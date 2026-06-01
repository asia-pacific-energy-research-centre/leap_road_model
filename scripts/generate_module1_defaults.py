"""
Generate Module 1 default inputs for all APEC economies.

This script calls road_model_inputs_interface generation code directly —
no website required. The outputs are written to:

    leap_road_model/input_data/module1_defaults/{version}/{economy}/
        road_module1_default_filled_inputs.csv

These files are consumed automatically by road_workflow.py when running
the road model. Refresh them whenever Module 1 assumptions are updated.

Usage
-----
Generate all economies (default version):
    python scripts/generate_module1_defaults.py

Generate all economies with a custom version label:
    python scripts/generate_module1_defaults.py --version my_version_name

Relax strict source-backed validation (useful for testing):
    python scripts/generate_module1_defaults.py --no-enforce

Dependencies
------------
Requires road_model_inputs_interface to be checked out as a sibling repo:
    ../road_model_inputs_interface/back-end/

Both repos must be in the same parent folder.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Locate the road_model_inputs_interface back-end and add to sys.path
# ---------------------------------------------------------------------------

_THIS_REPO = Path(__file__).resolve().parents[1]
_INTERFACE_BACKEND = _THIS_REPO.parent / "road_model_inputs_interface" / "back-end"

if not _INTERFACE_BACKEND.exists():
    raise FileNotFoundError(
        f"\nroad_model_inputs_interface/back-end not found at:\n  {_INTERFACE_BACKEND}\n\n"
        "Ensure the road_model_inputs_interface repo is checked out as a sibling of leap_road_model:\n"
        "  <parent>/\n"
        "    leap_road_model/\n"
        "    road_model_inputs_interface/\n"
    )

sys.path.insert(0, str(_INTERFACE_BACKEND))

# ---------------------------------------------------------------------------
# Import after path is set up
# ---------------------------------------------------------------------------

from core.road_module1_defaults import (  # noqa: E402  (import after sys.path manipulation)
    DEFAULT_VERSION,
    DEFAULT_SCENARIOS,
    DEFAULT_YEARS,
    write_all_economy_packages,
)

# ---------------------------------------------------------------------------
# Output location inside leap_road_model
# ---------------------------------------------------------------------------

MODULE1_OUTPUT_DIR = _THIS_REPO / "input_data" / "module1_defaults"


def generate_defaults(version: str = DEFAULT_VERSION, no_enforce: bool = False) -> None:
    """Generate Module 1 defaults for all APEC economies and write to input_data/module1_defaults/."""
    output_root = MODULE1_OUTPUT_DIR
    output_root.mkdir(parents=True, exist_ok=True)

    print(f"road_model_inputs_interface backend : {_INTERFACE_BACKEND}")
    print(f"Output directory                    : {output_root}")
    print(f"Version                             : {version}")
    print(f"Scenarios                           : {list(DEFAULT_SCENARIOS)}")
    print(f"Years                               : {list(DEFAULT_YEARS)}")
    print(f"Enforce source-backed values        : {not no_enforce}")
    print()

    paths = write_all_economy_packages(
        output_root=output_root,
        scenarios=DEFAULT_SCENARIOS,
        years=DEFAULT_YEARS,
        enforce_source_backed_values=not no_enforce,
    )

    print(f"\nDone. Generated defaults for {len(paths)} economies.")
    print(f"Location: {output_root / version}")
    print(
        "\nNext step: run the road model via run_with_config() — it will automatically\n"
        f"load defaults from {output_root}."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        default=DEFAULT_VERSION,
        help=f"Version tag for the output folder (default: {DEFAULT_VERSION})",
    )
    parser.add_argument(
        "--no-enforce",
        action="store_true",
        help="Disable strict source-backed value enforcement (useful for testing)",
    )
    args = parser.parse_args()
    generate_defaults(version=args.version, no_enforce=args.no_enforce)
