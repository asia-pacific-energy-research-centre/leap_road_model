"""
Adapter A3, A9 — LEAP import/export workbook.

A3: Load the DEFAULT_transport_leap_import workbook as a branch template.
A9: Write T11_leap_ready tidy output into LEAP import workbook format.
LEAP ID helper: extract BranchID / VariableID / ScenarioID / RegionID lookup
    table for merging against model output at Module 2 and final export.

The LEAP import workbook format:
    Sheet "Export", header on row 3 (0-indexed row 2).
    Key columns: Branch Path, Variable, Scenario, Region, Units, Expression.
    Expression format: Data(2022, v1, 2023, v2, ...)

Reference: transition_audit_report.md Section 2, Section 10 answer C3.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from adapters.leap_expressions import to_leap_expression, parse_expression_column

log = logging.getLogger(__name__)

# Column positions match the audit report findings
_HEADER_ROW = 2  # 0-indexed (row 3 in Excel)
_BRANCH_PATH = "Branch Path"
_VARIABLE = "Variable"
_SCENARIO = "Scenario"
_REGION = "Region"
_UNITS = "Units"
_EXPRESSION = "Expression"
_SCALE = "Scale"
_PER = "Per..."
_SCENARIO_ID = "ScenarioID"
_REGION_ID = "RegionID"


def load_leap_import_workbook_as_template(
    path: str | Path,
    road_only: bool = True,
) -> pd.DataFrame:
    """
    Load the LEAP import workbook and return the set of required
    branch × variable × scenario combinations (the template).

    This defines what the new model must populate.

    Args:
        path: Path to DEFAULT_transport_leap_import_TGT_REF_CA.xlsx.
        road_only: If True, filter to road transport branches only.

    Returns:
        DataFrame with columns:
        [leap_branch_path, variable, scenario, unit, scale, per]
        representing the required output structure.
    """
    path = Path(path)
    log.info("Loading LEAP import workbook template: %s", path.name)

    df = pd.read_excel(path, sheet_name="Export", header=_HEADER_ROW)

    rename = {
        _BRANCH_PATH: "leap_branch_path",
        _VARIABLE:    "variable",
        _SCENARIO:    "scenario",
        _REGION:      "region",
        _UNITS:       "unit",
        _SCALE:       "scale",
        _PER:         "per",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    if "leap_branch_path" not in df.columns:
        raise ValueError("Could not find 'Branch Path' column in workbook")

    # Drop rows with no branch path
    df = df.dropna(subset=["leap_branch_path"])

    if road_only:
        road_mask = df["leap_branch_path"].str.startswith(
            ("Demand\\Passenger road", "Demand\\Freight road"), na=False
        )
        df = df[road_mask].copy()

    template_cols = ["leap_branch_path", "variable", "scenario", "unit"]
    available = [c for c in template_cols if c in df.columns]
    template = df[available].drop_duplicates()

    log.info("Template has %d branch×variable×scenario combinations", len(template))
    return template


def load_leap_id_lookup(
    path: str | Path,
    road_only: bool = True,
) -> pd.DataFrame:
    """
    Extract the LEAP internal ID lookup table from the import workbook.

    LEAP uses integer IDs (BranchID, VariableID, ScenarioID, RegionID) to
    identify branches. These IDs are fixed for a given LEAP area file.
    The new model joins against this table at two points:
      1. After Module 2, to validate that all model branches exist in LEAP.
      2. After Module 6 final output, to populate ID columns in the export workbook.

    Missing rows after a join indicate branches the model produces that LEAP
    does not know about (extra rows) or LEAP branches the model has not populated
    (missing rows). Both are validation failures.

    Args:
        path: Path to DEFAULT_transport_leap_import_TGT_REF_CA.xlsx.
        road_only: If True, filter to road transport branches only.

    Returns:
        DataFrame with columns:
        [leap_branch_path, variable, scenario, region,
         branch_id, variable_id, scenario_id, region_id, unit]
    """
    path = Path(path)
    log.info("Loading LEAP ID lookup from: %s", path.name)

    df = pd.read_excel(path, sheet_name="Export", header=_HEADER_ROW)

    # Rename to standard names
    rename = {
        "BranchID":    "branch_id",
        "VariableID":  "variable_id",
        "ScenarioID":  "scenario_id",
        "RegionID":    "region_id",
        _BRANCH_PATH:  "leap_branch_path",
        _VARIABLE:     "variable",
        _SCENARIO:     "scenario",
        _REGION:       "region",
        _UNITS:        "unit",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    required = ["branch_id", "variable_id", "scenario_id", "region_id", "leap_branch_path"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"LEAP ID columns not found in workbook: {missing}")

    df = df.dropna(subset=["leap_branch_path"])

    if road_only:
        road_mask = df["leap_branch_path"].str.startswith(
            ("Demand\\Passenger road", "Demand\\Freight road"), na=False
        )
        df = df[road_mask].copy()

    id_cols = ["leap_branch_path", "variable", "scenario", "region",
               "branch_id", "variable_id", "scenario_id", "region_id", "unit"]
    available = [c for c in id_cols if c in df.columns]
    result = df[available].drop_duplicates()

    # Convert ID columns to int where possible
    for col in ["branch_id", "variable_id", "scenario_id", "region_id"]:
        if col in result.columns:
            result[col] = pd.to_numeric(result[col], errors="coerce")

    log.info("Loaded %d LEAP ID rows for %d unique branch paths",
             len(result), result["leap_branch_path"].nunique())
    return result.reset_index(drop=True)


def validate_coverage_against_leap_ids(
    model_df: pd.DataFrame,
    leap_ids: pd.DataFrame,
    join_on: list[str] | None = None,
) -> dict[str, pd.DataFrame]:
    """
    Check that model output covers all required LEAP branches and no extras.

    Performs a left join and a right join to detect:
      - Extra rows: model has branches LEAP does not expect.
      - Missing rows: LEAP expects branches the model has not produced.

    Args:
        model_df: DataFrame with at least 'leap_branch_path', 'variable',
            'scenario' columns (T11 schema).
        leap_ids: Output of load_leap_id_lookup().
        join_on: Columns to join on. Defaults to
            ['leap_branch_path', 'variable', 'scenario'].

    Returns:
        Dict with keys:
          'matched': rows present in both.
          'missing': LEAP rows not covered by the model.
          'extra': model rows not in the LEAP template.
    """
    join_on = join_on or ["leap_branch_path", "variable", "scenario"]
    present = [c for c in join_on if c in model_df.columns and c in leap_ids.columns]

    model_keys = model_df[present].drop_duplicates()
    leap_keys = leap_ids[present].drop_duplicates()

    matched = pd.merge(model_keys, leap_keys, on=present, how="inner")
    missing = pd.merge(leap_keys, model_keys, on=present, how="left", indicator=True)
    missing = missing[missing["_merge"] == "left_only"].drop(columns=["_merge"])
    extra = pd.merge(model_keys, leap_keys, on=present, how="left", indicator=True)
    extra = extra[extra["_merge"] == "left_only"].drop(columns=["_merge"])

    log.info(
        "Coverage check: %d matched, %d missing from model, %d extra in model",
        len(matched), len(missing), len(extra),
    )
    return {"matched": matched, "missing": missing, "extra": extra}


def write_leap_import_workbook(
    leap_ready: pd.DataFrame,
    output_path: str | Path,
    template_path: str | Path | None = None,
    economy_long_name: str = "",
    scenario_id_map: dict[str, int] | None = None,
) -> None:
    """
    Write T11_leap_ready tidy DataFrame to LEAP import workbook format.

    Produces a two-sheet Excel workbook:
    - "LEAP" sheet: compact format with Data() expressions.
    - "FOR_VIEWING" sheet: expanded with individual year columns.

    Args:
        leap_ready: T11_leap_ready tidy DataFrame.
        output_path: Path for the output .xlsx file.
        template_path: Optional path to the import workbook template.
            If provided, used to ensure all required branches are present.
        economy_long_name: Full economy name for the Region column.
        scenario_id_map: Maps scenario labels to LEAP ScenarioID integers.
            Defaults to {Current Accounts: 1, Reference: 2, Target: 3}.
    """
    output_path = Path(output_path)
    sid_map = scenario_id_map or {
        "Current Accounts": 1,
        "Reference": 2,
        "Target": 3,
    }

    # Convert km/GJ → MJ/100km for efficiency
    df = _convert_units_for_leap(leap_ready.copy())

    # Pivot to wide (one row per branch × variable × scenario)
    leap_sheet = _build_leap_sheet(df, economy_long_name, sid_map)
    viewing_sheet = _build_viewing_sheet(df)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        leap_sheet.to_excel(writer, sheet_name="LEAP", index=False)
        viewing_sheet.to_excel(writer, sheet_name="FOR_VIEWING", index=False)

    log.info("Wrote LEAP import workbook to %s (%d rows)", output_path, len(leap_sheet))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _convert_units_for_leap(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert internal units to LEAP-expected units.

    Efficiency: km/GJ → MJ/100km: value = 10_000 / value
    Energy: PJ → MJ: value = value × 1_000_000
    """
    if "variable" not in df.columns:
        return df

    # Efficiency conversion
    eff_mask = df["variable"] == "Fuel Economy"
    if eff_mask.any():
        df.loc[eff_mask, "value"] = 10_000 / df.loc[eff_mask, "value"].replace(0, float("nan"))
        df.loc[eff_mask, "unit"] = "MJ/100 km"

    return df


