#%%
"""Build a short-path transport dashboard folder and Windows-friendly zip."""

from __future__ import annotations

import shutil
from pathlib import Path


PACKAGE_FOLDER_NAME = "transport_dashboards"
PACKAGE_ZIP_NAME = "transport_dashboards"


def safely_remove_package(path: Path, output_root: Path) -> None:
    """Remove only a known package directory directly below the output root."""
    resolved_path = path.resolve()
    resolved_root = output_root.resolve()
    if resolved_path.parent != resolved_root:
        raise ValueError(f"Refusing to remove unexpected package path: {resolved_path}")
    if path.exists():
        shutil.rmtree(path)


def dashboard_path_replacements() -> dict[str, str]:
    """Map long generated dashboard paths to the compact packaged layout."""
    replacements = {
        "../non_road_assumptions_dashboard/non_road_assumptions_dashboard_all_economies.html": "../nr/index.html",
        "../international_transport_assumptions_dashboard/international_transport_assumptions_dashboard_all_economies.html": "../intl/index.html",
        "../road_transport_assumptions_dashboard/road_transport_assumptions_dashboard_all_economies.html": "../road/index.html",
    }
    for economy_number in range(1, 22):
        economy_prefix = f"{economy_number:02d}_"
        replacements[f"road_transport_assumptions_dashboard_{economy_prefix}"] = economy_prefix
    return replacements


def copy_html(source_path: Path, destination_path: Path) -> None:
    """Copy an HTML dashboard while translating links to compact package paths."""
    html_text = source_path.read_text(encoding="utf-8")
    for old_path, new_path in dashboard_path_replacements().items():
        html_text = html_text.replace(old_path, new_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path.write_text(html_text, encoding="utf-8")


def compact_data_name(source_name: str) -> str:
    """Return a concise, still interpretable name for packaged support data."""
    exact_names = {
        "dashboard_data_all_economies.json": "data.json",
        "economy_exception_candidates_all_economies.csv": "exceptions.csv",
        "non_road_drive_timeseries_all_economies.csv": "drives.csv",
        "non_road_energy_reconciliation_all_economies.csv": "reconciliation.csv",
        "non_road_fuel_energy_all_economies.csv": "fuels.csv",
        "non_road_fuel_mix_assumptions_all_economies.csv": "fuel_mix.csv",
        "non_road_user_inputs_all_economies.csv": "inputs.csv",
        "economy_exceptions_section_plan.md": "exceptions_notes.md",
        "international_transport_dashboard_data.json": "data.json",
        "international_transport_drive_timeseries_all_economies.csv": "drives.csv",
        "international_transport_fuel_energy_all_economies.csv": "fuels.csv",
        "international_transport_review_timeseries_all_economies.csv": "review.csv",
        "useful_model_assumptions_and_exceptions_registry.csv": "assumptions.csv",
        "road_dashboard_build_summary_all_economies.csv": "summary.csv",
    }
    if source_name in exact_names:
        return exact_names[source_name]
    road_prefixes = {
        "road_assumptions_explained_": "assumptions_",
        "road_dashboard_all_data_": "all_",
        "road_fleet_diagnostics_": "fleet_",
        "road_outcomes_": "outcomes_",
    }
    for long_prefix, short_prefix in road_prefixes.items():
        if source_name.startswith(long_prefix):
            return source_name.replace(long_prefix, short_prefix, 1)
    return source_name


def copy_data_files(source_dir: Path, destination_dir: Path, include_all: bool = True) -> None:
    """Copy supporting files with compact filenames."""
    destination_dir.mkdir(parents=True, exist_ok=True)
    for source_path in source_dir.rglob("*"):
        if not source_path.is_file() or source_path.suffix.lower() == ".html":
            continue
        if not include_all and "russia_prc" in source_path.name:
            continue
        destination_path = destination_dir / compact_data_name(source_path.name)
        shutil.copy2(source_path, destination_path)


def write_entry_page(package_dir: Path) -> None:
    """Write the single obvious file users open after extracting."""
    entry_html = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="0; url=nr/index.html">
  <title>Transport assumptions dashboards</title>
</head>
<body>
  <p>Opening the domestic non-road dashboard...</p>
  <p><a href="nr/index.html">Continue to the dashboard</a></p>
</body>
</html>
"""
    (package_dir / "open.html").write_text(entry_html, encoding="utf-8")
    (package_dir / "README.txt").write_text(
        "Open open.html to use the dashboards. Supporting CSV and JSON files are in the data folder.\n",
        encoding="utf-8",
    )


def build_combined_package(output_root: Path) -> Path:
    """Refresh all dashboards in a clean, compact package layout."""
    package_dir = output_root / PACKAGE_FOLDER_NAME
    old_package_dir = output_root / "Transport assumptions dashboards package"
    safely_remove_package(package_dir, output_root)
    safely_remove_package(old_package_dir, output_root)
    package_dir.mkdir(parents=True, exist_ok=True)

    non_road_source = output_root / "non_road_assumptions_dashboard"
    international_source = output_root / "international_transport_assumptions_dashboard"
    road_source = output_root / "road_transport_assumptions_dashboard"

    copy_html(non_road_source / "non_road_assumptions_dashboard_all_economies.html", package_dir / "nr" / "index.html")
    copy_html(international_source / "international_transport_assumptions_dashboard_all_economies.html", package_dir / "intl" / "index.html")
    copy_html(road_source / "road_transport_assumptions_dashboard_all_economies.html", package_dir / "road" / "index.html")
    for source_path in road_source.glob("road_transport_assumptions_dashboard_[0-9][0-9]_*.html"):
        economy = source_path.stem.removeprefix("road_transport_assumptions_dashboard_")
        copy_html(source_path, package_dir / "road" / f"{economy}.html")

    copy_data_files(non_road_source, package_dir / "data" / "nr", include_all=False)
    copy_data_files(international_source, package_dir / "data" / "intl")
    copy_data_files(road_source / "data", package_dir / "data" / "road")
    write_entry_page(package_dir)

    zip_base = output_root / PACKAGE_ZIP_NAME
    archive_path = shutil.make_archive(str(zip_base), "zip", root_dir=output_root, base_dir=package_dir.name)
    old_archive = output_root / "Transport assumptions dashboards package.zip"
    if old_archive.exists() and old_archive.resolve().parent == output_root.resolve():
        old_archive.unlink()
    return Path(archive_path)


# --- Frequently changed settings ---

WORKFLOW_DIR = Path(__file__).resolve().parent
OUTPUT_ROOT = WORKFLOW_DIR.parents[1] / "outputs"
# Packaging is orchestrated by build_transport_assumptions_dashboard.py.
RUN_COMBINED_PACKAGE_WORKFLOW = False


# --- Notebook-style run block ---

if RUN_COMBINED_PACKAGE_WORKFLOW:
    try:
        PACKAGE_PATH = build_combined_package(output_root=OUTPUT_ROOT)
        print(f"Updated package: {PACKAGE_PATH}")
    except Exception as error:
        print(f"Combined package workflow failed: {type(error).__name__}: {error}")
        raise

#%%
