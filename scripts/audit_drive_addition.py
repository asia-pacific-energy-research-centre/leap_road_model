"""Audit a proposed vehicle/drive addition against a LEAP export workbook.

This script is deliberately read-only. LEAP's generic COM ``AddCategory`` and
``AddTechnology`` methods create Activity Analysis branches under a Transport
Stock Turnover parent, so they are not a valid way to create road technologies.
Create the branches in LEAP's transport-stock-turnover UI, export the area, and
use this audit to verify the resulting branch/variable/scenario IDs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
CODEBASE_DIR = REPO_ROOT / "codebase"
if str(CODEBASE_DIR) not in sys.path:
    sys.path.insert(0, str(CODEBASE_DIR))

from adapters.leap_import_writer import load_reference_id_table  # noqa: E402


DEFAULT_PARENT_PATH = "Demand\\Freight road\\Trucks"
DEFAULT_DRIVE = "PHEV"
DEFAULT_SIZES = ("heavy", "medium")
DEFAULT_FUELS = ("Electricity", "Gas and diesel oil", "Biodiesel")


def expected_rows(
    *,
    parent_path: str,
    drive: str,
    sizes: tuple[str, ...],
    fuels: tuple[str, ...],
    scenario: str,
) -> list[tuple[str, str, str]]:
    """Return the minimum strict-import rows for one projected scenario."""
    rows: list[tuple[str, str, str]] = []
    for size in sizes:
        drive_path = f"{parent_path}\\{drive} {size}"
        rows.append((drive_path, "Sales Share", scenario))
        for fuel in fuels:
            fuel_path = f"{drive_path}\\{fuel}"
            rows.extend(
                (fuel_path, variable, scenario)
                for variable in ("Device Share", "Fuel Economy", "Mileage")
            )
    return rows


def audit_reference(
    reference_workbook: str | Path,
    *,
    scenario: str,
    parent_path: str = DEFAULT_PARENT_PATH,
    drive: str = DEFAULT_DRIVE,
    sizes: tuple[str, ...] = DEFAULT_SIZES,
    fuels: tuple[str, ...] = DEFAULT_FUELS,
) -> dict[str, object]:
    reference_path = Path(reference_workbook).resolve()
    reference = load_reference_id_table(reference_path, road_only=False)
    indexed = reference.set_index(["Branch Path", "Variable", "Scenario"])
    required = expected_rows(
        parent_path=parent_path,
        drive=drive,
        sizes=sizes,
        fuels=fuels,
        scenario=scenario,
    )

    matched: list[dict[str, object]] = []
    missing: list[dict[str, str]] = []
    for branch_path, variable, row_scenario in required:
        key = (branch_path, variable, row_scenario)
        if key not in indexed.index:
            missing.append(
                {"branch_path": branch_path, "variable": variable, "scenario": row_scenario}
            )
            continue
        row = indexed.loc[key]
        if getattr(row, "ndim", 1) > 1:
            row = row.iloc[0]
        matched.append(
            {
                "branch_path": branch_path,
                "variable": variable,
                "scenario": row_scenario,
                "branch_id": int(row["BranchID"]),
                "variable_id": int(row["VariableID"]),
                "scenario_id": int(row["ScenarioID"]),
                "region_id": int(row["RegionID"]),
            }
        )

    return {
        "reference_workbook": str(reference_path),
        "scenario": scenario,
        "scope": {
            "parent_path": parent_path,
            "drive": drive,
            "sizes": list(sizes),
            "fuels": list(fuels),
        },
        "required_row_count": len(required),
        "matched_row_count": len(matched),
        "missing_row_count": len(missing),
        "complete": not missing,
        "matched": matched,
        "missing": missing,
        "creation_note": (
            "Create transport-stock-turnover branches in LEAP before exporting. "
            "Do not use generic COM AddCategory/AddTechnology for this step."
        ),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference_workbook", type=Path)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--parent-path", default=DEFAULT_PARENT_PATH)
    parser.add_argument("--drive", default=DEFAULT_DRIVE)
    parser.add_argument("--sizes", nargs="+", default=list(DEFAULT_SIZES))
    parser.add_argument("--fuels", nargs="+", default=list(DEFAULT_FUELS))
    parser.add_argument(
        "--output-json",
        type=Path,
        help="Optional JSON output path; stdout is always written.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    result = audit_reference(
        args.reference_workbook,
        scenario=args.scenario,
        parent_path=args.parent_path,
        drive=args.drive,
        sizes=tuple(args.sizes),
        fuels=tuple(args.fuels),
    )
    rendered = json.dumps(result, indent=2)
    print(rendered)
    if args.output_json:
        args.output_json.write_text(rendered + "\n", encoding="utf-8")
    if not result["complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
