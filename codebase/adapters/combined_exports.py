"""
Adapter A1, A2 — LEAP combined exports.

Loads files from leap_transport/results/combined_exports/ and converts
them into tidy T11-compatible DataFrames for benchmark comparison.

Reference: transition_audit_report.md Section 1.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from adapters.leap_expressions import parse_expression_column

log = logging.getLogger(__name__)

# Column names in the LEAP sheet (0-indexed positions from audit report)
_BRANCH_PATH_COL = "Branch Path"
_VARIABLE_COL = "Variable"
_SCENARIO_COL = "Scenario"
_REGION_COL = "Region"
_UNITS_COL = "Units"
_EXPRESSION_COL = "Expression"
_SCALE_COL = "Scale"


def load_single_export(
    path: str | Path,
    sheet_name: str = "LEAP",
) -> pd.DataFrame:
    """
    Load one combined export workbook and return tidy T11-compatible DataFrame.

    Args:
        path: Path to the combined export Excel file.
        sheet_name: Sheet to read ('LEAP' or 'FOR_VIEWING').

    Returns:
        Tidy DataFrame with columns:
        [leap_branch_path, variable, scenario, region, unit, year, value,
         source='benchmark_combined_export']
    """
    path = Path(path)
    log.info("Loading combined export: %s", path.name)

    df = pd.read_excel(path, sheet_name=sheet_name, header=2)

    # Rename columns to standard names
    col_map = {}
    for col in df.columns:
        if "branch" in col.lower() and "path" in col.lower():
            col_map[col] = "leap_branch_path"
        elif col.lower() == "variable":
            col_map[col] = "variable"
        elif col.lower() == "scenario":
            col_map[col] = "scenario"
        elif col.lower() == "region":
            col_map[col] = "region"
        elif col.lower() == "units":
            col_map[col] = "unit"
        elif col.lower() == "expression":
            col_map[col] = "Expression"

    df = df.rename(columns=col_map)

    required = ["leap_branch_path", "variable", "scenario", "region", "unit", "Expression"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        log.warning("Missing columns in export: %s", missing)

    tidy = parse_expression_column(df, expression_col="Expression")
    tidy["source"] = "benchmark_combined_export"
    tidy["file"] = path.name

    return tidy


def load_combined_exports_as_benchmark(
    exports_dir: str | Path,
    economy_filter: list[str] | None = None,
    scenario_filter: list[str] | None = None,
    road_only: bool = True,
) -> pd.DataFrame:
    """
    Load all combined export workbooks from a directory.

    Args:
        exports_dir: Path to the combined_exports folder.
        economy_filter: Optional list of economy codes to keep.
        scenario_filter: Optional list of scenarios to keep.
        road_only: If True, filter to road transport branches only.

    Returns:
        Concatenated tidy T11-compatible benchmark DataFrame.
    """
    exports_dir = Path(exports_dir)
    files = list(exports_dir.glob("transport_leap_export_combined_*.xlsx"))

    if not files:
        raise FileNotFoundError(f"No combined export files found in {exports_dir}")

    log.info("Found %d combined export files", len(files))
    frames = []

    for f in sorted(files):
        try:
            tidy = load_single_export(f)
            frames.append(tidy)
        except Exception as exc:
            log.warning("Failed to load %s: %s", f.name, exc)

    if not frames:
        raise RuntimeError("No combined export files could be loaded")

    result = pd.concat(frames, ignore_index=True)

    if road_only and "leap_branch_path" in result.columns:
        road_mask = result["leap_branch_path"].str.startswith(
            ("Demand\\Passenger road", "Demand\\Freight road"), na=False
        )
        result = result[road_mask].copy()
        log.info("Filtered to %d road transport rows", len(result))

    return result


def parse_branch_path(branch_path: str) -> dict[str, str | None]:
    """
    Parse a LEAP branch path into its constituent dimension components.

    Example:
        'Demand\\Passenger road\\LPVs\\ICE small\\Motor gasoline'
        → {demand: 'Demand', transport_type: 'Passenger road',
           vehicle_type: 'LPVs', technology: 'ICE small', fuel: 'Motor gasoline'}

    Args:
        branch_path: Backslash-separated LEAP branch path.

    Returns:
        Dict with keys: demand, transport_type, vehicle_type, technology, fuel.
    """
    parts = branch_path.split("\\")
    result: dict[str, str | None] = {
        "demand": None,
        "transport_type": None,
        "vehicle_type": None,
        "technology": None,
        "fuel": None,
    }
    keys = list(result.keys())
    for i, part in enumerate(parts[:len(keys)]):
        result[keys[i]] = part
    return result
