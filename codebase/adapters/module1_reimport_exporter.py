#%%
"""
Build a canonical Module 1 CSV with reconciled base-year values.

The exporter starts from the original Module 1 long CSV so row keys and
interface metadata remain compatible with the road_model_inputs_interface upload
flow. It replaces base-year Stock, Stock Share, Mileage, and Fuel Economy values
that were recalculated by Module 6.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from adapters.road_module1_defaults import _iter_package_csvs, _resolve_package_root
from modules.reconciliation_aggregation import build_reconciled_technology_assumptions


MODULE1_REIMPORT_COLUMNS = [
    "Economy",
    "Scenario",
    "Branch Path",
    "Variable",
    "Year",
    "Value",
    "Scale",
    "Units",
    "Source",
    "Comment",
    "Input Status",
    "Shown In Interface",
]

RECONCILED_REIMPORT_VARIABLES = {"Stock", "Stock Share", "Mileage", "Fuel Economy"}

_SCALE_MULTIPLIERS = {
    "": 1.0,
    "%": 1.0,
    "thousand": 1_000.0,
    "thousands": 1_000.0,
    "million": 1_000_000.0,
    "millions": 1_000_000.0,
    "billion": 1_000_000_000.0,
    "billions": 1_000_000_000.0,
}


def find_module1_source_csv(
    defaults_dir: str | Path,
    economy: str,
    version: str | None = None,
) -> Path:
    """Return the Module 1 CSV currently used by the workflow for one economy."""
    package_root = _resolve_package_root(Path(defaults_dir), version)
    matches = [
        csv_path
        for found_economy, csv_path in _iter_package_csvs(package_root, economy_filter=[economy])
        if found_economy == economy
    ]
    if not matches:
        raise FileNotFoundError(
            f"Module 1 source CSV not found for {economy} in {package_root}"
        )
    return matches[0]


def load_module1_source_long_csv(
    defaults_dir: str | Path,
    economy: str,
    version: str | None = None,
) -> pd.DataFrame:
    """Load the original canonical long Module 1 CSV for one economy."""
    csv_path = find_module1_source_csv(defaults_dir, economy=economy, version=version)
    source = pd.read_csv(csv_path, low_memory=False)
    missing = [col for col in ["Branch Path", "Variable", "Scenario", "Year", "Value"] if col not in source.columns]
    if missing:
        raise ValueError(
            f"Reconciled Module 1 re-import requires a canonical long CSV. "
            f"{csv_path} is missing columns: {missing}"
        )
    return source


def build_reconciled_module1_reimport(
    source_long_df: pd.DataFrame,
    leap_ready: pd.DataFrame,
    base_year: int,
    reconciliation_scalars: pd.DataFrame | None = None,
    stock_targets: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Return a canonical long Module 1 CSV suitable for re-upload.

    The source CSV is carried through unchanged so the next run sees the same
    base-year inputs (T4) and produces identical base-year reconciliation (T9).
    If ``stock_targets`` (T5 post-reconciliation) is supplied, "Stock Target"
    rows are appended for every projection year so that a second model run
    started from this CSV produces identical stock trajectories to the first.
    """
    source_long_df = source_long_df.drop_duplicates().copy()
    source_long_df = source_long_df.drop_duplicates(
        subset=["Branch Path", "Variable", "Scenario", "Year"],
        keep="first",
    ).copy()
    _validate_unique_keys(source_long_df, context="source Module 1")

    out = _ensure_reimport_columns(source_long_df)
    out = out[out["Shown In Interface"].astype(str).str.strip().str.lower().ne("false")]

    if stock_targets is not None:
        # Remove any stale "Stock Target" rows carried over from a previous reconciled CSV
        # (they are replaced below with fresh values from the current T5).
        out = out[out["Variable"] != "Stock Target"]
        target_rows = _build_stock_target_rows(
            stock_targets,
            reconciliation_scalars=reconciliation_scalars,
            source_long_df=source_long_df,
        )
        if not target_rows.empty:
            out = pd.concat([out, target_rows], ignore_index=True)

    _validate_unique_keys(out, context="reconciled Module 1 re-import")
    return out[MODULE1_REIMPORT_COLUMNS].copy()


