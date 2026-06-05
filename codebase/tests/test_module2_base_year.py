from __future__ import annotations

import pathlib
import sys

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from modules.module2_base_year import run_module2


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
