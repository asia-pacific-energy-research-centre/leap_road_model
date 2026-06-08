"""
Tests for Module 7 - Python mirror and post-LEAP validation.
"""

from __future__ import annotations

import pandas as pd
import pytest

from modules.module7_mirror import (
    _validate_assumptions_for_nonzero_sales,
    build_base_technology_assumptions,
    calculate_mirror_fuel_outputs,
    compare_with_leap,
    run_module7_mirror,
)


def _sales_turnover() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "economy": "12_NZ",
            "scenario": "Reference",
            "year": 2022,
            "transport_type": "passenger",
            "vehicle_type": "LPVs",
            "drive_type": "ICE",
            "surviving_stock": 900.0,
            "new_sales": 120.0,
            "additional_retirements": 20.0,
            "stock": 1000.0,
            "scrappage_for_leap": 0.0,
        },
        {
            "economy": "12_NZ",
            "scenario": "Reference",
            "year": 2023,
            "transport_type": "passenger",
            "vehicle_type": "LPVs",
            "drive_type": "ICE",
            "surviving_stock": 920.0,
            "new_sales": 130.0,
            "additional_retirements": 10.0,
            "stock": 1040.0,
            "scrappage_for_leap": 0.0,
        },
    ])


def _reconciliation_scalars() -> pd.DataFrame:
    base = {
        "economy": "12_NZ",
        "scenario": "Reference",
        "transport_type": "passenger",
        "vehicle_type": "LPVs",
        "drive_type": "ICE",
        "adjusted_stock": 1000.0,
        "adjusted_mileage_km_per_year": 10_000.0,
        "adjusted_efficiency_km_per_gj": 100.0,
    }
    return pd.DataFrame([
        {
            **base,
            "fuel": "Motor gasoline",
            "final_branch_fuel_pj": 0.08,
            "leap_branch_path": "Demand\\Passenger road\\LPVs\\ICE\\Motor gasoline",
        },
        {
            **base,
            "fuel": "Biogasoline",
            "final_branch_fuel_pj": 0.02,
            "leap_branch_path": "Demand\\Passenger road\\LPVs\\ICE\\Biogasoline",
        },
    ])


def _device_shares() -> pd.DataFrame:
    base = {
        "economy": "12_NZ",
        "scenario": "Reference",
        "transport_type": "passenger",
        "vehicle_type": "LPVs",
        "drive_type": "ICE",
    }
    return pd.DataFrame([
        {
            **base,
            "fuel": "Motor gasoline",
            "leap_branch_path": "Demand\\Passenger road\\LPVs\\ICE\\Motor gasoline",
            "device_share": 0.8,
        },
        {
            **base,
            "fuel": "Biogasoline",
            "leap_branch_path": "Demand\\Passenger road\\LPVs\\ICE\\Biogasoline",
            "device_share": 0.2,
        },
    ])


def test_base_assumptions_deduplicate_fuel_rows_to_technology_path():
    base = build_base_technology_assumptions(_reconciliation_scalars())

    assert len(base) == 1
    assert base["leap_branch_path"].iloc[0] == "Demand\\Passenger road\\LPVs\\ICE"
    assert base["base_mileage_km_per_year"].iloc[0] == 10_000.0


def test_base_assumptions_sum_fuel_implied_vehicles():
    scalars = _reconciliation_scalars()
    scalars.loc[scalars["fuel"] == "Biogasoline", "adjusted_stock"] = 1.0

    base = build_base_technology_assumptions(scalars)

    assert base["base_stock"].iloc[0] == 1000.0
    assert pytest.approx(base["base_energy_pj"].iloc[0], rel=1e-9) == 0.1


