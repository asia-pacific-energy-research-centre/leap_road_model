"""Run Modules 2-7 without the website running.

This script is the offline entry point for the road model workflow. It uses
pre-generated Module 1 static outputs from the sibling ``road_model_inputs_interface``
repo instead of requiring the website to be running.

Expected folder layout (both repos as siblings):

    parent_folder/
        leap_road_model/           ← this repo
        road_model_inputs_interface/   ← sibling repo

The Module 1 package is read from:

    ../road_model_inputs_interface/back-end/outputs/road_module1_defaults/

If that path does not exist (e.g. the sibling repo is not present), the script
falls back to the legacy inputs under ``input_data/module1_defaults/``.

Usage
-----
Edit the constants near the bottom of this file and run:

    python scripts/offline_workflow.py

Or call ``run_offline`` directly from a Python session:

    from scripts.offline_workflow import run_offline
    run_offline("20_USA", scenario="Target", build_dashboards=False)
"""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CODEBASE_DIR = REPO_ROOT / "codebase"

# Default Module 1 source: sibling repo outputs
SIBLING_MODULE1_DIR = REPO_ROOT.parent / "road_model_inputs_interface" / "back-end" / "outputs" / "road_module1_defaults"
# Fallback: legacy inputs committed to this repo
LEGACY_MODULE1_DIR = REPO_ROOT / "input_data" / "module1_defaults"


def _resolve_module1_dir() -> Path:
    if SIBLING_MODULE1_DIR.exists():
        return SIBLING_MODULE1_DIR
    if LEGACY_MODULE1_DIR.exists():
        print(
            f"[offline_workflow] Sibling repo outputs not found at {SIBLING_MODULE1_DIR}\n"
            f"  Falling back to legacy inputs at {LEGACY_MODULE1_DIR}"
        )
        return LEGACY_MODULE1_DIR
    raise FileNotFoundError(
        f"No Module 1 defaults found.\n"
        f"  Checked: {SIBLING_MODULE1_DIR}\n"
        f"  Checked: {LEGACY_MODULE1_DIR}\n"
        f"  Clone road_model_inputs_interface as a sibling of this repo, or "
        f"run scripts/generate_module1_defaults.py to populate input_data/module1_defaults/."
    )


def _dashboard_index_from_outputs(outputs: dict) -> Path | None:
    """Return the generated dashboard index path from workflow outputs."""
    workflow_meta = outputs.get("workflow_meta", {})
    diagnostics_root = workflow_meta.get("diagnostics_root")
    if not diagnostics_root:
        return None
    return Path(diagnostics_root) / "dashboard" / "index.html"


def _confirm_dashboard_written(outputs: dict, build_dashboards: bool) -> None:
    """Print the dashboard path and fail if a requested dashboard is missing."""
    if not build_dashboards:
        print("[offline_workflow] Dashboard generation disabled.")
        return

    dashboard_index = _dashboard_index_from_outputs(outputs)
    if dashboard_index is not None and dashboard_index.exists():
        print(f"[offline_workflow] Dashboard written: {dashboard_index.resolve()}")
        print(f"[offline_workflow] Dashboard URL    : {dashboard_index.resolve().as_uri()}")
        return

    expected = str(dashboard_index) if dashboard_index is not None else "diagnostics_root was not set"
    raise FileNotFoundError(
        "[offline_workflow] Dashboard generation was requested, but index.html was not written.\n"
        f"  Expected: {expected}"
    )


def run_offline(
    economy: str,
    scenario: str = "Target",
    module1_version: str | None = None,
    build_dashboards: bool = True,
) -> dict:
    """Run Modules 2-7 for one economy using static Module 1 inputs.

    Parameters
    ----------
    economy:
        Canonical economy code, e.g. ``"20_USA"`` or ``"01_AUS"``.
    scenario:
        Scenario label. Defaults to ``"Target"``.
    module1_version:
        Version folder name inside the Module 1 defaults directory.
        ``None`` selects the most recently modified version.
    build_dashboards:
        Whether to build HTML dashboard outputs.

    Returns
    -------
    dict
        Workflow outputs dict from ``run_for_economy``.
    """
    sys.path.insert(0, str(CODEBASE_DIR))
    from road_workflow import run_for_economy  # noqa: PLC0415

    module1_dir = _resolve_module1_dir()
    print(f"[offline_workflow] Module 1 source : {module1_dir}")
    if module1_version:
        print(f"[offline_workflow] Module 1 version: {module1_version}")
    else:
        print("[offline_workflow] Module 1 version: auto (most recently modified)")

    start = time.perf_counter()
    outputs = run_for_economy(
        economy=economy,
        scenario=scenario,
        module1_defaults_dir=str(module1_dir),
        module1_defaults_version=module1_version,
        enable_visualisations=build_dashboards,
    )
    _confirm_dashboard_written(outputs, build_dashboards=build_dashboards)
    print(f"[offline_workflow] {economy} completed in {time.perf_counter() - start:.1f}s")
    return outputs


def run_offline_all(
    scenario: str = "Target",
    module1_version: str | None = None,
    build_dashboards: bool = True,
    economies: list[str] | None = None,
) -> list[dict]:
    """Run Modules 2-7 for all (or selected) economies using static Module 1 inputs.

    Parameters
    ----------
    scenario:
        Scenario label.
    module1_version:
        Version folder name. ``None`` selects the most recently modified version.
    build_dashboards:
        Whether to build HTML dashboard outputs.
    economies:
        Explicit list of economy codes to run. ``None`` discovers all economies
        from the Module 1 defaults directory.

    Returns
    -------
    list[dict]
        One result dict per economy with keys ``economy``, ``ok``, ``seconds``,
        and ``error`` (on failure).
    """
    sys.path.insert(0, str(str(REPO_ROOT / "scripts")))
    from run_all_economies import discover_economies  # noqa: PLC0415

    module1_dir = _resolve_module1_dir()
    all_economies = discover_economies(module1_dir, version=module1_version)
    to_run = economies if economies is not None else all_economies

    results: list[dict] = []
    for economy in to_run:
        try:
            outputs = run_offline(
                economy,
                scenario=scenario,
                module1_version=module1_version,
                build_dashboards=build_dashboards,
            )
            dashboard_index = _dashboard_index_from_outputs(outputs)
            results.append({
                "economy": economy,
                "ok": True,
                "dashboard_index": str(dashboard_index) if dashboard_index else "",
            })
        except Exception:
            print(f"[offline_workflow] FAILED: {economy}")
            print(traceback.format_exc())
            results.append({"economy": economy, "ok": False, "error": traceback.format_exc()})

    ok = sum(1 for r in results if r["ok"])
    print(f"\n[offline_workflow] {ok}/{len(results)} economies completed successfully.")
    return results


# ---------------------------------------------------------------------------
# Edit these constants and run this file directly
# ---------------------------------------------------------------------------

ECONOMY = "01_AUS"          # single economy to run; ignored when RUN_ALL is True
RUN_ALL = False              # set True to run all economies
SCENARIO = "Target"
MODULE1_VERSION: str | None = None   # None = auto-select most recently modified
BUILD_DASHBOARDS = True

# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if RUN_ALL:
        run_offline_all(
            scenario=SCENARIO,
            module1_version=MODULE1_VERSION,
            build_dashboards=BUILD_DASHBOARDS,
        )
    else:
        run_offline(
            economy=ECONOMY,
            scenario=SCENARIO,
            module1_version=MODULE1_VERSION,
            build_dashboards=BUILD_DASHBOARDS,
        )
