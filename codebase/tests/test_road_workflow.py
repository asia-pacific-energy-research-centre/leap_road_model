#%%
from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from road_workflow import _apply_stock_target_overrides, build_post_reconciliation_stock_targets


def _minimal_t5(years=(2022, 2030, 2040, 2060)) -> pd.DataFrame:
    rows = []
    for vt, tt in [("LPVs", "passenger"), ("Trucks", "freight")]:
        for yr in years:
            rows.append({
                "economy": "20_USA",
                "scenario": "Reference",
                "transport_type": tt,
                "vehicle_type": vt,
                "year": yr,
                "target_stock": 1_000_000.0 + (yr - 2022) * 10_000.0,
            })
    return pd.DataFrame(rows)


def _minimal_t9() -> pd.DataFrame:
    """Minimal reconciliation scalars (T9) with one fuel row per drive type."""
    return pd.DataFrame([
        {
            "economy": "20_USA", "scenario": "Reference",
            "transport_type": "passenger", "vehicle_type": "LPVs",
            "drive_type": "ICE", "size": None,
            "leap_branch_path": "Demand\\Passenger road\\LPVs\\ICE\\Motor gasoline",
            "adjusted_stock": 1_200_000.0,
            "adjusted_mileage_km_per_year": 12_000.0,
            "adjusted_efficiency_km_per_gj": 400.0,
            "final_branch_fuel_pj": 36.0,
        },
        {
            "economy": "20_USA", "scenario": "Reference",
            "transport_type": "freight", "vehicle_type": "Trucks",
            "drive_type": "Diesel", "size": None,
            "leap_branch_path": "Demand\\Freight road\\Trucks\\Diesel\\Gas and diesel oil",
            "adjusted_stock": 900_000.0,
            "adjusted_mileage_km_per_year": 40_000.0,
            "adjusted_efficiency_km_per_gj": 150.0,
            "final_branch_fuel_pj": 240.0,
        },
    ])


class TestApplyStockTargetOverrides:
    def test_reconciled_base_stock_broadcast_to_all_years(self):
        """
        Regression: reconciled_base_stock must be set on ALL year rows for an
        overridden vehicle type, not only the base year row.
        build_post_reconciliation_stock_targets achieves this via a merge;
        _apply_stock_target_overrides must match.
        """
        t5 = _minimal_t5()
        overrides = {
            "LPVs": pd.Series({2022: 1_200_000.0, 2030: 1_400_000.0, 2060: 1_800_000.0}),
        }
        out = _apply_stock_target_overrides(t5, overrides, base_year=2022)

        lpv_rows = out[out["vehicle_type"] == "LPVs"]
        assert not lpv_rows["reconciled_base_stock"].isna().any(), (
            "reconciled_base_stock must be non-NaN for every year of an overridden vehicle type"
        )
        # All year rows for the same vehicle type share the same reconciled_base_stock.
        assert lpv_rows["reconciled_base_stock"].nunique() == 1, (
            "reconciled_base_stock should be constant across years for a given vehicle type"
        )

    def test_non_overridden_vehicle_type_has_nan_reconciled_base_stock(self):
        t5 = _minimal_t5()
        overrides = {"LPVs": pd.Series({2022: 1_200_000.0, 2030: 1_400_000.0})}
        out = _apply_stock_target_overrides(t5, overrides, base_year=2022)

        trucks_rows = out[out["vehicle_type"] == "Trucks"]
        assert trucks_rows["reconciled_base_stock"].isna().all(), (
            "Non-overridden vehicle types should have NaN reconciled_base_stock"
        )

    def test_output_columns_match_build_post_reconciliation_stock_targets(self):
        """
        Both code paths (reimport override vs second-pass re-anchor) must produce
        T5 with the same column set so downstream consumers see a consistent schema.
        """
        t5 = _minimal_t5()
        t9 = _minimal_t9()

        post_recon = build_post_reconciliation_stock_targets(
            t5, t9, base_year=2022, final_year=2060
        )

        overrides = {
            "LPVs": pd.Series({2022: 1_200_000.0, 2030: 1_400_000.0, 2060: 1_800_000.0}),
            "Trucks": pd.Series({2022: 900_000.0, 2030: 1_100_000.0, 2060: 1_500_000.0}),
        }
        applied = _apply_stock_target_overrides(t5, overrides, base_year=2022)

        extra_in_post = sorted(set(post_recon.columns) - set(applied.columns))
        extra_in_applied = sorted(set(applied.columns) - set(post_recon.columns))
        assert not extra_in_post, f"Columns in build_post_reconciliation_stock_targets but not _apply_stock_target_overrides: {extra_in_post}"
        assert not extra_in_applied, f"Columns in _apply_stock_target_overrides but not build_post_reconciliation_stock_targets: {extra_in_applied}"
