from pathlib import Path

import yaml
import pytest

from modules.module2_base_year import _build_branch_skeleton
from modules.module1_inputs import _load_defaults


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
        "Trucks": ["ICE", "BEV", "FCEV"],
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
        "Trucks": ["ICE", "BEV", "FCEV"],
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
    assert actual["Trucks"] == {"drives": ["BEV", "FCEV", "ICE"], "sizes": ["heavy", "medium"]}
