from pathlib import Path

import pandas as pd
import yaml
import pytest

from modules.module2_base_year import _add_leap_branch_paths, _build_branch_skeleton
from modules.module1_inputs import _load_defaults
from modules.module6_reconciliation_and_leap_handoff import (
    build_leap_ready_table,
    calculate_device_shares,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "codebase" / "config"


def test_model_defaults_file_is_kept_as_guidance_only():
    assert (CONFIG_DIR / "model_defaults.yaml").exists()


def test_legacy_load_defaults_fails_loudly(monkeypatch):
    monkeypatch.delenv("ROAD_MODEL_ENABLE_LEGACY_MODEL_DEFAULTS", raising=False)
    with pytest.raises(RuntimeError, match="guidance-only"):
        _load_defaults(CONFIG_DIR)


def test_legacy_load_defaults_env_var_does_not_reactivate(monkeypatch):
    monkeypatch.setenv("ROAD_MODEL_ENABLE_LEGACY_MODEL_DEFAULTS", "1")
    with pytest.raises(RuntimeError, match="guidance-only"):
        _load_defaults(CONFIG_DIR)


def test_legacy_model_defaults_match_current_branch_matrix():
    with open(CONFIG_DIR / "model_defaults.yaml", encoding="utf-8") as f:
        defaults_cfg = yaml.safe_load(f)

    expected_drives = {
        "LPVs": ["ICE", "HEV", "EREV", "PHEV", "BEV", "FCEV"],
        "Motorcycles": ["ICE", "BEV", "FCEV"],
        "Buses": ["ICE", "BEV", "FCEV"],
        "LCVs": ["ICE", "PHEV", "BEV", "FCEV"],
        "Trucks": ["ICE", "PHEV", "BEV", "FCEV"],
    }
    expected_weights = {
        "LPVs": 1.0,
        "Motorcycles": 0.8,
        "Buses": 20.0,
        "Trucks": 5.0,
        "LCVs": 1.5,
    }

    for section_name in ["default_mileage_km_per_year", "default_efficiency_km_per_gj"]:
        section = defaults_cfg[section_name]
        assert list(section) == list(expected_drives)
        for vehicle_type, drives in expected_drives.items():
            assert list(section[vehicle_type]) == drives

    assert defaults_cfg["vehicle_equivalent_weights"] == expected_weights
    assert defaults_cfg["vehicle_equivalent_weight_bounds"] == {
        "Motorcycles": {"lower": 0.05, "upper": 0.80},
        "Buses": {"lower": 8.0, "upper": 30.0},
    }


def test_vehicle_branch_matrix_matches_current_scope():
    with open(CONFIG_DIR / "vehicle_mappings.yaml", encoding="utf-8") as f:
        vehicle_cfg = yaml.safe_load(f)

    expected_drives = {
        "LPVs": ["ICE", "HEV", "EREV", "PHEV", "BEV", "FCEV"],
        "Motorcycles": ["ICE", "BEV", "FCEV"],
        "Buses": ["ICE", "BEV", "FCEV"],
        "LCVs": ["ICE", "PHEV", "BEV", "FCEV"],
        "Trucks": ["ICE", "PHEV", "BEV", "FCEV"],
    }
    expected_sizes = {
        "LPVs": ["small", "medium", "large"],
        "Motorcycles": [None],
        "Buses": [None],
        "LCVs": [None],
        "Trucks": ["medium", "heavy"],
    }

    assert vehicle_cfg["valid_drive_types_by_vehicle_type"] == expected_drives
    assert vehicle_cfg["vehicle_type_sizes"] == expected_sizes


def test_branch_skeleton_uses_current_vehicle_scope():
    with open(CONFIG_DIR / "vehicle_mappings.yaml", encoding="utf-8") as f:
        vehicle_cfg = yaml.safe_load(f)
    with open(CONFIG_DIR / "fuel_mappings.yaml", encoding="utf-8") as f:
        fuel_cfg = yaml.safe_load(f)

    skeleton = _build_branch_skeleton(vehicle_cfg, fuel_cfg)
    branch_scope = skeleton[["vehicle_type", "drive_type", "size"]].drop_duplicates()

    actual = {}
    for vehicle_type, group in branch_scope.groupby("vehicle_type"):
        sizes = []
        for value in group["size"].unique():
            sizes.append(None if value != value else value)
        actual[vehicle_type] = {
            "drives": sorted(group["drive_type"].dropna().unique()),
            "sizes": sorted(sizes, key=lambda value: "" if value is None else str(value)),
        }

    assert actual["LPVs"] == {
        "drives": ["BEV", "EREV", "FCEV", "HEV", "ICE", "PHEV"],
        "sizes": ["large", "medium", "small"],
    }
    assert actual["Motorcycles"] == {"drives": ["BEV", "FCEV", "ICE"], "sizes": [None]}
    assert actual["Buses"] == {"drives": ["BEV", "FCEV", "ICE"], "sizes": [None]}
    assert actual["LCVs"] == {"drives": ["BEV", "FCEV", "ICE", "PHEV"], "sizes": [None]}
    assert actual["Trucks"] == {
        "drives": ["BEV", "FCEV", "ICE", "PHEV"],
        "sizes": ["heavy", "medium"],
    }


def test_truck_phev_scope_reaches_t11_with_diesel_family_fuels():
    """The production scope carries sized truck PHEV branches into T11."""
    with open(CONFIG_DIR / "vehicle_mappings.yaml", encoding="utf-8") as f:
        vehicle_cfg = yaml.safe_load(f)
    with open(CONFIG_DIR / "fuel_mappings.yaml", encoding="utf-8") as f:
        fuel_cfg = yaml.safe_load(f)

    skeleton = _add_leap_branch_paths(_build_branch_skeleton(vehicle_cfg, fuel_cfg))
    truck_phev = skeleton[
        skeleton["vehicle_type"].eq("Trucks")
        & skeleton["drive_type"].eq("PHEV")
    ]

    assert set(zip(truck_phev["size"], truck_phev["fuel"])) == {
        (size, fuel)
        for size in ("medium", "heavy")
        for fuel in ("Electricity", "Gas and diesel oil", "Biodiesel")
    }

    # Use one size and the two primary energy streams to prove that the generic
    # Module 6/T11 machinery accepts a sized truck PHEV technology branch.
    medium_paths = truck_phev[
        truck_phev["size"].eq("medium")
        & truck_phev["fuel"].isin(["Electricity", "Gas and diesel oil"])
    ].set_index("fuel")["leap_branch_path"]
    t9 = pd.DataFrame([
        {
            "economy": "12_NZ",
            "scenario": "Target",
            "base_year": 2022,
            "transport_type": "freight",
            "vehicle_type": "Trucks",
            "drive_type": "PHEV",
            "size": "medium",
            "fuel": "Electricity",
            "leap_branch_path": medium_paths["Electricity"],
            "adjusted_stock": 100.0,
            "adjusted_mileage_km_per_year": 8_000.0,
            "adjusted_efficiency_km_per_gj": 4_000.0,
            "final_branch_fuel_pj": 0.00008,
        },
        {
            "economy": "12_NZ",
            "scenario": "Target",
            "base_year": 2022,
            "transport_type": "freight",
            "vehicle_type": "Trucks",
            "drive_type": "PHEV",
            "size": "medium",
            "fuel": "Gas and diesel oil",
            "leap_branch_path": medium_paths["Gas and diesel oil"],
            "adjusted_stock": 100.0,
            "adjusted_mileage_km_per_year": 12_000.0,
            "adjusted_efficiency_km_per_gj": 2_000.0,
            "final_branch_fuel_pj": 0.00036,
        },
    ])
    device_shares = calculate_device_shares(t9)
    t11 = build_leap_ready_table(
        reconciliation_scalars=t9,
        device_shares=device_shares,
        sales_turnover=pd.DataFrame(),
        sales_shares=pd.DataFrame(),
        projection_years=[2022],
    )

    device_rows = t11[t11["variable"].eq("Device Share")].set_index("leap_branch_path")
    assert device_rows.loc[medium_paths["Electricity"], "value"] == pytest.approx(40.0)
    assert device_rows.loc[medium_paths["Gas and diesel oil"], "value"] == pytest.approx(60.0)
    assert (
        t11["leap_branch_path"]
        == "Demand\\Freight road\\Trucks\\PHEV medium"
    ).any()
