from __future__ import annotations

import pandas as pd
import pytest

from adapters.leap_import_writer import build_leap_import_tables, write_leap_import_workbook


def test_build_leap_import_tables_merges_ids_and_returns_warnings():
    t11 = pd.DataFrame([
        {
            "leap_branch_path": "Demand\\Freight road",
            "variable": "Sales",
            "scenario": "Target",
            "year": 2022,
            "value": 100.0,
            "unit": "Device",
        },
        {
            "leap_branch_path": "Demand\\Freight road",
            "variable": "Sales",
            "scenario": "Target",
            "year": 2023,
            "value": 110.0,
            "unit": "Device",
        },
        {
            "leap_branch_path": "Demand\\Freight road\\LCVs\\BEV\\Electricity",
            "variable": "Mileage",
            "scenario": "Target",
            "year": 2022,
            "value": 1.0,
            "unit": "Kilometer",
        },
        {
            "leap_branch_path": "Demand\\Freight road\\LCVs\\BEV",
            "variable": "Fuel Economy",
            "scenario": "Target",
            "year": 2022,
            "value": 50.0,
            "unit": "MJ/100 km",
        },
    ])
    reference = pd.DataFrame([
        {
            "BranchID": 1,
            "VariableID": 2,
            "ScenarioID": 3,
            "RegionID": 4,
            "Branch Path": "Demand\\Freight road",
            "Variable": "Sales",
            "Scenario": "Target",
            "Region": "United States of America",
            "Scale": "",
            "Units": "Device",
            "Per...": "",
        },
        {
            "BranchID": 5,
            "VariableID": 6,
            "ScenarioID": 3,
            "RegionID": 4,
            "Branch Path": "Demand\\Freight road",
            "Variable": "Stock",
            "Scenario": "Target",
            "Region": "United States of America",
            "Scale": "",
            "Units": "Device",
            "Per...": "",
        },
        {
            "BranchID": 7,
            "VariableID": 8,
            "ScenarioID": 3,
            "RegionID": 4,
            "Branch Path": "Demand\\Freight road\\LCVs",
            "Variable": "Sales Share",
            "Scenario": "Target",
            "Region": "United States of America",
            "Scale": "%",
            "Units": "Share",
            "Per...": "",
        },
        {
            "BranchID": 7,
            "VariableID": 8,
            "ScenarioID": 3,
            "RegionID": 4,
            "Branch Path": "Demand\\Freight road\\LCVs\\EREV\\Electricity",
            "Variable": "Fuel Economy",
            "Scenario": "Target",
            "Region": "United States of America",
            "Scale": "",
            "Units": "MJ/100 km",
            "Per...": "",
        },
        {
            "BranchID": 9,
            "VariableID": 10,
            "ScenarioID": 3,
            "RegionID": 4,
            "Branch Path": "Demand\\Freight road\\LCVs\\BEV\\Electricity",
            "Variable": "Average Mileage",
            "Scenario": "Target",
            "Region": "United States of America",
            "Scale": "",
            "Units": "Kilometer",
            "Per...": "",
        },
        {
            "BranchID": 11,
            "VariableID": 12,
            "ScenarioID": 3,
            "RegionID": 4,
            "Branch Path": "Demand\\Freight road\\LCVs\\BEV\\Electricity",
            "Variable": "Fuel Economy",
            "Scenario": "Target",
            "Region": "United States of America",
            "Scale": "",
            "Units": "MJ/100 km",
            "Per...": "",
        },
    ])

    leap_sheet, viewing_sheet, warnings, not_needed = build_leap_import_tables(
        t11,
        reference,
        economy_long_name="United States of America",
    )

    assert list(leap_sheet.columns[:12]) == [
        "BranchID",
        "VariableID",
        "ScenarioID",
        "RegionID",
        "Branch Path",
        "Variable",
        "Scenario",
        "Region",
        "Scale",
        "Units",
        "Per...",
        "Expression",
    ]
    assert leap_sheet.columns[12] == ""
    assert list(leap_sheet.columns[13:]) == [
        "Level 1",
        "Level 2",
        "Level 3",
        "Level 4",
        "Level 5",
        "Level 6",
        "Level 7",
        "Level 8...",
    ]
    assert leap_sheet["BranchID"].iloc[0] == 1
    assert leap_sheet["Level 1"].iloc[0] == "Demand"
    assert leap_sheet["Level 2"].iloc[0] == "Freight road"
    assert "Data(2022, 100, 2023, 110)" in leap_sheet["Expression"].iloc[0]
    assert "Level 1" in viewing_sheet.columns
    assert "Level 8..." in viewing_sheet.columns
    assert 2022 in viewing_sheet.columns
    assert not viewing_sheet.empty
    assert {warning["type"] for warning in warnings} >= {
        "model_row_not_in_leap_reference",
        "region_id_from_reference",
    }
    warned_pairs = {(warning.get("Branch Path"), warning.get("Variable")) for warning in warnings}
    assert ("Demand\\Freight road\\LCVs\\EREV\\Electricity", "Fuel Economy") not in warned_pairs
    assert ("Demand\\Freight road\\LCVs\\BEV\\Electricity", "Average Mileage") not in warned_pairs
    assert ("Demand\\Freight road\\LCVs\\BEV\\Electricity", "Fuel Economy") not in warned_pairs
    assert not not_needed.empty
    assert "outside_active_scope" in set(not_needed["reason"])
    assert (
        (leap_sheet["Branch Path"] == "Demand\\Freight road\\LCVs\\BEV\\Electricity")
        & (leap_sheet["Variable"] == "Fuel Economy")
    ).any()