def test_run_module7_calculates_stock_activity_and_energy():
    outputs = run_module7_mirror(
        sales_turnover=_sales_turnover(),
        reconciliation_scalars=_reconciliation_scalars(),
        device_shares=_device_shares(),
        projection_years=[2022],
    )

    t13 = outputs["T13"]
    row = t13.iloc[0]

    assert row["mirror_stock"] == 1000.0
    assert row["mirror_vehicle_km"] == 10_000_000.0
    assert pytest.approx(row["mirror_energy_pj"], rel=1e-9) == 0.1


def test_run_module7_splits_vehicle_level_turnover_by_sales_share():
    sales_turnover = pd.DataFrame([
        {
            "economy": "12_NZ",
            "scenario": "Reference",
            "year": 2022,
            "transport_type": "passenger",
            "vehicle_type": "LPVs",
            "stock": 1000.0,
            "new_sales": 0.0,
            "total_retirements": 0.0,
        },
        {
            "economy": "12_NZ",
            "scenario": "Reference",
            "year": 2023,
            "transport_type": "passenger",
            "vehicle_type": "LPVs",
            "stock": 1100.0,
            "new_sales": 200.0,
            "total_retirements": 100.0,
        },
    ])
    scalars = pd.DataFrame([
        {
            "economy": "12_NZ",
            "scenario": "Reference",
            "transport_type": "passenger",
            "vehicle_type": "LPVs",
            "drive_type": "ICE",
            "fuel": "Motor gasoline",
            "adjusted_stock": 900.0,
            "adjusted_mileage_km_per_year": 10_000.0,
            "adjusted_efficiency_km_per_gj": 100.0,
            "final_branch_fuel_pj": 0.09,
            "leap_branch_path": "Demand\\Passenger road\\LPVs\\ICE\\Motor gasoline",
        },
        {
            "economy": "12_NZ",
            "scenario": "Reference",
            "transport_type": "passenger",
            "vehicle_type": "LPVs",
            "drive_type": "BEV",
            "fuel": "Electricity",
            "adjusted_stock": 100.0,
            "adjusted_mileage_km_per_year": 10_000.0,
            "adjusted_efficiency_km_per_gj": 400.0,
            "final_branch_fuel_pj": 0.0025,
            "leap_branch_path": "Demand\\Passenger road\\LPVs\\BEV\\Electricity",
        },
    ])
    device_shares = pd.DataFrame([
        {
            "economy": "12_NZ",
            "scenario": "Reference",
            "transport_type": "passenger",
            "vehicle_type": "LPVs",
            "drive_type": "ICE",
            "fuel": "Motor gasoline",
            "device_share": 1.0,
        },
        {
            "economy": "12_NZ",
            "scenario": "Reference",
            "transport_type": "passenger",
            "vehicle_type": "LPVs",
            "drive_type": "BEV",
            "fuel": "Electricity",
            "device_share": 1.0,
        },
    ])
    sales_shares = pd.DataFrame([
        {"economy": "12_NZ", "scenario": "Reference", "year": 2022, "vehicle_type": "LPVs", "drive_type": "ICE", "sales_share": 0.9},
        {"economy": "12_NZ", "scenario": "Reference", "year": 2022, "vehicle_type": "LPVs", "drive_type": "BEV", "sales_share": 0.1},
        {"economy": "12_NZ", "scenario": "Reference", "year": 2023, "vehicle_type": "LPVs", "drive_type": "ICE", "sales_share": 0.25},
        {"economy": "12_NZ", "scenario": "Reference", "year": 2023, "vehicle_type": "LPVs", "drive_type": "BEV", "sales_share": 0.75},
    ])

    outputs = run_module7_mirror(
        sales_turnover=sales_turnover,
        reconciliation_scalars=scalars,
        device_shares=device_shares,
        sales_shares=sales_shares,
        projection_years=[2022, 2023],
    )

    stocks = outputs["T13"].set_index(["year", "drive_type"])["mirror_stock"]
    assert pytest.approx(stocks[(2022, "ICE")], rel=1e-9) == 900.0
    assert pytest.approx(stocks[(2022, "BEV")], rel=1e-9) == 100.0
    assert pytest.approx(stocks[(2023, "ICE")], rel=1e-9) == 860.0
    assert pytest.approx(stocks[(2023, "BEV")], rel=1e-9) == 240.0


