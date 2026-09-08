"""Build and package the transport assumptions dashboards reproducibly.

This is the supported entry point for the preserved 12 August 2026 workflow.
It deliberately keeps the domestic non-road, international, and original road
generators separate from the current road-model comparison overlay: the latter
is a review aid, not a replacement for an official LEAP result.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from legacy import all_economies_non_road_workflow as domestic
from legacy import international_transport_dashboard_workflow as international
from legacy import package_dashboard_html_workflow as html_wrapper
from legacy import package_transport_dashboards_workflow as legacy_package
from legacy import prc_road_dashboard_workflow as road


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
LEGACY_DIR = SCRIPT_DIR / "legacy"
DEFAULT_OUTPUT = REPO_ROOT / "results" / "transport_assumptions_dashboard"
EXPECTED_PACKAGE_FILES = (
    "open.html",
    "README.txt",
    "nr/index.html",
    "intl/index.html",
    "road/index.html",
    "data/nr/exceptions_notes.md",
)


def require_path(path: Path | None, description: str, *, directory: bool = False) -> Path:
    """Return an existing input path, with an actionable error if it is absent."""
    if path is None:
        raise ValueError(f"{description} is required for this build.")
    if not path.exists():
        raise FileNotFoundError(f"{description} does not exist: {path}")
    if directory and not path.is_dir():
        raise NotADirectoryError(f"{description} must be a directory: {path}")
    if not directory and not path.is_file():
        raise FileNotFoundError(f"{description} must be a file: {path}")
    return path.resolve()


def refuse_existing(path: Path, *, replace: bool) -> None:
    """Require an explicit opt-in before replacing a generated artifact."""
    if path.exists() and not replace:
        raise FileExistsError(f"Refusing to replace {path}. Use --replace for this known output path.")


def clean_known_directory(path: Path, parent: Path, *, replace: bool) -> None:
    """Remove only a direct child of the requested output directory."""
    if not path.exists():
        return
    if not replace:
        raise FileExistsError(f"Refusing to replace {path}. Use --replace for this known output path.")
    if path.resolve().parent != parent.resolve():
        raise ValueError(f"Refusing to remove output outside its selected root: {path}")
    shutil.rmtree(path)


def generated_root(output: Path) -> Path:
    return output / "generated"


def code_paths(code_root: Path) -> tuple[Path, Path]:
    """Resolve the two 9th-edition configuration files needed by the legacy code."""
    concordance = code_root / "config" / "concordances_and_config_data" / "economy_code_to_name.csv"
    parameters = code_root / "config" / "parameters.yml"
    require_path(concordance, "9th-edition economy concordance")
    require_path(parameters, "9th-edition parameter YAML")
    return concordance, parameters


def domestic_raw_dir(data_dir: Path) -> Path:
    """Accept either the snapshot's data root or its raw_all input folder."""
    raw_all = data_dir / "raw_all"
    return raw_all if raw_all.is_dir() else data_dir


