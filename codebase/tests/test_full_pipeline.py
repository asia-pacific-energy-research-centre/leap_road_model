"""
End-to-end integration tests for the road model pipeline.

Each test calls run_for_economy() with real Module 1 defaults and ESTO macro data,
verifies the full pipeline (modules 2–6) completes without error, and checks that
the key output tables are present and non-empty.

Run just the fast smoke test (12_NZ only):
    pytest codebase/tests/test_full_pipeline.py -k smoke

Run all 21 economies (slow, ~minutes):
    pytest codebase/tests/test_full_pipeline.py -m slow
"""
from __future__ import annotations

from pathlib import Path

import pytest

from road_workflow import run_for_economy

ALL_ECONOMIES = [
    "01_AUS", "02_BD",  "03_CDA", "04_CHL", "05_PRC",
    "06_HKC", "07_INA", "08_JPN", "09_ROK", "10_MAS",
    "11_MEX", "12_NZ",  "13_PNG", "14_PE",  "15_PHL",
    "16_RUS", "17_SGP", "18_CT",  "19_THA", "20_USA", "21_VN",
]


_DEFAULTS_VERSION = "v2026_05_25_best_guess"


def _run_and_assert(economy: str, tmp_path: Path) -> None:
    result = run_for_economy(
        economy,
        scenario="Reference",
        enable_visualisations=False,
        output_root=tmp_path / economy,
        module1_defaults_version=_DEFAULTS_VERSION,
        save_csv_outputs=False,
    )
    assert "T4" in result, f"{economy}: T4 (base-year branches) missing"
    assert "T11" in result, f"{economy}: T11 (LEAP-ready table) missing"
    assert len(result["T11"]) > 0, f"{economy}: T11 is empty"
    assert "timings" in result, f"{economy}: timings missing"
    total_time = sum(result["timings"].values())
    assert total_time > 0, f"{economy}: timings all zero"


def test_full_pipeline_smoke_nz(tmp_path: Path) -> None:
    """Fast smoke test — 12_NZ with default scenario, no visualisations."""
    _run_and_assert("12_NZ", tmp_path)


@pytest.mark.slow
@pytest.mark.parametrize("economy", ALL_ECONOMIES)
def test_full_pipeline_all_economies(economy: str, tmp_path: Path) -> None:
    """Full run for every APEC economy using the pre-generated Module 1 defaults."""
    _run_and_assert(economy, tmp_path)