def test_missing_assumption_validation_reports_deduplicated_branches():
    merged = pd.DataFrame([
        {
            "economy": "12_NZ",
            "scenario": "Reference",
            "vehicle_type": "LPVs",
            "drive_type": "ICE",
            "size": "small",
            "new_sales": 10.0,
            "base_mileage_km_per_year": None,
            "base_efficiency_km_per_gj": None,
        },
        {
            "economy": "12_NZ",
            "scenario": "Reference",
            "vehicle_type": "LPVs",
            "drive_type": "ICE",
            "size": "small",
            "new_sales": 12.0,
            "base_mileage_km_per_year": None,
            "base_efficiency_km_per_gj": None,
        },
    ])

    with pytest.raises(ValueError) as excinfo:
        _validate_assumptions_for_nonzero_sales(merged)

    message = str(excinfo.value)
    assert "1 branch(es)" in message
    assert "mileage and efficiency" in message


def test_mileage_and_efficiency_adjustments_are_applied():
    mileage_adj = pd.DataFrame([{
        "economy": "12_NZ",
        "scenario": "Reference",
        "year": 2022,
        "vehicle_type": "LPVs",
        "drive_type": "ICE",
        "value": 1.10,
    }])
    efficiency_adj = pd.DataFrame([{
        "economy": "12_NZ",
        "scenario": "Reference",
        "year": 2022,
        "vehicle_type": "LPVs",
        "drive_type": "ICE",
        "value": 1.25,
    }])

    outputs = run_module7_mirror(
        sales_turnover=_sales_turnover(),
        reconciliation_scalars=_reconciliation_scalars(),
        device_shares=_device_shares(),
        projection_years=[2022],
        mileage_adjustment_variables=mileage_adj,
        efficiency_adjustment_variables=efficiency_adj,
    )

    row = outputs["T13"].iloc[0]
    assert row["mirror_mileage_km_per_year"] == 11_000.0
    assert row["mirror_efficiency_km_per_gj"] == 125.0
    assert pytest.approx(row["mirror_energy_pj"], rel=1e-9) == 0.088


def test_fuel_outputs_apply_device_shares_and_sum_to_technology_energy():
    outputs = run_module7_mirror(
        sales_turnover=_sales_turnover(),
        reconciliation_scalars=_reconciliation_scalars(),
        device_shares=_device_shares(),
        projection_years=[2022],
    )

    fuel = outputs["T13_fuel"]
    by_fuel = fuel.set_index("fuel")["mirror_fuel_energy_pj"]

    assert pytest.approx(by_fuel["Motor gasoline"], rel=1e-9) == 0.08
    assert pytest.approx(by_fuel["Biogasoline"], rel=1e-9) == 0.02
    assert pytest.approx(fuel["mirror_fuel_energy_pj"].sum(), rel=1e-9) == 0.1


def test_scrappage_dict_reduces_mirror_stock():
    outputs = run_module7_mirror(
        sales_turnover=_sales_turnover(),
        reconciliation_scalars=_reconciliation_scalars(),
        device_shares=_device_shares(),
        projection_years=[2022],
        scrappage_by_year={"LPVs": {2022: 50.0}},
    )

    row = outputs["T13"].iloc[0]
    assert row["mirror_stock"] == 950.0


