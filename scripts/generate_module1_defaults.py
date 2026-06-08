"""
Generate Module 1 default inputs for all APEC economies.

This script calls road_model_inputs_interface generation code directly; no
website is required. The outputs are written to:

    leap_road_model/input_data/module1_defaults/{version}/{economy}/
        road_module1_values_<ECONOMY>.csv

These files are consumed automatically by road_workflow.py when running the
road model. Refresh them whenever Module 1 assumptions are updated.

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
from datetime import date
import re
import sys
from pathlib import Path

import pandas as pd

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

LEGACY_PREFIX = "road_module1_default_filled_inputs_"
LONG_PREFIX = "road_module1_values_"
YEAR_PATTERN = re.compile(r"^\d{4}$")
VALID_BASE_DRIVES_BY_VEHICLE_TYPE = {
    "LPVs": {"ICE", "HEV", "EREV", "PHEV", "BEV", "FCEV"},
    "Motorcycles": {"ICE", "BEV", "FCEV"},
    "Buses": {"ICE", "BEV", "FCEV"},
    "Trucks": {"ICE", "BEV", "FCEV"},
    "LCVs": {"ICE", "PHEV", "BEV", "FCEV"},
}
MODULE1_LONG_KEY_COLUMNS = ["Economy", "Scenario", "Branch Path", "Variable", "Year"]


def _profile_prefixed_branch_path(branch_path: object, variable: object) -> str:
    """Encode global age-profile rows in Branch Path instead of extra columns."""
    path_text = str(branch_path or "")
    variable_text = str(variable or "")
    if variable_text not in {"Survival Rate", "Vintage Profile Share"}:
        return path_text

    match = re.search(r"(?:^|\\)Age\s+(\d+)(?:\\|$)", path_text)
    if not match:
        return path_text

    age = match.group(1)
    return f"Age Profile\\{age}"


def _parse_vehicle_and_drive(branch_path: object) -> tuple[str | None, str | None]:
    """Return model vehicle_type and unsized base drive from a LEAP branch path."""
    parts = str(branch_path or "").split("\\")
    if len(parts) < 4:
        return None, None
    vehicle_type = parts[2]
    if vehicle_type not in VALID_BASE_DRIVES_BY_VEHICLE_TYPE:
        return None, None
    technology = parts[3]
    tokens = technology.split()
    if not tokens:
        return vehicle_type, None
    return vehicle_type, tokens[0]


def _filter_out_of_scope_model_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Drop generated rows for drive branches outside the current road model scope."""
    branch_cols = [
        col for col in df.columns
        if str(col) in {"Branch Path", "Branch_Path", "expected_key_Branch_Path"}
    ]
    if not branch_cols or df.empty:
        return df

    def _is_out_of_scope(branch_path: object) -> bool:
        vehicle_type, drive_type = _parse_vehicle_and_drive(branch_path)
        if vehicle_type is None or drive_type is None:
            return False
        return drive_type not in VALID_BASE_DRIVES_BY_VEHICLE_TYPE[vehicle_type]

    out_of_scope = pd.Series(False, index=df.index)
    for col in branch_cols:
        out_of_scope = out_of_scope | df[col].apply(_is_out_of_scope)
    return df.loc[~out_of_scope].copy()


def _drop_exact_duplicate_long_rows(df: pd.DataFrame, source_path: Path) -> pd.DataFrame:
    """Drop exact duplicate Module 1 long rows, but reject conflicting duplicate keys."""
    if not set(MODULE1_LONG_KEY_COLUMNS).issubset(df.columns) or df.empty:
        return df

    duplicate_mask = df.duplicated(MODULE1_LONG_KEY_COLUMNS, keep=False)
    if not duplicate_mask.any():
        return df

    duplicate_rows = df.loc[duplicate_mask].copy()
    value_columns = [col for col in df.columns if col not in MODULE1_LONG_KEY_COLUMNS]
    conflicting_keys: list[dict[str, object]] = []
    for _, group in duplicate_rows.groupby(MODULE1_LONG_KEY_COLUMNS, dropna=False):
        comparable = group[value_columns].fillna("<NA>").astype(str).drop_duplicates()
        if len(comparable) > 1:
            conflicting_keys.append(group.iloc[0][MODULE1_LONG_KEY_COLUMNS].to_dict())

    if conflicting_keys:
        sample = conflicting_keys[:5]
        raise ValueError(
            f"Conflicting duplicate Module 1 keys in {source_path}: {sample}"
        )

    dropped = int(len(df) - len(df.drop_duplicates(MODULE1_LONG_KEY_COLUMNS, keep="first")))
    if dropped:
        print(f"Removed {dropped} exact duplicate Module 1 row(s) from {source_path}")
    return df.drop_duplicates(MODULE1_LONG_KEY_COLUMNS, keep="first").copy()


def _legacy_wide_to_canonical_long(wide_df: pd.DataFrame, economy_code: str, version: str) -> pd.DataFrame:
    """Convert the legacy Module 1 wide CSV into the canonical long CSV contract."""
    year_cols = [col for col in wide_df.columns if YEAR_PATTERN.match(str(col))]
    id_cols = [col for col in wide_df.columns if col not in year_cols]
    long_df = wide_df.melt(
        id_vars=id_cols,
        value_vars=year_cols,
        var_name="Year",
        value_name="Value",
    )
    long_df["Economy"] = economy_code
    long_df["Year"] = pd.to_numeric(long_df["Year"], errors="coerce").astype("Int64")
    long_df["Source"] = long_df.get("source_name", "")
    long_df["Comment"] = long_df.get("review_reason", long_df.get("notes", ""))
    long_df["Input Status"] = long_df.get("input_source", "")
    long_df["Source Method"] = long_df.get("source_type", "")
    long_df["Original Value"] = ""
    long_df["Validation Message"] = ""
    long_df["Last Updated"] = long_df.get("source_date", "")
    long_df["Version"] = long_df.get("default_version", version)
    long_df["Branch Path"] = [
        _profile_prefixed_branch_path(branch_path, variable)
        for branch_path, variable in zip(long_df["Branch Path"], long_df["Variable"])
    ]

    keep = [
        "Economy", "Scenario", "Branch Path", "Variable", "Year", "Value", "Units",
        "Source", "Comment", "Input Status", "Source Method",
        "Original Value", "Validation Message", "Last Updated", "Version",
    ]
    return long_df[[col for col in keep if col in long_df.columns]].copy()


