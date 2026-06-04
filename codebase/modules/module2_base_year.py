"""
Module 2 — Base-year road structure and calibration preparation.

Responsibilities:
- Define the full road branch skeleton: transport_type × vehicle_type × size ×
  drive_type × fuel, enumerated from config.
- Expand the skeleton across all economies × scenarios.
- Populate base-year stock, mileage, and efficiency from the merged input table (T3).
- Construct LEAP branch paths including the size-qualified technology label
  (e.g. 'ICE medium', 'BEV large').
- Validate coverage against the LEAP workbook ID lookup (optional).
- Produce T4_base_year_branches for Modules 3–6.

Does NOT do fuel reconciliation (that is Module 6).

Size handling:
- LPVs have sizes [small, medium, large]; Trucks have [medium, heavy].
- Motorcycles, Buses, LCVs have no size split (size = None).
- If T3 carries a 'size' column (from the 9th edition adapter), the join is exact.
- If T3 has no 'size' column, stocks are distributed equally across sizes and
  mileage/efficiency are replicated unchanged.  Both cases are flagged.

LEAP ID join (optional):
- If leap_workbook_path is supplied, load_leap_id_lookup() is called and a
  left-join adds 'branch_id' to T4.  Missing rows (LEAP branches the model
  has not populated) are logged as warnings.  This acts as an early-stage
  coverage check (Section 10 answer C3 of the audit report).

Outputs: T4_base_year_branches DataFrame.
"""

from __future__ import annotations

import logging
import yaml
from pathlib import Path

import pandas as pd

from diagnostics.module_charts import write_module2_charts
from schemas.validation import validate_table

log = logging.getLogger(__name__)