def test_compare_with_leap_populates_differences():
    outputs = run_module7_mirror(
        sales_turnover=_sales_turnover(),
        reconciliation_scalars=_reconciliation_scalars(),
        device_shares=_device_shares(),
        projection_years=[2022],
    )
    mirror = outputs["T13"]
    leap = pd.DataFrame([
        {
            "economy": "12_NZ",
            "scenario": "Reference",
            "year": 2022,
            "leap_branch_path": "Demand\\Passenger road\\LPVs\\ICE",
            "variable": "Stock",
            "value": 990.0,
        },
        {
            "economy": "12_NZ",
            "scenario": "Reference",
            "year": 2022,
            "leap_branch_path": "Demand\\Passenger road\\LPVs\\ICE",
            "variable": "Mirror Energy",
            "value": 0.11,
        },
    ])

    compared = compare_with_leap(mirror, leap, energy_variable="Mirror Energy")
    row = compared.iloc[0]

    assert row["leap_stock"] == 990.0
    assert row["stock_difference"] == 10.0
    assert pytest.approx(row["energy_difference_pj"], rel=1e-9) == -0.01


def test_run_module7_writes_png_charts(tmp_path):
    run_module7_mirror(
        sales_turnover=_sales_turnover(),
        reconciliation_scalars=_reconciliation_scalars(),
        device_shares=_device_shares(),
        diagnostics_dir=tmp_path,
    )

    charts = sorted((tmp_path / "module7").glob("*.png"))
    assert charts
    assert {p.name for p in charts}.issuperset({
        "module7_mirror_stock_by_vehicle_type.png",
        "module7_mirror_vehicle_km_by_vehicle_type.png",
        "module7_mirror_energy_by_transport_type.png",
        "module7_mirror_fuel_energy_mix.png",
    })


def test_validate_assumptions_raises_when_sales_set_but_mileage_missing():
    merged = pd.DataFrame([{
        "economy": "01_AUS",
        "scenario": "Target",
        "vehicle_type": "Trucks",
        "drive_type": "ICE",
        "size": "heavy",
        "new_sales": 50.0,
        "base_mileage_km_per_year": float("nan"),
        "base_efficiency_km_per_gj": 80.0,
    }])
    with pytest.raises(ValueError, match="Sales shares are set > 0"):
        _validate_assumptions_for_nonzero_sales(merged)


def test_validate_assumptions_raises_when_sales_set_but_efficiency_missing():
    merged = pd.DataFrame([{
        "economy": "01_AUS",
        "scenario": "Target",
        "vehicle_type": "Trucks",
        "drive_type": "ICE",
        "size": "heavy",
        "new_sales": 50.0,
        "base_mileage_km_per_year": 50_000.0,
        "base_efficiency_km_per_gj": 0.0,
    }])
    with pytest.raises(ValueError, match="Sales shares are set > 0"):
        _validate_assumptions_for_nonzero_sales(merged)


def test_validate_assumptions_does_not_raise_when_sales_zero():
    merged = pd.DataFrame([{
        "economy": "01_AUS",
        "scenario": "Target",
        "vehicle_type": "Trucks",
        "drive_type": "ICE",
        "size": "heavy",
        "new_sales": 0.0,
        "base_mileage_km_per_year": float("nan"),
        "base_efficiency_km_per_gj": float("nan"),
    }])
    _validate_assumptions_for_nonzero_sales(merged)  # should not raise


def test_validate_assumptions_error_message_names_affected_branches():
    merged = pd.DataFrame([
        {
            "economy": "01_AUS",
            "scenario": "Target",
            "vehicle_type": "Trucks",
            "drive_type": "ICE heavy",
            "size": "heavy",
            "new_sales": 100.0,
            "base_mileage_km_per_year": float("nan"),
            "base_efficiency_km_per_gj": float("nan"),
        },
        {
            "economy": "01_AUS",
            "scenario": "Target",
            "vehicle_type": "LPVs",
            "drive_type": "FCEV",
            "size": "medium",
            "new_sales": 20.0,
            "base_mileage_km_per_year": float("nan"),
            "base_efficiency_km_per_gj": float("nan"),
        },
    ])
    with pytest.raises(ValueError) as exc_info:
        _validate_assumptions_for_nonzero_sales(merged)
    msg = str(exc_info.value)
    assert "Trucks" in msg
    assert "LPVs" in msg
    assert "researcher input parameters" in msg