def test_build_leap_import_tables_applies_scale_to_expression_and_viewing_values():
    t11 = pd.DataFrame([
        {
            "leap_branch_path": "Demand\\Passenger road",
            "variable": "Stock",
            "scenario": "Target",
            "year": 2022,
            "value": 2_500_000.0,
            "unit": "Device",
            "scale": "Millions",
        },
        {
            "leap_branch_path": "Demand\\Passenger road",
            "variable": "Stock",
            "scenario": "Target",
            "year": 2023,
            "value": 3_000_000.0,
            "unit": "Device",
            "scale": "Millions",
        },
    ])
    reference = pd.DataFrame([
        {
            "BranchID": 1,
            "VariableID": 2,
            "ScenarioID": 3,
            "RegionID": 4,
            "Branch Path": "Demand\\Passenger road",
            "Variable": "Stock",
            "Scenario": "Target",
            "Region": "United States of America",
            "Scale": "",
            "Units": "Device",
            "Per...": "",
        }
    ])

    leap_sheet, viewing_sheet, warnings, not_needed = build_leap_import_tables(
        t11,
        reference,
        economy_long_name="United States of America",
        region_id=4,
    )

    assert leap_sheet.loc[0, "Scale"] == "Millions"
    assert leap_sheet.loc[0, "Expression"] == "Data(2022, 2.5, 2023, 3)"
    assert viewing_sheet.loc[0, 2022] == pytest.approx(2.5)
    assert viewing_sheet.loc[0, 2023] == pytest.approx(3.0)


def test_build_leap_import_tables_can_export_raw_values_instead_of_scaled_values():
    t11 = pd.DataFrame([
        {
            "leap_branch_path": "Demand\\Passenger road",
            "variable": "Stock",
            "scenario": "Target",
            "year": 2022,
            "value": 2_500_000.0,
            "unit": "Device",
            "scale": "Millions",
        },
        {
            "leap_branch_path": "Demand\\Passenger road\\LPVs",
            "variable": "Sales Share",
            "scenario": "Target",
            "year": 2022,
            "value": 12.5,
            "unit": "Share",
            "scale": "%",
        },
    ])
    reference = pd.DataFrame([
        {
            "BranchID": 1,
            "VariableID": 2,
            "ScenarioID": 3,
            "RegionID": 4,
            "Branch Path": "Demand\\Passenger road",
            "Variable": "Stock",
            "Scenario": "Target",
            "Region": "United States of America",
            "Scale": "",
            "Units": "Device",
            "Per...": "",
        },
        {
            "BranchID": 5,
            "VariableID": 6,
            "ScenarioID": 3,
            "RegionID": 4,
            "Branch Path": "Demand\\Passenger road\\LPVs",
            "Variable": "Sales Share",
            "Scenario": "Target",
            "Region": "United States of America",
            "Scale": "%",
            "Units": "Share",
            "Per...": "",
        },
    ])

    leap_sheet, viewing_sheet, warnings, not_needed = build_leap_import_tables(
        t11,
        reference,
        economy_long_name="United States of America",
        region_id=4,
        export_values_in_raw_units=True,
    )

    stock_row = leap_sheet[leap_sheet["Variable"].eq("Stock")].iloc[0]
    share_row = leap_sheet[leap_sheet["Variable"].eq("Sales Share")].iloc[0]
    assert stock_row["Scale"] == ""
    assert float(stock_row["Expression"]) == pytest.approx(2_500_000.0)
    assert share_row["Scale"] == "%"
    assert share_row["Expression"] == "12.5"
    stock_view = viewing_sheet[viewing_sheet["Variable"].eq("Stock")].iloc[0]
    assert stock_view[2022] == pytest.approx(2_500_000.0)