def write_reconciled_module1_reimport_csv(
    source_long_df: pd.DataFrame,
    leap_ready: pd.DataFrame,
    output_path: str | Path,
    base_year: int,
    reconciliation_scalars: pd.DataFrame | None = None,
    stock_targets: pd.DataFrame | None = None,
) -> Path:
    """Build and write the reconciled Module 1 re-import CSV."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out = build_reconciled_module1_reimport(
        source_long_df=source_long_df,
        leap_ready=leap_ready,
        base_year=base_year,
        reconciliation_scalars=reconciliation_scalars,
        stock_targets=stock_targets,
    )
    out.to_csv(output_path, index=False)
    return output_path


def _ensure_reimport_columns(source_long_df: pd.DataFrame) -> pd.DataFrame:
    out = source_long_df.copy()
    for col in MODULE1_REIMPORT_COLUMNS:
        if col not in out.columns:
            out[col] = ""
    return out[MODULE1_REIMPORT_COLUMNS].copy()


def _build_replacement_values(
    leap_ready: pd.DataFrame,
    base_year: int,
    include_stock_share: bool = True,
) -> dict[tuple[str, str, str, int], float]:
    required = {"leap_branch_path", "variable", "scenario", "year", "value"}
    missing = sorted(required - set(leap_ready.columns))
    if missing:
        raise ValueError(f"T11_leap_ready is missing required columns: {missing}")

    rows = leap_ready.copy()
    variables = set(RECONCILED_REIMPORT_VARIABLES)
    if not include_stock_share:
        variables.discard("Stock Share")

    rows = rows[
        rows["variable"].isin(variables)
        & pd.to_numeric(rows["year"], errors="coerce").eq(int(base_year))
    ].copy()
    rows["value"] = pd.to_numeric(rows["value"], errors="coerce")
    rows = rows.dropna(subset=["value"])

    key_cols = ["leap_branch_path", "variable", "scenario", "year"]
    duplicates = rows.duplicated(subset=key_cols, keep=False)
    if duplicates.any():
        sample = rows.loc[duplicates, key_cols].head(5).to_dict("records")
        raise ValueError(f"T11_leap_ready has duplicate Module 1 re-import keys: {sample}")

    return {
        (str(row["leap_branch_path"]), str(row["variable"]), str(row["scenario"]), int(row["year"])): float(row["value"])
        for _, row in rows.iterrows()
    }


def _build_stock_share_replacements_from_t9(
    reconciliation_scalars: pd.DataFrame,
    base_year: int,
) -> dict[tuple[str, str, str, int], float]:
    """Build vehicle- and technology-level Stock Share replacements from T9."""
    if reconciliation_scalars.empty:
        return {}
    tech_rows = build_reconciled_technology_assumptions(reconciliation_scalars)
    if tech_rows.empty:
        return {}

    tech_rows = tech_rows.copy()
    tech_rows["_tech_path"] = tech_rows["leap_branch_path"].astype(str)
    tech_rows["_vehicle_path"] = tech_rows["leap_branch_path"].astype(str).map(_vehicle_path)
    tech_rows["_transport_path"] = tech_rows["leap_branch_path"].astype(str).map(_transport_path)

    replacements: dict[tuple[str, str, str, int], float] = {}
    scenario_values = set(tech_rows.get("scenario", pd.Series(["Target"])).dropna().astype(str))
    scenario_values.add("Current Accounts")

    transport_totals = tech_rows.groupby("_transport_path", dropna=False)["adjusted_stock"].sum().to_dict()
    vehicle_totals = tech_rows.groupby("_vehicle_path", dropna=False)["adjusted_stock"].sum().to_dict()

    vehicle_share_rows = tech_rows.groupby(
        ["_transport_path", "_vehicle_path"],
        dropna=False,
        as_index=False,
    )["adjusted_stock"].sum()
    for _, row in vehicle_share_rows.iterrows():
        transport_total = float(transport_totals.get(row["_transport_path"], 0.0))
        value = float(row["adjusted_stock"]) / transport_total * 100.0 if transport_total > 0 else 0.0
        for scenario in scenario_values:
            replacements[(str(row["_vehicle_path"]), "Stock Share", scenario, int(base_year))] = value

    tech_share_rows = tech_rows.groupby(
        ["_vehicle_path", "_tech_path"],
        dropna=False,
        as_index=False,
    )["adjusted_stock"].sum()
    for _, row in tech_share_rows.iterrows():
        vehicle_total = float(vehicle_totals.get(row["_vehicle_path"], 0.0))
        value = float(row["adjusted_stock"]) / vehicle_total * 100.0 if vehicle_total > 0 else 0.0
        for scenario in scenario_values:
            replacements[(str(row["_tech_path"]), "Stock Share", scenario, int(base_year))] = value

    return replacements


def _parent_path(branch_path: str) -> str:
    parts = str(branch_path).rsplit("\\", 1)
    return parts[0] if len(parts) > 1 else str(branch_path)


def _tech_path(branch_path: str) -> str:
    parts = str(branch_path).rsplit("\\", 1)
    return parts[0] if len(parts) > 1 else str(branch_path)


def _vehicle_path(branch_path: str) -> str:
    return "\\".join(str(branch_path).split("\\")[:3])


def _transport_path(branch_path: str) -> str:
    return "\\".join(str(branch_path).split("\\")[:2])


def _build_stock_target_rows(
    stock_targets: pd.DataFrame,
    reconciliation_scalars: pd.DataFrame | None,
    source_long_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Build "Stock Target" rows for every (vehicle_type, scenario, year) in T5.

    The LEAP branch path at vehicle-type level is derived from T9
    (reconciliation_scalars) when available, otherwise inferred from the
    source CSV's existing "Stock" rows at the same path depth.
    """
    required = {"vehicle_type", "year", "target_stock"}
    if not required.issubset(stock_targets.columns):
        return pd.DataFrame()

    # Build vehicle_type → vehicle-level LEAP branch path mapping
    vt_to_path: dict[str, str] = {}
    if reconciliation_scalars is not None and "leap_branch_path" in reconciliation_scalars.columns and "vehicle_type" in reconciliation_scalars.columns:
        for _, row in reconciliation_scalars.drop_duplicates("vehicle_type").iterrows():
            vt = str(row["vehicle_type"])
            path = _vehicle_path(str(row["leap_branch_path"]))
            vt_to_path[vt] = path

    # Fall back to deriving paths from source "Stock" rows at 3-level depth
    if "Branch Path" in source_long_df.columns and "Variable" in source_long_df.columns:
        for _, row in source_long_df[source_long_df["Variable"] == "Stock"].iterrows():
            parts = str(row["Branch Path"]).split("\\")
            if len(parts) == 3:
                vt = parts[2]
                if vt not in vt_to_path:
                    vt_to_path[vt] = str(row["Branch Path"])

    economy = str(source_long_df["Economy"].iloc[0]) if "Economy" in source_long_df.columns else ""

    agg = (
        stock_targets
        .groupby(
            [c for c in ["scenario", "vehicle_type", "year"] if c in stock_targets.columns],
            dropna=False,
        )["target_stock"]
        .sum()
        .reset_index()
    )

    rows = []
    scenarios = agg["scenario"].dropna().unique().tolist() if "scenario" in agg.columns else ["Current Accounts"]
    for _, row in agg.iterrows():
        vt = str(row["vehicle_type"])
        branch_path = vt_to_path.get(vt)
        if branch_path is None:
            continue
        scenario = str(row.get("scenario", scenarios[0])) if "scenario" in row else scenarios[0]
        rows.append({
            "Economy": economy,
            "Scenario": scenario,
            "Branch Path": branch_path,
            "Variable": "Stock Target",
            "Year": int(row["year"]),
            "Value": float(row["target_stock"]) / 1_000_000.0,
            "Scale": "Millions",
            "Units": "Device",
            "Source": "reconciled",
            "Comment": "",
            "Input Status": "reconciled",
            "Shown In Interface": "False",
        })

    return pd.DataFrame(rows, columns=MODULE1_REIMPORT_COLUMNS) if rows else pd.DataFrame()


def _validate_unique_keys(df: pd.DataFrame, context: str) -> None:
    key_cols = ["Branch Path", "Variable", "Scenario", "Year"]
    missing = [col for col in key_cols if col not in df.columns]
    if missing:
        raise ValueError(f"{context} is missing key columns: {missing}")
    duplicates = df.duplicated(subset=key_cols, keep=False)
    if duplicates.any():
        sample = df.loc[duplicates, key_cols].head(5).to_dict("records")
        raise ValueError(f"{context} has duplicate Module 1 row keys: {sample}")


def _scale_multiplier(scale: object) -> float:
    text = "" if pd.isna(scale) else str(scale).strip().lower()
    return _SCALE_MULTIPLIERS.get(text, 1.0)


#%%
