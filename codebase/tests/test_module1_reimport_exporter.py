#%%
from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from adapters.module1_reimport_exporter import (
    MODULE1_REIMPORT_COLUMNS,
    build_reconciled_module1_reimport,
)
from adapters.road_module1_defaults import load_module1_for_economy
from road_workflow import parse_leap_format_inputs


def _source_rows() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "Economy": "20USA",
            "Scenario": "Current Accounts",
            "Branch Path": "Demand\\Passenger road\\LPVs",
            "Variable": "Stock",
            "Year": 2022,
            "Value": 1.0,
            "Scale": "Millions",
            "Units": "Device",
            "Source": "original_source.csv",
            "Comment": "Original stock note.",
            "Input Status": "default",
            "Shown In Interface": "True",
        },
        {
            "Economy": "20USA",
            "Scenario": "Current Accounts",
            "Branch Path": "Demand\\Passenger road\\LPVs\\ICE",
            "Variable": "Stock Share",
            "Year": 2022,
            "Value": 50.0,
            "Scale": "%",
            "Units": "Share",
            "Source": "original_source.csv",
            "Comment": "Original stock share note.",
            "Input Status": "default",
            "Shown In Interface": "True",
        },
        {
            "Economy": "20USA",
            "Scenario": "Current Accounts",
            "Branch Path": "Demand\\Passenger road\\LPVs\\ICE\\Motor gasoline",
            "Variable": "Mileage",
            "Year": 2022,
            "Value": 10.0,
            "Scale": "Thousands",
            "Units": "Kilometer",
            "Source": "original_source.csv",
            "Comment": "Original mileage note.",
            "Input Status": "default",
            "Shown In Interface": "True",
        },
        {
            "Economy": "20USA",
            "Scenario": "Current Accounts",
            "Branch Path": "Demand\\Passenger road\\LPVs\\ICE\\Motor gasoline",
            "Variable": "Fuel Economy",
            "Year": 2022,
            "Value": 8.0,
            "Scale": "",
            "Units": "MJ/100 km",
            "Source": "original_source.csv",
            "Comment": "Original efficiency note.",
            "Input Status": "default",
            "Shown In Interface": "True",
        },
        {
            "Economy": "20USA",
            "Scenario": "Target",
            "Branch Path": "Demand\\Passenger road\\LPVs\\ICE",
            "Variable": "Sales Share",
            "Year": 2030,
            "Value": 55.0,
            "Scale": "%",
            "Units": "Share",
            "Source": "original_source.csv",
            "Comment": "Leave untouched.",
            "Input Status": "default",
            "Shown In Interface": "False",
        },
    ])


def _t11_rows() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "economy": "20_USA",
            "scenario": "Current Accounts",
            "year": 2022,
            "leap_branch_path": "Demand\\Passenger road\\LPVs",
            "variable": "Stock",
            "value": 2_500_000.0,
            "unit": "Device",
        },
        {
            "economy": "20_USA",
            "scenario": "Current Accounts",
            "year": 2022,
            "leap_branch_path": "Demand\\Passenger road\\LPVs\\ICE",
            "variable": "Stock Share",
            "value": 60.0,
            "unit": "Share",
        },
        {
            "economy": "20_USA",
            "scenario": "Current Accounts",
            "year": 2022,
            "leap_branch_path": "Demand\\Passenger road\\LPVs\\ICE\\Motor gasoline",
            "variable": "Mileage",
            "value": 12_500.0,
            "unit": "Kilometer",
        },
        {
            "economy": "20_USA",
            "scenario": "Current Accounts",
            "year": 2022,
            "leap_branch_path": "Demand\\Passenger road\\LPVs\\ICE\\Motor gasoline",
            "variable": "Fuel Economy",
            "value": 7.5,
            "unit": "MJ/100 km",
        },
    ])


def test_reconciled_reimport_preserves_row_keys_and_metadata():
    source = _source_rows()
    out = build_reconciled_module1_reimport(source, _t11_rows(), base_year=2022)

    assert list(out.columns) == MODULE1_REIMPORT_COLUMNS
    assert set(map(tuple, out[["Branch Path", "Variable", "Scenario", "Year"]].to_numpy())) == set(
        map(tuple, source[["Branch Path", "Variable", "Scenario", "Year"]].to_numpy())
    )

    sales_share = out[out["Variable"] == "Sales Share"].iloc[0]
    assert sales_share["Value"] == pytest.approx(55.0)
    assert sales_share["Shown In Interface"] == "False"

    stock = out[out["Variable"] == "Stock"].iloc[0]
    assert stock["Source"] == "original_source.csv"
    assert stock["Comment"] == "Original stock note."
    assert stock["Input Status"] == "default"