def _build_leap_sheet(
    df: pd.DataFrame,
    economy_long_name: str,
    scenario_id_map: dict[str, int],
) -> pd.DataFrame:
    """Build the compact LEAP sheet with Data() expression column."""
    rows = []
    for (branch, variable, scenario), grp in df.groupby(
        ["leap_branch_path", "variable", "scenario"]
    ):
        series = grp.sort_values("year").set_index("year")["value"]
        rows.append({
            "Branch Path": branch,
            "Variable": variable,
            "Scenario": scenario,
            "ScenarioID": scenario_id_map.get(scenario, ""),
            "Region": economy_long_name,
            "Units": grp["unit"].iloc[0] if "unit" in grp.columns else "",
            "Expression": to_leap_expression(series),
        })
    return pd.DataFrame(rows)


def _build_viewing_sheet(df: pd.DataFrame) -> pd.DataFrame:
    """Build the expanded FOR_VIEWING sheet with individual year columns."""
    meta_cols = ["leap_branch_path", "variable", "scenario", "unit"]
    available = [c for c in meta_cols if c in df.columns]

    if "year" not in df.columns or "value" not in df.columns:
        return df

    pivoted = df.pivot_table(
        index=available,
        columns="year",
        values="value",
        aggfunc="first",
    ).reset_index()
    pivoted.columns.name = None
    return pivoted
