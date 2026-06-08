from __future__ import annotations

import pandas as pd
import pytest

from road_workflow import build_post_reconciliation_stock_targets


def test_post_reconciliation_stock_targets_preserve_final_target() -> None:
    stock_targets = pd.DataFrame(
        [
            {
                "economy": "12_NZ",
                "scenario": "Target",
                "year": 2022,
                "transport_type": "passenger",
                "vehicle_type": "LPVs",
                "target_stock": 100.0,
            },
            {
                "economy": "12_NZ",
                "scenario": "Target",
                "year": 2023,
                "transport_type": "passenger",
                "vehicle_type": "LPVs",
                "target_stock": 130.0,
            },
            {
                "economy": "12_NZ",
                "scenario": "Target",
                "year": 2024,
                "transport_type": "passenger",
                "vehicle_type": "LPVs",
                "target_stock": 200.0,
            },
        ]
    )
    reconciliation_scalars = pd.DataFrame(
        [
            {
                "economy": "12_NZ",
                "scenario": "Target",
                "transport_type": "passenger",
                "vehicle_type": "LPVs",
                "drive_type": "ICE",
                "fuel": "Motor gasoline",
                "adjusted_stock": 80.0,
                "adjusted_mileage_km_per_year": 10_000.0,
                "adjusted_efficiency_km_per_gj": 100.0,
                "final_branch_fuel_pj": 0.008,
                "leap_branch_path": "Demand\\Passenger road\\LPVs\\ICE\\Motor gasoline",
            }
        ]
    )

    result = build_post_reconciliation_stock_targets(
        stock_targets,
        reconciliation_scalars,
        base_year=2022,
        final_year=2024,
    )

    by_year = result.set_index("year")["target_stock"]
    assert by_year.loc[2022] == pytest.approx(80.0)
    assert by_year.loc[2023] == pytest.approx(120.0)
    assert by_year.loc[2024] == pytest.approx(200.0)
    assert result.set_index("year").loc[2022, "pre_reconciliation_target_stock"] == pytest.approx(100.0)


def test_freight_post_reconciliation_stock_targets_preserve_growth_index() -> None:
    stock_targets = pd.DataFrame(
        [
            {
                "economy": "12_NZ",
                "scenario": "Target",
                "year": 2022,
                "transport_type": "freight",
                "vehicle_type": "Trucks",
                "target_stock": 100.0,
            },
            {
                "economy": "12_NZ",
                "scenario": "Target",
                "year": 2023,
                "transport_type": "freight",
                "vehicle_type": "Trucks",
                "target_stock": 130.0,
            },
            {
                "economy": "12_NZ",
                "scenario": "Target",
                "year": 2024,
                "transport_type": "freight",
                "vehicle_type": "Trucks",
                "target_stock": 200.0,
            },
        ]
    )
    reconciliation_scalars = pd.DataFrame(
        [
            {
                "economy": "12_NZ",
                "scenario": "Target",
                "transport_type": "freight",
                "vehicle_type": "Trucks",
                "drive_type": "ICE",
                "size": "heavy",
                "fuel": "Gas and diesel oil",
                "adjusted_stock": 80.0,
                "adjusted_mileage_km_per_year": 10_000.0,
                "adjusted_efficiency_km_per_gj": 100.0,
                "final_branch_fuel_pj": 0.008,
                "leap_branch_path": "Demand\\Freight road\\Trucks\\ICE heavy\\Gas and diesel oil",
            }
        ]
    )

    result = build_post_reconciliation_stock_targets(
        stock_targets,
        reconciliation_scalars,
        base_year=2022,
        final_year=2024,
    )

    by_year = result.set_index("year")
    assert by_year.loc[2022, "target_stock"] == pytest.approx(80.0)
    assert by_year.loc[2023, "target_stock"] == pytest.approx(104.0)
    assert by_year.loc[2024, "target_stock"] == pytest.approx(160.0)
    assert by_year.loc[2024, "target_stock"] / by_year.loc[2022, "target_stock"] == pytest.approx(2.0)
    assert by_year.loc[2024, "stock_target_adjustment_method"] == "preserve_growth_index_from_reconciled_base"
