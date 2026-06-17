#%%
"""Export Module 4 age profiles as LEAP-compatible lifecycle profile workbooks.

The road model produces survival and vintage profiles in Module 4 as a tidy
age-indexed table. This adapter writes those profiles to the simple LEAP
lifecycle workbook format used by the transport workflow:

Area/Profile metadata rows, a blank separator, then Year/Value profile rows.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


# Stable output settings
MANIFEST_FILENAME = "lifecycle_profile_manifest.csv"
XLSX_FILENAME_TEMPLATE = "{economy}_lifecycle_profiles.xlsx"


#%%
# --- Validation helpers ---


def _normalise_vehicle_token(vehicle_type: str) -> str:
    """Create a filesystem-safe vehicle token while preserving readable names."""
    token = str(vehicle_type).strip().replace(" ", "_").replace("/", "_")
    return "".join(ch for ch in token if ch.isalnum() or ch in {"_", "-"})


def _validate_t6v_columns(t6v: pd.DataFrame) -> None:
    required = {"transport_type", "vehicle_type", "age", "vintage_share", "survival_probability"}
    missing = sorted(required - set(t6v.columns))
    if missing:
        raise ValueError(f"T6v is missing required lifecycle columns: {missing}")


def _clean_age_profile(
    rows: pd.DataFrame,
    *,
    vehicle_type: str,
) -> pd.DataFrame:
    """Validate one vehicle type's age rows and return a sorted copy."""
    profile = rows.copy()
    profile["age"] = pd.to_numeric(profile["age"], errors="coerce")
    profile["vintage_share"] = pd.to_numeric(profile["vintage_share"], errors="coerce")
    profile["survival_probability"] = pd.to_numeric(profile["survival_probability"], errors="coerce")
    profile = profile.dropna(subset=["age", "vintage_share", "survival_probability"])

    if profile.empty:
        raise ValueError(f"No valid lifecycle age rows found for {vehicle_type}.")

    if not np.allclose(profile["age"], np.round(profile["age"])):
        raise ValueError(f"Lifecycle ages must be integer years for {vehicle_type}.")

    profile["age"] = profile["age"].round().astype(int)
    if profile["age"].duplicated().any():
        duplicated = sorted(profile.loc[profile["age"].duplicated(), "age"].unique().tolist())
        raise ValueError(f"Duplicate lifecycle ages for {vehicle_type}: {duplicated}")

    profile = profile.sort_values("age").reset_index(drop=True)
    ages = profile["age"].to_numpy(dtype=int)
    if len(ages) > 1 and not np.array_equal(np.diff(ages), np.ones(len(ages) - 1, dtype=int)):
        raise ValueError(f"Lifecycle ages must be contiguous for {vehicle_type}.")

    survival = profile["survival_probability"].astype(float)
    if ((survival < 0.0) | (survival > 1.0)).any():
        raise ValueError(f"Survival probabilities must be in [0, 1] for {vehicle_type}.")

    vintage = profile["vintage_share"].astype(float)
    if (vintage < 0.0).any():
        raise ValueError(f"Vintage shares must be non-negative for {vehicle_type}.")
    vintage_total = float(vintage.sum())
    if vintage_total <= 0.0:
        raise ValueError(f"Vintage shares must sum to a positive value for {vehicle_type}.")

    return profile


def _annual_survival_to_cumulative_percent(annual_survival: pd.Series) -> pd.Series:
    """Convert Module 4 annual survival probabilities to LEAP cumulative percent."""
    annual = pd.Series(annual_survival, dtype=float).sort_index().clip(0.0, 1.0)
    if annual.empty:
        raise ValueError("annual_survival must not be empty.")

    ages = list(annual.index)
    cumulative_values: list[float] = []
    current = 1.0
    for idx, age in enumerate(ages):
        if idx == 0:
            current = 1.0
        else:
            previous_age = ages[idx - 1]
            current *= float(annual.loc[previous_age])
        cumulative_values.append(current * 100.0)

    return pd.Series(cumulative_values, index=annual.index, dtype=float)


def _vintage_to_percent(vintage_share: pd.Series) -> pd.Series:
    """Convert Module 4 vintage shares to percent and renormalise to 100."""
    vintage = pd.Series(vintage_share, dtype=float).sort_index().clip(lower=0.0)
    total = float(vintage.sum())
    if total <= 0.0:
        raise ValueError("vintage_share must sum to a positive value.")
    return (vintage / total) * 100.0


def validate_lifecycle_profile(profile: pd.Series, *, profile_type: str, profile_name: str) -> dict[str, float | int | bool]:
    """Validate a profile series and return compact diagnostics."""
    series = pd.Series(profile, dtype=float).sort_index()
    if series.empty:
        raise ValueError(f"{profile_name} is empty.")
    if series.index.has_duplicates:
        raise ValueError(f"{profile_name} has duplicate ages.")
    if not np.allclose(series.index.to_numpy(dtype=float), np.round(series.index.to_numpy(dtype=float))):
        raise ValueError(f"{profile_name} ages must be integer years.")
    if (series < 0.0).any():
        raise ValueError(f"{profile_name} has negative values.")

    profile_type_norm = str(profile_type).strip().lower()
    total = float(series.sum())
    is_valid = True
    if profile_type_norm == "vehicle_survival":
        if abs(float(series.iloc[0]) - 100.0) > 1e-6:
            raise ValueError(f"{profile_name} survival profile must start at 100.")
        if (series.diff().dropna() > 1e-6).any():
            raise ValueError(f"{profile_name} survival profile must be non-increasing.")
    elif profile_type_norm == "vintage":
        if abs(total - 100.0) > 1e-6:
            raise ValueError(f"{profile_name} vintage profile must sum to 100; got {total}.")

    return {
        "age_min": int(series.index.min()),
        "age_max": int(series.index.max()),
        "row_count": int(len(series)),
        "value_sum": total,
        "is_valid": is_valid,
    }


