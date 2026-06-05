from __future__ import annotations

import pandas as pd

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
    assert leap_sheet["BranchID"].iloc[0] == 1
    assert "Data(2022, 100, 2023, 110)" in leap_sheet["Expression"].iloc[0]
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
