"""
Tests for Module 5 — sales-share preparation and future scaling.

Focus:
  - scenario alias handling (e.g. TGT/REF)
  - economy alias handling (long region names vs economy codes)
  - successful shape-preserving scaling when valid future data is present
"""

from __future__ import annotations

import pathlib
import sys

import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from modules.module5_sales_shares import _prepare_future_shares, run_module5


def _base_year_branches(scenario: str = "TGT") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "economy": "20_USA",
                "scenario": scenario,
                "vehicle_type": "LPVs",
                "drive_type": "ICE",
                "stock": 80.0,
            },
            {
                "economy": "20_USA",
                "scenario": scenario,
                "vehicle_type": "LPVs",
                "drive_type": "BEV",
                "stock": 20.0,
            },
        ]
    )


def _future_sales_rows(economy: str = "United States", scenario: str = "Target") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"economy": economy, "scenario": scenario, "year": 2023, "vehicle_type": "LPVs", "drive_type": "ICE", "sales_share": 0.85},
            {"economy": economy, "scenario": scenario, "year": 2023, "vehicle_type": "LPVs", "drive_type": "BEV", "sales_share": 0.15},
            {"economy": economy, "scenario": scenario, "year": 2060, "vehicle_type": "LPVs", "drive_type": "ICE", "sales_share": 0.30},
            {"economy": economy, "scenario": scenario, "year": 2060, "vehicle_type": "LPVs", "drive_type": "BEV", "sales_share": 0.70},
        ]
    )


class TestPrepareFutureSharesAliases:
    def test_accepts_scenario_alias_tgt_for_target(self):
        prepared = _prepare_future_shares(
            future_sales_shares=_future_sales_rows(economy="20_USA", scenario="Target"),
            economy="20_USA",
            scenarios=["TGT"],
            economy_aliases=["20_USA"],
        )

        assert not prepared.empty
        assert set(prepared["scenario"].unique()) == {"TGT"}

    def test_accepts_long_region_name_for_code_economy(self):
        prepared = _prepare_future_shares(
            future_sales_shares=_future_sales_rows(economy="United States", scenario="Target"),
            economy="20_USA",
            scenarios=["Target"],
            economy_aliases=["United States"],
        )

        assert not prepared.empty
        assert set(prepared["economy"].unique()) == {"20_USA"}


class TestRunModule5AliasesAndScaling:
    def test_uses_shape_preserve_with_alias_inputs(self):
        t7, t7f = run_module5(
            base_year_branches=_base_year_branches(scenario="TGT"),
            future_sales_shares=_future_sales_rows(economy="United States", scenario="Target"),
            economy="20_USA",
            scenarios=["TGT"],
            economy_aliases=["20_USA", "United States"],
        )

        assert not t7.empty
        assert not t7f.empty

        future_only = t7f[t7f["year"] > 2022]
        assert (future_only["scaling_method"] == "shape_preserve_ice_residual").any()
        assert not (future_only["scaling_method"] == "flat_base_fallback").any()

    def test_module1_ice_override_drops_unprovided_stock_fallback_drives(self):
        base_year_branches = pd.DataFrame(
            [
                {"economy": "01_AUS", "scenario": "Target", "vehicle_type": "LCVs", "drive_type": "ICE", "stock": 880.0},
                {"economy": "01_AUS", "scenario": "Target", "vehicle_type": "LCVs", "drive_type": "BEV", "stock": 50.0},
                {"economy": "01_AUS", "scenario": "Target", "vehicle_type": "LCVs", "drive_type": "PHEV", "stock": 60.0},
                {"economy": "01_AUS", "scenario": "Target", "vehicle_type": "LCVs", "drive_type": "FCEV", "stock": 55.0},
            ]
        )
        module1_sales_shares = pd.DataFrame(
            [
                {"economy": "01_AUS", "scenario": "Target", "vehicle_type": "LCVs", "drive_type": "ICE", "sales_share": 0.88, "source_flag": "module1_input"},
                {"economy": "01_AUS", "scenario": "Target", "vehicle_type": "LCVs", "drive_type": "BEV", "sales_share": 0.05, "source_flag": "module1_input"},
                {"economy": "01_AUS", "scenario": "Target", "vehicle_type": "LCVs", "drive_type": "PHEV", "sales_share": 0.06, "source_flag": "module1_input"},
            ]
        )

        t7, _ = run_module5(
            base_year_branches=base_year_branches,
            economy="01_AUS",
            scenarios=["Target"],
            researcher_sales_shares=module1_sales_shares,
        )

        lcv = t7[t7["vehicle_type"].eq("LCVs")]
        assert set(lcv["drive_type"]) == {"ICE", "BEV", "PHEV"}
        assert lcv["sales_share"].sum() == pytest.approx(1.0)