def test_build_leap_import_tables_normalises_device_shares_after_reference_match():
    t11 = pd.DataFrame([
        {
            "leap_branch_path": "Demand\\Passenger road\\Motorcycles\\ICE\\Motor gasoline",
            "variable": "Device Share",
            "scenario": "Target",
            "year": 2022,
            "value": 98.0,
            "unit": "Share",
            "scale": "%",
        },
        {
            "leap_branch_path": "Demand\\Passenger road\\Motorcycles\\ICE\\Biogasoline",
            "variable": "Device Share",
            "scenario": "Target",
            "year": 2022,
            "value": 1.0,
            "unit": "Share",
            "scale": "%",
        },
        {
            "leap_branch_path": "Demand\\Passenger road\\Motorcycles\\ICE\\LPG",
            "variable": "Device Share",
            "scenario": "Target",
            "year": 2022,
            "value": 1.0,
            "unit": "Share",
            "scale": "%",
        },
    ])
    reference = pd.DataFrame([
        {
            "BranchID": branch_id,
            "VariableID": 2,
            "ScenarioID": 3,
            "RegionID": 4,
            "Branch Path": branch_path,
            "Variable": "Device Share",
            "Scenario": "Target",
            "Region": "Australia",
            "Scale": "%",
            "Units": "Share",
            "Per...": "",
        }
        for branch_id, branch_path in [
            (1, "Demand\\Passenger road\\Motorcycles\\ICE\\Motor gasoline"),
            (2, "Demand\\Passenger road\\Motorcycles\\ICE\\Biogasoline"),
        ]
    ])

    leap_sheet, viewing_sheet, warnings, not_needed = build_leap_import_tables(
        t11,
        reference,
        economy_long_name="Australia",
        region_id=4,
    )

    values = viewing_sheet.set_index("Branch Path")[2022]
    assert values["Demand\\Passenger road\\Motorcycles\\ICE\\Motor gasoline"] == pytest.approx(98.9898989899)
    assert values["Demand\\Passenger road\\Motorcycles\\ICE\\Biogasoline"] == pytest.approx(1.0101010101)
    assert values.sum() == pytest.approx(100.0)
    expressions = leap_sheet.set_index("Branch Path")["Expression"]
    assert float(expressions["Demand\\Passenger road\\Motorcycles\\ICE\\Motor gasoline"]) == pytest.approx(98.9898989899)


def test_write_leap_import_workbook_writes_row_coverage_diagnostics(tmp_path):
    t11 = pd.DataFrame([
        {
            "leap_branch_path": "Demand\\Freight road",
            "variable": "Sales",
            "scenario": "Target",
            "year": 2022,
            "value": 100.0,
            "unit": "Device",
        },
        {
            "leap_branch_path": "Demand\\Freight road\\Bad branch",
            "variable": "Sales",
            "scenario": "Target",
            "year": 2022,
            "value": 1.0,
            "unit": "Device",
        },
    ])
    reference_path = tmp_path / "reference.xlsx"
    reference = pd.DataFrame([
        {
            "BranchID": 1,
            "VariableID": 2,
            "ScenarioID": 3,
            "RegionID": 4,
            "Branch Path": "Demand\\Freight road",
            "Variable": "Sales",
            "Scenario": "Target",
            "Region": "United States of America",
            "Scale": "",
            "Units": "Device",
            "Per...": "",
        },
        {
            "BranchID": 5,
            "VariableID": 6,
            "ScenarioID": 3,
            "RegionID": 4,
            "Branch Path": "Demand\\Freight road",
            "Variable": "Stock",
            "Scenario": "Target",
            "Region": "United States of America",
            "Scale": "",
            "Units": "Device",
            "Per...": "",
        },
        {
            "BranchID": 7,
            "VariableID": 8,
            "ScenarioID": 3,
            "RegionID": 4,
            "Branch Path": "Demand\\Freight road\\LCVs",
            "Variable": "Sales Share",
            "Scenario": "Target",
            "Region": "United States of America",
            "Scale": "%",
            "Units": "Share",
            "Per...": "",
        },
    ])
    with pd.ExcelWriter(reference_path, engine="openpyxl") as writer:
        reference.to_excel(writer, sheet_name="LEAP", index=False, startrow=2)

    diagnostics_path = tmp_path / "coverage.csv"
    write_leap_import_workbook(
        t11,
        tmp_path / "import.xlsx",
        reference_path=reference_path,
        economy_long_name="United States of America",
        coverage_diagnostics_path=diagnostics_path,
        manual_missing_rows_path=None,
    )

    diagnostics = pd.read_csv(diagnostics_path)
    assert {"missing_required", "not_needed", "notice"}.issubset(set(diagnostics["diagnostic_status"]))
    assert "Demand\\Freight road\\Bad branch" in set(diagnostics["Branch Path"])