def build_domestic_non_road(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    data_dir = require_path(args.data_dir, "domestic non-road input directory", directory=True)
    code_root = require_path(args.code_root, "9th-edition code root", directory=True)
    concordance, _ = code_paths(code_root)
    target = root / "non_road_assumptions_dashboard"
    fragment = root / "fragments" / "domestic_non_road.html"
    clean_known_directory(target, root, replace=args.replace)
    target.mkdir(parents=True, exist_ok=True)
    summary = domestic.run_all_economies_workflow(
        raw_dir=domestic_raw_dir(data_dir),
        concordance_path=concordance,
        template_path=LEGACY_DIR / "dashboard_template.html",
        dashboard_fragment_path=fragment,
        output_dir=target,
        end_year=args.end_year,
    )
    html_wrapper.write_wrapped_dashboard(
        fragment,
        target / "non_road_assumptions_dashboard_all_economies.html",
        "Domestic non-road assumptions dashboard",
    )
    return summary


def build_international(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    data_dir = require_path(args.data_dir, "domestic non-road input directory", directory=True)
    code_root = require_path(args.code_root, "9th-edition code root", directory=True)
    source = require_path(args.international_source, "international bunker output")
    concordance, parameters = code_paths(code_root)
    target = root / "international_transport_assumptions_dashboard"
    fragment = root / "fragments" / "international.html"
    clean_known_directory(target, root, replace=args.replace)
    target.mkdir(parents=True, exist_ok=True)
    summary = international.run_international_dashboard_workflow(
        source_path=source,
        concordance_path=concordance,
        parameters_path=parameters,
        non_road_code_path=code_root / "model_code" / "calculation_functions" / "run_non_road_model.py",
        international_code_path=code_root / "model_code" / "calculation_functions" / "international_bunkers.py",
        domestic_raw_dir=domestic_raw_dir(data_dir),
        template_path=LEGACY_DIR / "international_transport_dashboard_template.html",
        fragment_path=fragment,
        output_dir=target,
        end_year=args.end_year,
    )
    html_wrapper.write_wrapped_dashboard(
        fragment,
        target / "international_transport_assumptions_dashboard_all_economies.html",
        "International transport assumptions dashboard",
    )
    return summary


def build_road(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    chart_dir = require_path(args.road_chart_dir, "9th-edition road chart directory", directory=True)
    stock_dir = require_path(args.road_stock_dir, "9th-edition road fleet diagnostics directory", directory=True)
    code_root = require_path(args.code_root, "9th-edition code root", directory=True)
    concordance, parameters = code_paths(code_root)
    target = root / "road_transport_assumptions_dashboard"
    clean_known_directory(target, root, replace=args.replace)
    target.mkdir(parents=True, exist_ok=True)
    summary = road.run_all_economies_road_dashboard_workflow(
        chart_dir=chart_dir,
        stock_dir=stock_dir,
        template_path=LEGACY_DIR / "prc_road_dashboard_template.html",
        concordance_path=concordance,
        parameters_path=parameters,
        output_dir=target,
        default_economy=args.default_economy,
    )
    return {"economies": len(summary), "summary_csv": str(target / "data" / "road_dashboard_build_summary_all_economies.csv")}


def load_road_comparison_builder() -> Any:
    """Load the maintained comparison overlay without making it a package dependency."""
    module_path = REPO_ROOT / "scripts" / "build_9th_dashboard_with_new_model.py"
    spec = importlib.util.spec_from_file_location("road_comparison_builder", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load road comparison builder: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_integrated_road_launcher(road_dir: Path) -> None:
    """Write a road landing page that keeps package-wide navigation visible."""
    pages = sorted(road_dir.glob("[0-9][0-9]_*.html"))
    links = "\n".join(f'<li><a href="{page.name}">{page.stem}</a></li>' for page in pages)
    launcher = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Road dashboard: 9th edition versus current road model</title>
<style>body{{font-family:system-ui,sans-serif;max-width:760px;margin:40px auto;padding:0 20px;color:#163238}} a{{color:#087f70}} li{{margin:8px 0}} nav{{display:flex;gap:18px;flex-wrap:wrap}}</style></head>
<body><nav><a href="../nr/index.html">Domestic non-road</a><a href="../intl/index.html">International transport</a></nav>
<h1>Road dashboard: 9th edition versus current road model</h1>
<p>Each economy page keeps the 9th-edition road dashboard and adds dashed lines for the current road-model Python mirror. Use the source filter to isolate either series; these lines are not recalculated LEAP results.</p>
<p>Select an economy:</p><ul>{links}</ul></body></html>"""
    (road_dir / "index.html").write_text(launcher, encoding="utf-8")


def integrate_road_comparison(args: argparse.Namespace, package_dir: Path, root: Path) -> dict[str, Any]:
    """Replace packaged road pages with the maintained 9th-versus-current overlay."""
    model_root = require_path(args.model_root, "current road-model comparison results", directory=True)
    merged_energy = require_path(args.merged_energy, "9th-edition merged-energy CSV")
    comparison_dir = root / "road_comparison"
    clean_known_directory(comparison_dir, root, replace=args.replace)
    comparison_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_road_comparison_builder().build(package_dir, model_root, merged_energy, comparison_dir)
    road_dir = package_dir / "road"
    for page in comparison_dir.glob("[0-9][0-9]_*.html"):
        shutil.copy2(page, road_dir / page.name)
    write_integrated_road_launcher(road_dir)
    for name in ("comparison_manifest.json", "total_comparison_scan.csv", "stock_unit_corrections.csv"):
        source = comparison_dir / name
        if source.is_file():
            shutil.copy2(source, package_dir / "data" / "road" / name)
    return {
        "comparison_dir": str(comparison_dir),
        "integrated_road_pages": len(list(comparison_dir.glob("[0-9][0-9]_*.html"))),
        "comparison_manifest": manifest,
    }


def package_dashboards(args: argparse.Namespace, output: Path, *, replace: bool, make_zip: bool) -> dict[str, Any]:
    """Create the short-path package without touching any unrelated output."""
    root = generated_root(output)
    sources = {
        "nr": root / "non_road_assumptions_dashboard" / "non_road_assumptions_dashboard_all_economies.html",
        "intl": root / "international_transport_assumptions_dashboard" / "international_transport_assumptions_dashboard_all_economies.html",
        "road": root / "road_transport_assumptions_dashboard" / "road_transport_assumptions_dashboard_all_economies.html",
    }
    for name, source in sources.items():
        require_path(source, f"generated {name} dashboard")

    package_dir = output / "transport_dashboards"
    clean_known_directory(package_dir, output, replace=replace)
    package_dir.mkdir(parents=True, exist_ok=True)
    legacy_package.copy_html(sources["nr"], package_dir / "nr" / "index.html")
    legacy_package.copy_html(sources["intl"], package_dir / "intl" / "index.html")
    legacy_package.copy_html(sources["road"], package_dir / "road" / "index.html")
    for source in (root / "road_transport_assumptions_dashboard").glob("road_transport_assumptions_dashboard_[0-9][0-9]_*.html"):
        economy = source.stem.removeprefix("road_transport_assumptions_dashboard_")
        legacy_package.copy_html(source, package_dir / "road" / f"{economy}.html")
    legacy_package.copy_data_files(root / "non_road_assumptions_dashboard", package_dir / "data" / "nr", include_all=False)
    shutil.copy2(LEGACY_DIR / "economy_exceptions_section_plan.md", package_dir / "data" / "nr" / "exceptions_notes.md")
    legacy_package.copy_data_files(root / "international_transport_assumptions_dashboard", package_dir / "data" / "intl")
    legacy_package.copy_data_files(root / "road_transport_assumptions_dashboard" / "data", package_dir / "data" / "road")
    legacy_package.write_entry_page(package_dir)

    comparison = integrate_road_comparison(args, package_dir, root) if args.integrate_road_comparison else None
    validation = validate_package(package_dir, require_road_comparison=args.integrate_road_comparison)
    zip_path = output / "transport_dashboards.zip"
    if make_zip:
        refuse_existing(zip_path, replace=replace)
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in package_dir.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(output))
    return {
        "package_dir": str(package_dir),
        "zip_path": str(zip_path) if make_zip else None,
        "validation": validation,
        "road_comparison": comparison,
    }


def validate_package(package_dir: Path, *, require_road_comparison: bool = False) -> dict[str, Any]:
    package_dir = require_path(package_dir, "dashboard package directory", directory=True)
    missing = [str(path) for path in EXPECTED_PACKAGE_FILES if not (package_dir / path).is_file()]
    road_pages = sorted((package_dir / "road").glob("[0-9][0-9]_*.html")) if (package_dir / "road").exists() else []
    data_files = [path for path in (package_dir / "data").rglob("*") if path.is_file()] if (package_dir / "data").exists() else []
    comparison_pages = [page for page in road_pages if "LEAP/new model" in page.read_text(encoding="utf-8") and "new_model" in page.read_text(encoding="utf-8")]
    comparison_files = [
        package_dir / "data" / "road" / "comparison_manifest.json",
        package_dir / "data" / "road" / "total_comparison_scan.csv",
    ]
    comparison_landing_page = (package_dir / "road" / "index.html").read_text(encoding="utf-8") if (package_dir / "road" / "index.html").is_file() else ""
    comparison_valid = (
        len(comparison_pages) == 21
        and all(path.is_file() for path in comparison_files)
        and "9th edition versus current road model" in comparison_landing_page
    )
    validation = {
        "package_dir": str(package_dir),
        "missing_required_files": missing,
        "road_economy_pages": len(road_pages),
        "supporting_data_files": len(data_files),
        "comparison_marked_road_pages": len(comparison_pages),
        "road_comparison_valid": comparison_valid,
        "valid": not missing and len(road_pages) == 21 and bool(data_files) and (comparison_valid or not require_road_comparison),
    }
    if not validation["valid"]:
        raise ValueError(f"Invalid dashboard package: {json.dumps(validation, indent=2)}")
    return validation


def build_road_comparison(args: argparse.Namespace, output: Path) -> dict[str, Any]:
    """Use the current comparison overlay, kept separate from the original bundle."""
    source = require_path(args.comparison_source, "original dashboard package", directory=True)
    model_root = require_path(args.model_root, "current road-model comparison results", directory=True)
    merged_energy = require_path(args.merged_energy, "9th-edition merged-energy CSV")
    destination = args.comparison_output or output / "road_comparison"
    refuse_existing(destination, replace=args.replace)
    return load_road_comparison_builder().build(source, model_root, merged_energy, destination)


def source_manifest(args: argparse.Namespace) -> dict[str, Any]:
    """Record supplied inputs without copying the large raw snapshot into git."""
    tracked_paths = {
        "domestic_non_road_data": args.data_dir,
        "ninth_edition_code": args.code_root,
        "international_bunker_output": args.international_source,
        "road_chart_directory": args.road_chart_dir,
        "road_fleet_diagnostics_directory": args.road_stock_dir,
        "comparison_source_dashboard": args.comparison_source,
        "current_road_model_results": args.model_root,
        "ninth_edition_merged_energy": args.merged_energy,
    }
    result: dict[str, Any] = {}
    for label, path in tracked_paths.items():
        if path is not None and path.exists():
            result[label] = {"path": str(path.resolve()), "files": sum(1 for item in path.rglob("*") if item.is_file()) if path.is_dir() else 1}
    return result


def write_manifest(output: Path, args: argparse.Namespace, stages: dict[str, Any]) -> Path:
    manifest = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "entry_point": str(Path(__file__).resolve()),
        "legacy_source_provenance": "Transport dashboards · extraction fixed (019ff3d4-7e17-7510-a8c9-95b8be59cebf), 12 August 2026",
        "inputs": source_manifest(args),
        "stages": stages,
        "input_snapshot_documentation": str(SCRIPT_DIR / "input_manifest.md"),
    }
    path = output / "dashboard_build_manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", choices=("all", "domestic-non-road", "international", "road", "package", "road-comparison", "validate"), default="all")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Parent directory for generated work and the distributable package.")
    parser.add_argument("--data-dir", type=Path, help="Extracted data/ directory from the preserved Drive input snapshot.")
    parser.add_argument("--code-root", type=Path, help="9th-edition transport_model_9th_edition directory.")
    parser.add_argument("--international-source", type=Path, help="International bunker output CSV used by the original workflow.")
    parser.add_argument("--road-chart-dir", type=Path, help="9th-edition road chart HTML directory.")
    parser.add_argument("--road-stock-dir", type=Path, help="9th-edition road fleet diagnostic directory.")
    parser.add_argument("--default-economy", default="05_PRC")
    parser.add_argument("--end-year", type=int, default=2070)
    parser.add_argument("--no-zip", action="store_true", help="Build the directory package only.")
    parser.add_argument("--replace", action="store_true", help="Replace only known generated package/build paths below --output.")
    parser.add_argument("--integrate-road-comparison", action="store_true", help="Replace packaged road pages with the 9th-versus-current-road-model comparison overlay.")
    parser.add_argument("--comparison-source", type=Path, help="Original dashboard directory used for the 9th-v-current road overlay.")
    parser.add_argument("--model-root", type=Path, help="Current road-model results root used for the comparison overlay.")
    parser.add_argument("--merged-energy", type=Path, help="9th-edition merged-energy CSV used for the comparison overlay.")
    parser.add_argument("--comparison-output", type=Path, help="Optional separate output directory for the road comparison overlay.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    root = generated_root(output)
    stages: dict[str, Any] = {}
    if args.build == "validate":
        stages["validate"] = validate_package(output / "transport_dashboards", require_road_comparison=args.integrate_road_comparison)
    elif args.build == "package":
        stages["package"] = package_dashboards(args, output, replace=args.replace, make_zip=not args.no_zip)
    elif args.build == "road-comparison":
        stages["road_comparison"] = build_road_comparison(args, output)
    else:
        root.mkdir(parents=True, exist_ok=True)
        if args.build in {"all", "domestic-non-road"}:
            stages["domestic_non_road"] = build_domestic_non_road(args, root)
        if args.build in {"all", "international"}:
            stages["international"] = build_international(args, root)
        if args.build in {"all", "road"}:
            stages["road"] = build_road(args, root)
        if args.build == "all":
            stages["package"] = package_dashboards(args, output, replace=args.replace, make_zip=not args.no_zip)
    manifest = write_manifest(output, args, stages)
    print(json.dumps({"manifest": str(manifest), "stages": stages}, indent=2, default=str))


if __name__ == "__main__":
    main()
