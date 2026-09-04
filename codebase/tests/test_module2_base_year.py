from __future__ import annotations

import pathlib
import sys

import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from modules.module2_base_year import run_module2


def _write_leap_reference(path: pathlib.Path, branch_paths: list[str], scenario: str = "Target") -> None:
    rows = []
    for branch_id, branch_path in enumerate(branch_paths, start=1):
        rows.append(
            {
                "BranchID": branch_id,
                "VariableID": 1,
                "ScenarioID": 3,
                "RegionID": 1,
                "Branch Path": branch_path,
                "Variable": "Stock",
                "Scenario": scenario,
                "Region": "Test economy",
                "Scale": "",
                "Units": "Vehicles",
                "Per...": "",
            }
        )
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name="LEAP", startrow=2, index=False)


def test_vehicle_type_mileage_broadcasts_to_fuel_level_branches():
    inputs = pd.DataFrame([
        {
            "economy": "20_USA",
            "scenario": "Target",
            "year": 2022,
            "transport_type": "passenger",
            "vehicle_type": "LPVs",
            "drive_type": None,
            "variable": "mileage",
            "value": 12_345.0,
            "source_flag": "test_vehicle_level",
        },
        {
            "economy": "20_USA",
            "scenario": "Target",
            "year": 2022,
            "transport_type": "freight",
            "vehicle_type": "Trucks",
            "drive_type": None,
            "variable": "mileage",
            "value": 67_890.0,
            "source_flag": "test_vehicle_level",
        },
    ])

    t4 = run_module2(
        inputs,
        config_dir=pathlib.Path(__file__).parent.parent / "config",
        economies=["20_USA"],
        scenarios=["Target"],
        base_year=2022,
        diagnostics_dir=None,
    )

    lpv = t4[t4["vehicle_type"].eq("LPVs")]
    trucks = t4[t4["vehicle_type"].eq("Trucks")]
    assert lpv["mileage_km_per_year"].notna().all()
    assert trucks["mileage_km_per_year"].notna().all()
    assert set(lpv["mileage_km_per_year"]) == {12_345.0}
    assert set(trucks["mileage_km_per_year"]) == {67_890.0}
    assert set(lpv["mileage_granularity"]) == {"vehicle_type_level_broadcast"}
    assert set(trucks["mileage_granularity"]) == {"vehicle_type_level_broadcast"}


def test_fuel_level_mileage_is_not_replaced_by_first_fuel():
    inputs = pd.DataFrame([
        {
            "economy": "20_USA",
            "scenario": "Target",
            "year": 2022,
            "transport_type": "freight",
            "vehicle_type": "LCVs",
            "drive_type": None,
            "variable": "stock",
            "value": 100_000.0,
            "source_flag": "test_vehicle_level",
        },
        {
            "economy": "20_USA",
            "scenario": "Target",
            "year": 2022,
            "transport_type": "freight",
            "vehicle_type": "LCVs",
            "drive_type": "ICE",
            "fuel": "Biodiesel",
            "variable": "mileage",
            "value": 10_000.0,
            "source_flag": "test_fuel_level",
        },
        {
            "economy": "20_USA",
            "scenario": "Target",
            "year": 2022,
            "transport_type": "freight",
            "vehicle_type": "LCVs",
            "drive_type": "ICE",
            "fuel": "Motor gasoline",
            "variable": "mileage",
            "value": 20_000.0,
            "source_flag": "test_fuel_level",
        },
    ])

    t4 = run_module2(
        inputs,
        config_dir=pathlib.Path(__file__).parent.parent / "config",
        economies=["20_USA"],
        scenarios=["Target"],
        base_year=2022,
        diagnostics_dir=None,
    )

    lcv = t4[(t4["vehicle_type"] == "LCVs") & (t4["drive_type"] == "ICE")]
    assert lcv.loc[lcv["fuel"] == "Biodiesel", "mileage_km_per_year"].iloc[0] == pytest.approx(10_000.0)
    assert lcv.loc[lcv["fuel"] == "Motor gasoline", "mileage_km_per_year"].iloc[0] == pytest.approx(20_000.0)


def test_missing_mileage_is_not_filled_from_model_defaults():
    inputs = pd.DataFrame([
        {
            "economy": "20_USA",
            "scenario": "Target",
            "year": 2022,
            "transport_type": "passenger",
            "vehicle_type": "Buses",
            "drive_type": None,
            "variable": "mileage",
            "value": 45_000.0,
            "source_flag": "provided",
        },
    ])

    t4 = run_module2(
        inputs,
        config_dir=pathlib.Path(__file__).parent.parent / "config",
        economies=["20_USA"],
        scenarios=["Target"],
        base_year=2022,
        diagnostics_dir=None,
    )

    lpv_ice = t4[t4["vehicle_type"].eq("LPVs") & t4["drive_type"].eq("ICE")]
    truck_ice = t4[t4["vehicle_type"].eq("Trucks") & t4["drive_type"].eq("ICE")]
    assert lpv_ice["mileage_km_per_year"].isna().all()
    assert truck_ice["mileage_km_per_year"].isna().all()
    assert set(lpv_ice["mileage_source_flag"]) == {"missing"}
    assert set(truck_ice["mileage_granularity"]) == {"branch_level"}


def test_leap_reference_branch_presence_filters_configured_fuel_leaves(tmp_path: pathlib.Path):
    allowed_paths = [
        r"Demand\Passenger road\LPVs\ICE small\Motor gasoline",
        r"Demand\Passenger road\LPVs\ICE medium\LPG",
        r"Demand\Passenger road\Motorcycles\ICE\Motor gasoline",
    ]
    reference_path = tmp_path / "leap_reference.xlsx"
    _write_leap_reference(reference_path, allowed_paths)
    inputs = pd.DataFrame(
        [
            {
                "economy": "20_USA",
                "scenario": "Target",
                "year": 2022,
                "transport_type": "passenger",
                "vehicle_type": "LPVs",
                "drive_type": None,
                "variable": "mileage",
                "value": 12_345.0,
                "source_flag": "test_vehicle_level",
            }
        ]
    )

    t4 = run_module2(
        inputs,
        config_dir=pathlib.Path(__file__).parent.parent / "config",
        economies=["20_USA"],
        scenarios=["Target"],
        base_year=2022,
        leap_reference_path=reference_path,
        diagnostics_dir=None,
    )

    assert set(t4["leap_branch_path"]) == set(allowed_paths)
    assert r"Demand\Passenger road\LPVs\ICE small\LPG" not in set(t4["leap_branch_path"])
    assert r"Demand\Passenger road\Motorcycles\ICE\Natural gas" not in set(t4["leap_branch_path"])


def test_leap_reference_requires_requested_scenario(tmp_path: pathlib.Path):
    reference_path = tmp_path / "leap_reference.xlsx"
    _write_leap_reference(
        reference_path,
        [r"Demand\Passenger road\LPVs\ICE small\Motor gasoline"],
        scenario="Reference",
    )
    inputs = pd.DataFrame(
        columns=[
            "economy",
            "scenario",
            "year",
            "transport_type",
            "vehicle_type",
            "drive_type",
            "variable",
            "value",
            "source_flag",
        ]
    )

    with pytest.raises(ValueError, match="requested scenario.*Target"):
        run_module2(
            inputs,
            config_dir=pathlib.Path(__file__).parent.parent / "config",
            economies=["20_USA"],
            scenarios=["Target"],
            base_year=2022,
            leap_reference_path=reference_path,
            diagnostics_dir=None,
        )
