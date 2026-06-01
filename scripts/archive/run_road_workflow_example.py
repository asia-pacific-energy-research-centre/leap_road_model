"""
run_road_workflow_example.py
============================
Minimal end-to-end example of the road model workflow for economy 12_NZ.

Demonstrates:
  - How to build RoadWorkflowConfig and RoadWorkflowInputs
  - The enable_visualisations switch  (True = PNG charts + HTML dashboard)
  - The run_m7 switch                 (True = run Module 7 mirror model)
  - Predictable output paths under results/example_run/ and
    plotting_output/example_run/

Usage::

    python scripts/run_road_workflow_example.py

All outputs land in:
  results/example_run/12_NZ/          ← CSV tables (T4 through T13)
  plotting_output/example_run/12_NZ/  ← matplotlib PNGs + HTML dashboard

To turn off all visuals (e.g. for batch runs), set ENABLE_VIS = False below.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Add codebase/ to sys.path so this script can be run from repo root
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "codebase"))

from road_workflow import RoadWorkflowConfig, RoadWorkflowInputs, run_with_config

# ===========================================================================
# SWITCHES  —  toggle these to control what the run produces
# ===========================================================================

ECONOMY = "12_NZ"

# True  → write matplotlib PNG charts + interactive Plotly HTML dashboard.
# False → skip all visualisation output (faster for batch runs).
ENABLE_VIS = True

# True  → run Module 7 mirror model after Module 6.
# False → stop after Module 6 (default).
RUN_MODULE_7 = False

# ===========================================================================
# OUTPUT PATHS  —  predictable, all under repo root
# ===========================================================================

OUTPUT_ROOT = REPO_ROOT / "results" / "example_run" / ECONOMY
DIAG_ROOT = REPO_ROOT / "plotting_output" / "example_run" / ECONOMY

# ===========================================================================
# SYNTHETIC INPUTS
# The road model workflow requires external data for Modules 3 and 6.
# Below we build NZ-like synthetic series so the script runs self-contained.
# Replace these with real data from your ESTO/population pipeline.
# ===========================================================================

YEARS = list(range(2022, 2061))
HIST_YEARS = list(range(2010, 2023))


def make_population() -> pd.Series:
    """Synthetic NZ-like population (5 M, growing at ~1 %/yr)."""
    return pd.Series(
        5_000_000 * (1.01 ** np.arange(len(YEARS))),
        index=YEARS,
    )


def make_gdp() -> pd.Series:
    """Synthetic NZ-like GDP index (growing at ~2 %/yr from base 100)."""
    return pd.Series(
        200_000 * (1.02 ** np.arange(len(YEARS))),
        index=YEARS,
    )


def make_esto_road_energy() -> pd.DataFrame:
    """
    Synthetic ESTO road energy (PJ) by transport type.

    Required columns: year, transport_type, energy_pj.
    Historical years only (Module 3 uses historical energy to calibrate trends).
    """
    rows = []
    for yr in HIST_YEARS:
        i = yr - HIST_YEARS[0]
        rows.append({"year": yr, "transport_type": "passenger", "energy_pj": 50.0 * (1.025 ** i)})
        rows.append({"year": yr, "transport_type": "freight",   "energy_pj": 20.0 * (1.030 ** i)})
    return pd.DataFrame(rows)


def make_esto_fuel_totals() -> pd.DataFrame:
    """
    Synthetic ESTO fuel totals (PJ) for Module 6 reconciliation.

    Required columns: fuel, energy_pj.
    Represents aggregate road sector energy by fuel for the base year.
    """
    return pd.DataFrame([
        {"fuel": "Gasoline",    "energy_pj": 45.0},
        {"fuel": "Diesel",      "energy_pj": 22.0},
        {"fuel": "Electricity", "energy_pj":  3.5},
        {"fuel": "LPG",         "energy_pj":  1.2},
    ])


# ===========================================================================
# MAIN
# ===========================================================================

def main() -> None:
    print(f"\n{'='*60}")
    print(f"  Road model example run — economy: {ECONOMY}")
    print(f"  enable_visualisations : {ENABLE_VIS}")
    print(f"  run_m7 (mirror model) : {RUN_MODULE_7}")
    print(f"  output_root           : {OUTPUT_ROOT.relative_to(REPO_ROOT)}")
    if ENABLE_VIS:
        print(f"  diagnostics_root      : {DIAG_ROOT.relative_to(REPO_ROOT)}")
        print(f"  HTML dashboard        : {(DIAG_ROOT / 'dashboard').relative_to(REPO_ROOT)}")
    print(f"{'='*60}\n")

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------
    config = RoadWorkflowConfig(
        economy=ECONOMY,
        scenarios=["Reference", "Target"],
        base_year=2022,
        final_year=2060,

        # Config directory containing fuel_mappings.yaml etc.
        config_dir=REPO_ROOT / "codebase" / "config",

        # Path to per-economy Module 1 default CSVs.
        # Generated by scripts/generate_module1_defaults.py.
        module1_defaults_dir=REPO_ROOT / "input_data" / "module1_defaults",
        module1_defaults_version=None,  # None = latest version folder

        # Module flags
        run_m2=True,
        run_m3=True,
        run_m4=True,
        run_m5=True,
        run_m6=True,
        run_m7=RUN_MODULE_7,

        # Visualisation switch
        enable_visualisations=ENABLE_VIS,

        # Output paths
        output_root=OUTPUT_ROOT,
        diagnostics_root=DIAG_ROOT if ENABLE_VIS else None,

        save_csv_outputs=True,
    )

    # ------------------------------------------------------------------
    # Inputs
    # ------------------------------------------------------------------
    inputs = RoadWorkflowInputs(
        population=make_population(),
        gdp=make_gdp(),
        esto_road_energy_pj=make_esto_road_energy(),

        # Module 6: fuel totals for reconciliation
        esto_fuel_totals=make_esto_fuel_totals(),

        # No future sales-share overrides — Module 5 will use base-year shares.
        future_sales_shares=None,
    )

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    outputs = run_with_config(config, inputs)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    timings = outputs.get("timings", {})
    total = sum(v for k, v in timings.items() if k.endswith("_seconds"))

    print("\nRun complete.")
    print(f"  Total time : {total:.1f} s")
    for k, v in timings.items():
        if k.endswith("_seconds"):
            print(f"    {k:<30} {v:.2f} s")

    csv_outputs = [
        ("T4 base-year branches",    "T4"),
        ("T5 stock targets",         "T5"),
        ("T6 sales/turnover",        "T6"),
        ("T7 sales shares (base)",   "T7"),
        ("T7f sales shares (proj)",  "T7f"),
        ("T9 reconciliation",        "T9"),
        ("T12 reconciliation diag.", "T12"),
    ]
    if RUN_MODULE_7:
        csv_outputs.append(("T13 mirror model", "T13"))

    print("\nKey output tables:")
    for label, key in csv_outputs:
        df = outputs.get(key)
        if df is not None and not df.empty:
            print(f"  {label:<28} {len(df):>6} rows  → {OUTPUT_ROOT.relative_to(REPO_ROOT)}")
        else:
            print(f"  {label:<28} (not produced)")

    if ENABLE_VIS:
        dashboard_dir = DIAG_ROOT / "dashboard"
        if dashboard_dir.exists():
            pages = list(dashboard_dir.glob("*.html"))
            print(f"\nHTML dashboard ({len(pages)} pages):")
            print(f"  Open: {(dashboard_dir / 'index.html').relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