# Columns populated from T3 via variable pivot
_T3_VARIABLES = {
    "stock":      ("stock",                "stock_source_flag"),
    "mileage":    ("mileage_km_per_year",  "mileage_source_flag"),
    "efficiency": ("efficiency_km_per_gj", "efficiency_source_flag"),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_module2(
    merged_inputs: pd.DataFrame,
    config_dir: str | Path = "config",
    economies: list[str] | None = None,
    scenarios: list[str] | None = None,
    base_year: int = 2022,
    leap_workbook_path: str | Path | None = None,
    diagnostics_dir: str | Path | None = None,
) -> pd.DataFrame:
    """
    Run Module 2: build the base-year road branch table (T4).

    Args:
        merged_inputs: T3_merged_inputs DataFrame from Module 1.
            Must contain 'economy', 'scenario', 'year', 'transport_type',
            'vehicle_type', 'drive_type', 'variable', 'value', 'source_flag'.
            Optional 'size' column enables exact size-level join.
        config_dir: Directory containing vehicle_mappings.yaml and
            fuel_mappings.yaml.
        economies: Economy codes to include.  Defaults to all found in
            merged_inputs.
        scenarios: Scenario labels to include.  Defaults to all found in
            merged_inputs.
        base_year: Base year to extract from merged_inputs (default 2022).
        leap_workbook_path: Optional path to the LEAP import workbook.
            If supplied, branch_id is joined onto T4 and coverage gaps are
            logged.
        diagnostics_dir: Optional directory root for Module 2 PNG diagnostic
            charts. When provided, charts are written to
            diagnostics_dir/module2/.

    Returns:
        T4_base_year_branches DataFrame.
    """
    config_dir = Path(config_dir)
    fuel_cfg = _load_fuel_config(config_dir)
    vehicle_cfg = _load_vehicle_config(config_dir)

    # --- 1. Build branch skeleton (size-aware) ---
    skeleton = _build_branch_skeleton(vehicle_cfg, fuel_cfg)
    skeleton = _add_leap_branch_paths(skeleton)
    log.info("Branch skeleton: %d rows across %d vehicle types",
             len(skeleton), skeleton["vehicle_type"].nunique())

    # --- 2. Determine economies and scenarios ---
    all_economies = economies or sorted(merged_inputs["economy"].dropna().unique())
    all_scenarios = scenarios or sorted(merged_inputs["scenario"].dropna().unique())

    # --- 3. Cross-join skeleton × economies × scenarios ---
    econ_scen = pd.DataFrame(
        [{"economy": e, "scenario": s} for e in all_economies for s in all_scenarios]
    )
    # Use a temporary merge key for the cartesian product
    econ_scen["_k"] = 1
    skeleton["_k"] = 1
    branches = econ_scen.merge(skeleton, on="_k").drop(columns="_k")
    branches["base_year"] = base_year
    log.info("Expanded branch table: %d rows (%d economies × %d scenarios × %d branch types)",
             len(branches), len(all_economies), len(all_scenarios),
             len(skeleton))

    # --- 4. Populate base-year values from T3 ---
    t4 = _populate_base_year_values(branches, merged_inputs, base_year)

    # --- 5. Optional LEAP ID join ---
    if leap_workbook_path is not None:
        t4 = _join_leap_ids(t4, leap_workbook_path)

    # --- 6. Validate ---
    errors = validate_table(t4, "T4_base_year_branches")
    for err in errors:
        log.warning("Validation: %s", err)

    if diagnostics_dir is not None:
        try:
            written = write_module2_charts(t4, diagnostics_dir)
            log.info("Module 2 diagnostics: wrote %d chart(s)", len(written))
        except Exception as exc:
            log.warning("Module 2 diagnostics chart generation failed: %s", exc)

    return t4.reset_index(drop=True)


def build_leap_branch_path(
    transport_type: str,
    vehicle_type: str,
    drive_type: str,
    fuel: str,
    size: str | None = None,
) -> str:
    """
    Build a LEAP branch path from dimension components.

    The technology label is '{drive_type} {size}' when size is present,
    or just '{drive_type}' for vehicle types without a size split.

    Args:
        transport_type: 'passenger' or 'freight'.
        vehicle_type: LEAP vehicle type label e.g. 'LPVs'.
        drive_type: 'ICE', 'HEV', 'PHEV', 'EREV', 'BEV', 'FCEV'.
        fuel: LEAP fuel name e.g. 'Motor gasoline'.
        size: 'small', 'medium', 'large', 'heavy', or None.

    Returns:
        Backslash-separated LEAP branch path string.

    Examples:
        >>> build_leap_branch_path('passenger', 'LPVs', 'ICE', 'Motor gasoline', 'medium')
        'Demand\\\\Transport passenger road\\\\LPVs\\\\ICE medium\\\\Motor gasoline'
        >>> build_leap_branch_path('passenger', 'Buses', 'BEV', 'Electricity')
        'Demand\\\\Transport passenger road\\\\Buses\\\\BEV\\\\Electricity'
    """
    transport_label = "Transport passenger road" if transport_type == "passenger" else "Transport freight road"
    tech = f"{drive_type} {size}" if size else drive_type
    return f"Demand\\{transport_label}\\{vehicle_type}\\{tech}\\{fuel}"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_fuel_config(config_dir: Path) -> dict:
    with open(config_dir / "fuel_mappings.yaml") as f:
        return yaml.safe_load(f)


def _load_vehicle_config(config_dir: Path) -> dict:
    with open(config_dir / "vehicle_mappings.yaml") as f:
        return yaml.safe_load(f)


def _build_branch_skeleton(vehicle_cfg: dict, fuel_cfg: dict) -> pd.DataFrame:
    """
    Enumerate all valid (transport_type, vehicle_type, size, drive_type, fuel)
    combinations for road transport.

    Size is drawn from vehicle_type_sizes in vehicle_mappings.yaml.
    For vehicle types with no size split the size cell is None.
    """
    eligibility = fuel_cfg["drive_fuel_eligibility"]
    bucket_transport = vehicle_cfg["bucket_transport_type"]
    vehicle_sizes = vehicle_cfg.get("vehicle_type_sizes", {})
    valid_drives = vehicle_cfg.get("valid_drive_types_by_vehicle_type", {})

    rows = []
    for vehicle_type, transport_type in bucket_transport.items():
        sizes = vehicle_sizes.get(vehicle_type, [None])
        allowed_drives = valid_drives.get(vehicle_type, list(eligibility))
        for size in sizes:
            # yaml null → Python None; keep as-is
            actual_size = None if size == "null" or size is None else size
            for drive_type, fuel_groups in eligibility.items():
                if drive_type not in allowed_drives:
                    continue
                all_fuels: list[str] = []
                for fuel_list in fuel_groups.values():
                    all_fuels.extend(fuel_list)
                for fuel in all_fuels:
                    rows.append({
                        "transport_type": transport_type,
                        "vehicle_type":   vehicle_type,
                        "size":           actual_size,
                        "drive_type":     drive_type,
                        "fuel":           fuel,
                    })

    return pd.DataFrame(rows).drop_duplicates(
        subset=["transport_type", "vehicle_type", "size", "drive_type", "fuel"]
    )


def _add_leap_branch_paths(df: pd.DataFrame) -> pd.DataFrame:
    """Add leap_branch_path column using size-qualified technology labels."""
    df = df.copy()
    def _clean_size(value: object) -> str | None:
        return None if pd.isna(value) or value == "null" else str(value)

    df["leap_branch_path"] = df.apply(
        lambda r: build_leap_branch_path(
            r["transport_type"],
            r["vehicle_type"],
            r["drive_type"],
            r["fuel"],
            size=_clean_size(r.get("size")),
        ),
        axis=1,
    )
    return df


def _populate_base_year_values(
    branches: pd.DataFrame,
    merged_inputs: pd.DataFrame,
    base_year: int,
) -> pd.DataFrame:
    """
    Join base-year stock, mileage, and efficiency from T3 onto the branch table.

    T3 is in tall format (variable / value rows).  This function pivots T3 for
    the three required variables and left-joins onto branches.

    Size handling:
    - If T3 has a 'size' column: join on (economy, scenario, vehicle_type,
      drive_type, size).  Values land on the correct size row directly.
    - If T3 has no 'size' column: join on (economy, scenario, vehicle_type,
      drive_type).  The same value is replicated to all sizes for mileage and
      efficiency.  Stock is split equally across sizes, flagged as
      'size_equal_split'.
    """
    base_data = merged_inputs[merged_inputs["year"] == base_year].copy()

    has_size = "size" in base_data.columns and base_data["size"].notna().any()

    base_join_keys = ["economy", "scenario", "transport_type", "vehicle_type", "drive_type"]
    if has_size:
        base_join_keys.append("size")

    # Pivot each variable into its own wide column
    wide_parts: list[pd.DataFrame] = []
    for var, (col_name, flag_col) in _T3_VARIABLES.items():
        sub = (
            base_data[base_data["variable"] == var]
            [base_join_keys + ["value", "source_flag"]]
            .copy()
        )
        if sub.empty:
            continue
        sub = sub.rename(columns={"value": col_name, "source_flag": flag_col})
        sub = sub.drop_duplicates(subset=base_join_keys)
        wide_parts.append(sub.set_index(base_join_keys))

    if wide_parts:
        wide = wide_parts[0]
        for part in wide_parts[1:]:
            wide = wide.join(part, how="outer")
        wide = wide.reset_index()
    else:
        wide = pd.DataFrame(columns=base_join_keys)

    if has_size:
        t4 = branches.merge(wide, on=base_join_keys, how="left")
    else:
        # Join without size, then handle the size replication
        t4 = branches.merge(wide, on=base_join_keys, how="left")
        t4 = _split_stock_equally_across_sizes(t4)

    # Fallback: broadcast vehicle_type-level mileage/efficiency to all drives.
    # Module 1 stores mileage at vehicle_type (or size-category) level with
    # non-standard drive labels (e.g. "Heavy", "Passenger") rather than actual
    # drive types (ICE, HEV, PHEV, EREV, BEV, FCEV). The exact drive_type join above misses these.
    # For each null, look for any mileage/efficiency value for the same
    # (economy, scenario, transport_type, vehicle_type) and replicate it.
    vt_fallback_keys = ["economy", "scenario", "transport_type", "vehicle_type"]
    for var, (col_name, flag_col) in _T3_VARIABLES.items():
        if var == "stock":
            continue  # stock broadcast doesn't make sense
        if col_name not in t4.columns or not t4[col_name].isna().any():
            continue
        fb_col = f"_fb_{col_name}"
        fb_flag_col = f"_fb_{flag_col}"
        granularity_col = f"{var}_granularity"
        fallback = (
            wide[vt_fallback_keys + [col_name, flag_col]]
            .dropna(subset=[col_name])
            .groupby(vt_fallback_keys)
            .agg(
                **{
                    fb_col: (col_name, "mean"),
                    fb_flag_col: (flag_col, lambda s: s.dropna().mode().iat[0] if not s.dropna().empty else "missing"),
                }
            )
            .reset_index()
        )
        t4 = t4.merge(fallback, on=vt_fallback_keys, how="left").reset_index(drop=True)
        was_null  = t4[col_name].isna()
        has_fb    = t4[fb_col].notna()
        n_filled  = int((was_null & has_fb).sum())
        if n_filled:
            t4[col_name] = t4[col_name].fillna(t4[fb_col])
            t4[flag_col] = t4[flag_col].where(~(was_null & has_fb), t4[fb_flag_col])
            t4[granularity_col] = t4.get(granularity_col, pd.Series("branch_level", index=t4.index))
            t4[granularity_col] = t4[granularity_col].where(
                ~(was_null & has_fb),
                "vehicle_type_level_broadcast",
            )
            log.info("Filled %d null %s values from vehicle_type-level fallback", n_filled, col_name)
        t4 = t4.drop(columns=[fb_col, fb_flag_col])

    # Ensure required source flag columns exist (fill NaN → 'missing')
    for _, (_, flag_col) in _T3_VARIABLES.items():
        if flag_col not in t4.columns:
            t4[flag_col] = "missing"
        else:
            t4[flag_col] = t4[flag_col].fillna("missing")

    for var, (col_name, _) in _T3_VARIABLES.items():
        granularity_col = f"{var}_granularity"
        if granularity_col not in t4.columns:
            t4[granularity_col] = "branch_level"
        else:
            t4[granularity_col] = t4[granularity_col].fillna("branch_level")

    return t4


def _split_stock_equally_across_sizes(t4: pd.DataFrame) -> pd.DataFrame:
    """
    When T3 has no size column, stocks need to be divided among sizes.

    For each (economy, scenario, vehicle_type, drive_type) group that has
    multiple sizes, divide stock equally.  Mileage and efficiency are replicated
    unchanged.  Rows with a single size (or null size) are untouched.

    The stock_granularity column is updated to 'size_equal_split' for affected rows.
    """
    if "size" not in t4.columns or "stock" not in t4.columns:
        return t4

    group_keys = ["economy", "scenario", "transport_type", "vehicle_type", "drive_type", "fuel"]
    size_counts = (
        t4[group_keys + ["size"]]
        .drop_duplicates()
        .groupby(group_keys)["size"]
        .count()
        .rename("n_sizes")
        .reset_index()
    )

    t4 = t4.merge(size_counts, on=group_keys, how="left")
    needs_split = (t4["n_sizes"] > 1) & t4["stock"].notna()

    if needs_split.any():
        t4.loc[needs_split, "stock"] = t4.loc[needs_split, "stock"] / t4.loc[needs_split, "n_sizes"]
        t4["stock_granularity"] = t4.get("stock_granularity", pd.Series("branch_level", index=t4.index))
        t4.loc[needs_split, "stock_granularity"] = "size_equal_split"
        log.warning(
            "%d rows had stock divided equally across %d size class(es) — "
            "provide size-split T3 for economy-specific calibration.",
            needs_split.sum(),
            int(t4.loc[needs_split, "n_sizes"].max()),
        )

    return t4.drop(columns=["n_sizes"])


def _join_leap_ids(t4: pd.DataFrame, leap_workbook_path: str | Path) -> pd.DataFrame:
    """
    Left-join LEAP branch IDs onto T4 and log coverage gaps.

    Adds 'branch_id' column to t4 (NaN where no LEAP match).
    Missing rows (LEAP branches not covered by the model) are logged.
    Extra rows (model branches not in LEAP) are also logged.
    """
    from adapters.leap_workbook import load_leap_id_lookup

    try:
        leap_ids = load_leap_id_lookup(leap_workbook_path, road_only=True)
    except Exception as exc:
        log.warning("Could not load LEAP ID lookup from %s: %s", leap_workbook_path, exc)
        return t4

    # Build a minimal model_df for coverage checking
    model_paths = t4[["leap_branch_path"]].drop_duplicates()
    # We don't have variable/scenario at T4 level; check branch paths only
    leap_paths = leap_ids[["leap_branch_path"]].drop_duplicates()

    in_leap = set(leap_paths["leap_branch_path"])
    in_model = set(model_paths["leap_branch_path"])

    missing = in_leap - in_model
    extra = in_model - in_leap

    if missing:
        log.warning(
            "LEAP ID coverage: %d LEAP branch path(s) not produced by Module 2 (first 5: %s)",
            len(missing), sorted(missing)[:5],
        )
    if extra:
        log.warning(
            "LEAP ID coverage: %d model branch path(s) not in LEAP workbook (first 5: %s)",
            len(extra), sorted(extra)[:5],
        )
    log.info(
        "LEAP ID coverage: %d matched, %d missing from model, %d extra in model",
        len(in_leap & in_model), len(missing), len(extra),
    )

    # Join branch_id
    branch_id_map = (
        leap_ids[["leap_branch_path", "branch_id"]]
        .drop_duplicates("leap_branch_path")
    )
    return t4.merge(branch_id_map, on="leap_branch_path", how="left")
