"""Run the road model workflow for all APEC economies and report dashboard timing.

This script discovers economies from input_data/module1_defaults, runs the road
workflow, and writes dashboard HTML when BUILD_DASHBOARDS is True. It is set up
so the constants at the bottom can be edited and run from a notebook cell.
"""

#%%

from __future__ import annotations

import re
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


# --- Stable Paths ---

REPO_ROOT = Path(__file__).resolve().parents[1]
CODEBASE_DIR = REPO_ROOT / "codebase"
MODULE1_DEFAULTS_DIR = REPO_ROOT / "input_data" / "module1_defaults"


# --- Functions ---

def discover_economies(module1_dir: Path) -> list[str]:
    """Return canonical economy codes from the most recent module1_defaults version."""
    version_dirs = sorted(
        [p for p in module1_dir.iterdir() if p.is_dir()],
        key=lambda p: p.stat().st_mtime,
    )
    if not version_dirs:
        raise FileNotFoundError(f"No version folders in {module1_dir}")

    version_dir = version_dirs[-1]
    print(f"Module 1 version: {version_dir.name}")

    codes: list[str] = []
    for folder in sorted(version_dir.iterdir()):
        if not folder.is_dir():
            continue
        name = folder.name
        match = re.match(r"^(\d{2})([A-Z].*)$", name)
        code = f"{match.group(1)}_{match.group(2)}" if match else name
        codes.append(code)
    return codes


def run_one_economy(
    economy: str,
    scenario: str,
    build_dashboards: bool,
    repo_root: Path,
) -> dict:
    """Run one economy and return model/dashboard timing."""
    sys.path.insert(0, str(repo_root / "codebase"))
    from road_workflow import run_for_economy  # noqa: PLC0415

    start = time.perf_counter()
    try:
        outputs = run_for_economy(
            economy=economy,
            scenario=scenario,
            enable_visualisations=build_dashboards,
        )
        timings = outputs.get("timings", {})
        workflow_meta = outputs.get("workflow_meta", {})
        diagnostics_root = workflow_meta.get("diagnostics_root")
        dashboard_index = Path(diagnostics_root) / "dashboard" / "index.html" if diagnostics_root else None
        dashboard_exists = bool(dashboard_index and dashboard_index.exists())

        return {
            "economy": economy,
            "ok": True,
            "seconds": time.perf_counter() - start,
            "dashboard_seconds": float(timings.get("dashboard_html_seconds", 0.0)),
            "summary_visuals_seconds": float(timings.get("workflow_summary_visuals_seconds", 0.0)),
            "dashboard_exists": dashboard_exists,
            "dashboard_index": str(dashboard_index) if dashboard_index else "",
        }
    except Exception:
        return {
            "economy": economy,
            "ok": False,
            "seconds": time.perf_counter() - start,
            "error": traceback.format_exc(),
        }


def run_one_economy_from_work_item(work_item: tuple[str, str, bool, str]) -> dict:
    """ProcessPool wrapper for one economy run."""
    economy, scenario, build_dashboards, repo_root = work_item
    return run_one_economy(
        economy=economy,
        scenario=scenario,
        build_dashboards=build_dashboards,
        repo_root=Path(repo_root),
    )


def print_run_result(result: dict, build_dashboards: bool) -> None:
    """Print one economy result line."""
    status = "OK " if result["ok"] else "FAIL"
    if result["ok"]:
        dashboard_note = "dashboard=off"
        if build_dashboards:
            dashboard_note = f"dashboard={result['dashboard_seconds']:5.1f}s"
            if not result["dashboard_exists"]:
                dashboard_note += " (missing index)"
        print(f"  [{status}]  {result['economy']:<12}  {result['seconds']:6.1f}s  {dashboard_note}")
        return

    last_error_line = result["error"].splitlines()[-1] if result.get("error") else "unknown error"
    print(f"  [{status}]  {result['economy']:<12}  {result['seconds']:6.1f}s  - {last_error_line}")


def print_summary(results: list[dict], elapsed_seconds: float) -> None:
    """Print aggregate run and dashboard timing."""
    ok = [result for result in results if result["ok"]]
    fail = [result for result in results if not result["ok"]]

    print(f"\n{'-' * 52}")
    print(f"  Completed: {len(ok)}/{len(results)}  |  wall time: {elapsed_seconds:.1f}s")

    if fail:
        print("\n  Failed economies:")
        for result in fail:
            print(f"    {result['economy']}")
            for line in result["error"].splitlines()[-5:]:
                print(f"      {line}")

    if not ok:
        return

    average_seconds = sum(result["seconds"] for result in ok) / len(ok)
    slowest = max(ok, key=lambda result: result["seconds"])
    print(f"\n  Avg time per economy: {average_seconds:.1f}s")
    print(f"  Slowest economy: {slowest['economy']} ({slowest['seconds']:.1f}s)")

    dashboard_runs = [result for result in ok if result.get("dashboard_seconds", 0.0)]
    if dashboard_runs:
        average_dashboard_seconds = sum(result["dashboard_seconds"] for result in dashboard_runs) / len(dashboard_runs)
        slowest_dashboard = max(dashboard_runs, key=lambda result: result["dashboard_seconds"])
        missing_dashboards = [result["economy"] for result in ok if not result.get("dashboard_exists")]
        print(f"  Avg dashboard HTML time: {average_dashboard_seconds:.1f}s")
        print(
            "  Slowest dashboard HTML: "
            f"{slowest_dashboard['economy']} ({slowest_dashboard['dashboard_seconds']:.1f}s)"
        )
        if missing_dashboards:
            print(f"  Missing dashboard indexes: {', '.join(missing_dashboards)}")


def run_all_economies(
    scenario: str,
    build_dashboards: bool,
    worker_count: int,
    economies_to_run: list[str] | None,
) -> list[dict]:
    """Run selected economies and print timing results."""
    all_economies = discover_economies(MODULE1_DEFAULTS_DIR)
    economies = economies_to_run if economies_to_run else all_economies

    print(
        f"Running {len(economies)} economies | scenario={scenario} | "
        f"workers={worker_count} | build_dashboards={build_dashboards}\n"
    )

    work_items = [(economy, scenario, build_dashboards, str(REPO_ROOT)) for economy in economies]
    results: list[dict] = []

    start = time.perf_counter()
    with ProcessPoolExecutor(max_workers=worker_count) as pool:
        futures = {pool.submit(run_one_economy_from_work_item, item): item[0] for item in work_items}
        for future in as_completed(futures):
            result = future.result()
            print_run_result(result, build_dashboards=build_dashboards)
            results.append(result)

    print_summary(results, elapsed_seconds=time.perf_counter() - start)
    return results


#%%
# --- Frequently Changed Run Settings ---

SCENARIO = "Reference"
BUILD_DASHBOARDS = True
WORKER_COUNT = 4
ECONOMIES_TO_RUN: list[str] | None = None

# For a quick timing test, uncomment one of these:
# ECONOMIES_TO_RUN = ["05_PRC"]
# ECONOMIES_TO_RUN = ["01_AUS", "05_PRC", "20_USA"]


#%%
# --- Run Block ---

if __name__ == "__main__":
    run_results = run_all_economies(
        scenario=SCENARIO,
        build_dashboards=BUILD_DASHBOARDS,
        worker_count=WORKER_COUNT,
        economies_to_run=ECONOMIES_TO_RUN,
    )

#%%