def test_reconciled_reimport_preserves_units_and_applies_original_scale():
    out = build_reconciled_module1_reimport(_source_rows(), _t11_rows(), base_year=2022)

    stock = out[out["Variable"] == "Stock"].iloc[0]
    mileage = out[out["Variable"] == "Mileage"].iloc[0]
    efficiency = out[out["Variable"] == "Fuel Economy"].iloc[0]
    stock_share = out[out["Variable"] == "Stock Share"].iloc[0]

    assert stock["Value"] == pytest.approx(2.5)
    assert stock["Scale"] == "Millions"
    assert stock["Units"] == "Device"

    assert mileage["Value"] == pytest.approx(12.5)
    assert mileage["Scale"] == "Thousands"
    assert mileage["Units"] == "Kilometer"

    assert stock_share["Value"] == pytest.approx(60.0)
    assert stock_share["Scale"] == "%"
    assert stock_share["Units"] == "Share"

    assert efficiency["Value"] == pytest.approx(7.5)
    assert efficiency["Scale"] == ""
    assert efficiency["Units"] == "MJ/100 km"


def test_reconciled_reimport_derives_stock_share_from_t9():
    source = pd.DataFrame([
        {
            "Economy": "20USA",
            "Scenario": "Current Accounts",
            "Branch Path": "Demand\\Passenger road\\LPVs",
            "Variable": "Stock Share",
            "Year": 2022,
            "Value": 50.0,
            "Scale": "%",
            "Units": "Share",
        },
        {
            "Economy": "20USA",
            "Scenario": "Current Accounts",
            "Branch Path": "Demand\\Passenger road\\LPVs\\ICE",
            "Variable": "Stock Share",
            "Year": 2022,
            "Value": 50.0,
            "Scale": "%",
            "Units": "Share",
        },
    ])
    t11 = pd.DataFrame(columns=["leap_branch_path", "variable", "scenario", "year", "value"])
    t9 = pd.DataFrame([
        {
            "economy": "20_USA",
            "scenario": "Target",
            "transport_type": "passenger",
            "vehicle_type": "LPVs",
            "drive_type": "ICE",
            "size": None,
            "leap_branch_path": "Demand\\Passenger road\\LPVs\\ICE\\Motor gasoline",
            "adjusted_stock": 80.0,
            "adjusted_mileage_km_per_year": 10_000.0,
            "adjusted_efficiency_km_per_gj": 1_000.0,
            "final_branch_fuel_pj": 0.8,
        },
        {
            "economy": "20_USA",
            "scenario": "Target",
            "transport_type": "passenger",
            "vehicle_type": "Motorcycles",
            "drive_type": "ICE",
            "size": None,
            "leap_branch_path": "Demand\\Passenger road\\Motorcycles\\ICE\\Motor gasoline",
            "adjusted_stock": 20.0,
            "adjusted_mileage_km_per_year": 10_000.0,
            "adjusted_efficiency_km_per_gj": 1_000.0,
            "final_branch_fuel_pj": 0.2,
        },
    ])

    out = build_reconciled_module1_reimport(
        source,
        t11,
        base_year=2022,
        reconciliation_scalars=t9,
    )

    vehicle_share = out[out["Branch Path"] == "Demand\\Passenger road\\LPVs"].iloc[0]
    tech_share = out[out["Branch Path"] == "Demand\\Passenger road\\LPVs\\ICE"].iloc[0]
    assert vehicle_share["Value"] == pytest.approx(80.0)
    assert tech_share["Value"] == pytest.approx(100.0)


def test_reconciled_reimport_loads_with_module1_adapter(tmp_path: Path):
    out = build_reconciled_module1_reimport(_source_rows(), _t11_rows(), base_year=2022)
    package_dir = tmp_path / "vtest" / "20USA"
    package_dir.mkdir(parents=True)
    out.to_csv(package_dir / "road_module1_values_20USA.csv", index=False)

    loaded = load_module1_for_economy(tmp_path, economy="20_USA", version="vtest")
    raw = loaded["raw_leap_df"]
    parsed = parse_leap_format_inputs(raw, base_year=2022)

    stock_raw = raw[raw["Variable"] == "Stock"].iloc[0]
    assert stock_raw["Scale"] == "Millions"
    assert stock_raw["2022"] == pytest.approx(2.5)

    stock_parsed = parsed[parsed["variable"] == "stock"].iloc[0]
    mileage_parsed = parsed[parsed["variable"] == "mileage"].iloc[0]
    stock_share_parsed = parsed[parsed["variable"] == "stock_share"].iloc[0]
    efficiency_parsed = parsed[parsed["variable"] == "efficiency"].iloc[0]

    assert stock_parsed["value"] == pytest.approx(2_500_000.0)
    assert stock_share_parsed["value"] == pytest.approx(60.0)
    assert mileage_parsed["value"] == pytest.approx(12_500.0)
    assert efficiency_parsed["value"] == pytest.approx(10_000.0 / 7.5)


#%%