def _prepare_long_csvs(output_root: Path, version: str) -> list[Path]:
    """Return current long CSVs, converting legacy wide files when needed."""
    version_root = output_root / version
    today = date.today().strftime("%Y%m%d")
    long_paths: list[Path] = []

    for economy_dir in sorted(path for path in version_root.iterdir() if path.is_dir()):
        economy_code = economy_dir.name
        current_long_candidates = sorted(economy_dir.glob(f"{LONG_PREFIX}*.csv"))
        if current_long_candidates:
            for long_path in current_long_candidates:
                long_df = pd.read_csv(long_path, low_memory=False)
                filtered_long_df = _filter_out_of_scope_model_rows(long_df)
                cleaned_long_df = _drop_exact_duplicate_long_rows(filtered_long_df, source_path=long_path)
                if len(cleaned_long_df) != len(long_df):
                    cleaned_long_df.to_csv(long_path, index=False)
                long_paths.append(long_path)
            continue

        legacy_candidates = sorted(economy_dir.glob(f"{LEGACY_PREFIX}*.csv"))
        if not legacy_candidates:
            continue
        legacy_path = legacy_candidates[0]
        wide_df = pd.read_csv(legacy_path, low_memory=False)
        filtered_wide_df = _filter_out_of_scope_model_rows(wide_df)
        if len(filtered_wide_df) != len(wide_df):
            filtered_wide_df.to_csv(legacy_path, index=False)
        wide_df = filtered_wide_df
        long_df = _legacy_wide_to_canonical_long(wide_df, economy_code=economy_code, version=version)
        long_df = _drop_exact_duplicate_long_rows(long_df, source_path=legacy_path)
        long_path = economy_dir / f"{LONG_PREFIX}{economy_code}_{version}_{today}.csv"

        for old_long_path in economy_dir.glob(f"{LONG_PREFIX}*.csv"):
            if old_long_path != long_path:
                old_long_path.unlink(missing_ok=True)

        long_df.to_csv(long_path, index=False)
        long_paths.append(long_path)

    return long_paths


def _write_local_manifest(output_root: Path, version: str, long_paths: list[Path]) -> Path:
    """Write a package manifest using local package paths."""
    version_root = output_root / version
    manifest_path = version_root / "road_module1_manifest.csv"
    rows: list[dict[str, str]] = []
    for path in sorted(long_paths):
        economy_code = path.parent.name
        rows.append({
            "default_version": version,
            "economy": economy_code,
            "file_type": "default_filled_inputs",
            "path": str(path),
        })
        legacy_candidates = sorted(path.parent.glob(f"{LEGACY_PREFIX}*.csv"))
        for legacy_path in legacy_candidates[:1]:
            rows.append({
                "default_version": version,
                "economy": economy_code,
                "file_type": "legacy_default_filled_inputs",
                "path": str(legacy_path),
            })

    columns = ["default_version", "economy", "file_type", "path"]
    pd.DataFrame(rows, columns=columns).to_csv(manifest_path, index=False)
    return manifest_path


def _filter_package_support_csvs(output_root: Path, version: str) -> list[Path]:
    """Clean package-level support CSVs that list branch paths."""
    version_root = output_root / version
    written: list[Path] = []
    for csv_path in sorted(version_root.glob("*.csv")):
        try:
            df = pd.read_csv(csv_path, low_memory=False)
        except Exception:
            continue
        filtered_df = _filter_out_of_scope_model_rows(df)
        if len(filtered_df) == len(df):
            continue
        filtered_df.to_csv(csv_path, index=False)
        written.append(csv_path)
    return written


def generate_defaults(version: str = DEFAULT_VERSION, no_enforce: bool = False) -> None:
    """Generate Module 1 defaults for all APEC economies and write to input_data/module1_defaults/."""
    output_root = MODULE1_OUTPUT_DIR
    output_root.mkdir(parents=True, exist_ok=True)

    print(f"road_model_inputs_interface backend : {_INTERFACE_BACKEND}")
    print(f"Output directory                    : {output_root}")
    if version != DEFAULT_VERSION:
        print(
            "Requested version                   : "
            f"{version} (upstream generator currently writes {DEFAULT_VERSION})"
        )
    print(f"Version                             : {DEFAULT_VERSION}")
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
    long_paths = _prepare_long_csvs(output_root=output_root, version=DEFAULT_VERSION)
    support_paths = _filter_package_support_csvs(output_root=output_root, version=DEFAULT_VERSION)
    manifest_path = _write_local_manifest(output_root=output_root, version=DEFAULT_VERSION, long_paths=long_paths)

    print(f"\nDone. Generated defaults for {len(paths)} economies.")
    print(f"Long CSV files available            : {len(long_paths)}")
    print(f"Support CSV files cleaned           : {len(support_paths)}")
    print(f"Manifest                            : {manifest_path}")
    print(f"Location: {output_root / DEFAULT_VERSION}")
    print(
        "\nNext step: run the road model via run_with_config(); it will automatically\n"
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