#%%
# --- Workbook writing ---


def _profile_rows(area_name: str, profile_name: str, profile: pd.Series) -> pd.DataFrame:
    rows: list[list[object]] = [
        ["Area:", area_name],
        ["Profile:", profile_name],
        [None, None],
        ["Year", "Value"],
    ]
    for age, value in pd.Series(profile, dtype=float).sort_index().items():
        rows.append([int(age), float(value)])
    return pd.DataFrame(rows)


def write_lifecycle_profile_excel(
    output_path: str | Path,
    *,
    area_name: str,
    profile_name: str,
    profile: pd.Series,
    sheet_name: str = "Lifecycle Profiles",
) -> Path:
    """Write one LEAP-compatible lifecycle profile workbook."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out_df = _profile_rows(area_name=area_name, profile_name=profile_name, profile=profile)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        out_df.to_excel(writer, sheet_name=sheet_name, index=False, header=False)
    return path


def export_lifecycle_profiles_from_t6v(
    t6v: pd.DataFrame,
    output_dir: str | Path,
    *,
    economy: str,
    area_name: str | None = None,
) -> dict[str, Path | pd.DataFrame]:
    """Export survival and vintage profiles from T6v into a single multi-sheet workbook.

    Profiles are assumed to be identical across vehicle types within a transport
    type, so one representative vehicle type is used per group.

    Returns a dict with:
    - ``manifest_path``: CSV manifest with one row per sheet
    - ``xlsx_path``: single XLSX workbook containing all profiles
    - ``manifest``: manifest DataFrame
    """
    _validate_t6v_columns(t6v)
    # Lifecycle profiles are scenario-independent; drop duplicates introduced by
    # multi-scenario concatenation in the workflow before iterating transport types.
    t6v = t6v.drop_duplicates(subset=["transport_type", "vehicle_type", "age"])
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    area = area_name or f"{economy} transport"

    manifest_rows: list[dict[str, object]] = []
    sheet_data: list[tuple[str, pd.DataFrame]] = []

    profile_specs = [
        ("vehicle_survival", "Vehicle Survival"),
        ("vintage", "Vintage Profile"),
    ]

    for transport_type in sorted(t6v["transport_type"].dropna().astype(str).unique()):
        tt_rows = t6v[t6v["transport_type"].astype(str) == transport_type]
        representative_vt = tt_rows["vehicle_type"].dropna().astype(str).iloc[0]
        rows = _clean_age_profile(
            tt_rows[tt_rows["vehicle_type"].astype(str) == representative_vt],
            vehicle_type=representative_vt,
        )
        by_age = rows.set_index("age")

        survival_profile = _annual_survival_to_cumulative_percent(by_age["survival_probability"])
        vintage_profile = _vintage_to_percent(by_age["vintage_share"])

        for profile_type, label in profile_specs:
            profile = survival_profile if profile_type == "vehicle_survival" else vintage_profile
            profile_name = f"{economy} {transport_type} {label}"
            diagnostics = validate_lifecycle_profile(
                profile,
                profile_type=profile_type,
                profile_name=profile_name,
            )
            sheet_name = f"{transport_type} {label}"[:31]
            out_df = _profile_rows(area_name=area, profile_name=profile_name, profile=profile)
            sheet_data.append((sheet_name, out_df))
            manifest_rows.append(
                {
                    "economy": economy,
                    "transport_type": transport_type,
                    "profile_type": profile_type,
                    "profile_name": profile_name,
                    "area_name": area,
                    "sheet_name": sheet_name,
                    **diagnostics,
                }
            )

    if not manifest_rows:
        raise ValueError("No lifecycle profiles were exported; T6v had no transport_type rows.")

    manifest = pd.DataFrame(manifest_rows)
    manifest_path = out_dir / MANIFEST_FILENAME
    manifest.to_csv(manifest_path, index=False)

    xlsx_path = out_dir / XLSX_FILENAME_TEMPLATE.format(economy=economy)
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        for sheet_name, out_df in sheet_data:
            out_df.to_excel(writer, sheet_name=sheet_name, index=False, header=False)

    return {
        "manifest_path": manifest_path,
        "manifest": manifest,
        "xlsx_path": xlsx_path,
    }


#%%
# --- Notebook-friendly run block ---

ECONOMY = "20_USA"
RESULTS_ROOT = Path("results")
T6V_INPUT_PATH = RESULTS_ROOT / ECONOMY / "module4" / "T6v_vintage_profiles.csv"
OUTPUT_DIR = RESULTS_ROOT / ECONOMY / "lifecycle_profiles"
RUN_EXPORT_FROM_SAVED_T6V = False


if __name__ == "__main__" and RUN_EXPORT_FROM_SAVED_T6V:
    t6v_df = pd.read_csv(T6V_INPUT_PATH)
    export_result = export_lifecycle_profiles_from_t6v(
        t6v_df,
        OUTPUT_DIR,
        economy=ECONOMY,
    )
    print(f"Manifest: {export_result['manifest_path']}")
    print(f"XLSX: {export_result.get('xlsx_path')}")

#%%
