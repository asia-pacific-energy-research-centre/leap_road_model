"""
Tests for Module 7 - Python mirror and post-LEAP validation.
"""

from __future__ import annotations

import pandas as pd
import pytest

from modules.module7_mirror import (
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
            "leap_branch_path": "Demand\\Passenger road\\LPVs\\ICE\\Motor gasoline",
        },
        {
            **base,
            "fuel": "Biogasoline",
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
