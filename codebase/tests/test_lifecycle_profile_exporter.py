import zipfile

import pandas as pd
import pytest

from adapters.lifecycle_profile_exporter import export_lifecycle_profiles_from_t6v


def _read_lifecycle_workbook(path):
    raw = pd.read_excel(path, sheet_name="Lifecycle Profiles", header=None)
    header_rows = raw.index[raw[0].eq("Year")].tolist()
    assert header_rows == [3]
    data = raw.iloc[4:].dropna(how="all")
    return {
        "area": raw.iloc[0, 1],
        "profile": raw.iloc[1, 1],
        "years": data[0].astype(int).tolist(),
        "values": data[1].astype(float).tolist(),
    }


def test_export_lifecycle_profiles_structure_against_small_fixture(tmp_path):
    t6v = pd.DataFrame(
        [
            {"transport_type": "passenger", "vehicle_type": "LPVs", "age": 0, "vintage_share": 0.50, "survival_probability": 0.90},
            {"transport_type": "passenger", "vehicle_type": "LPVs", "age": 1, "vintage_share": 0.30, "survival_probability": 0.80},
            {"transport_type": "passenger", "vehicle_type": "LPVs", "age": 2, "vintage_share": 0.20, "survival_probability": 0.00},
            {"transport_type": "freight", "vehicle_type": "Trucks", "age": 0, "vintage_share": 0.60, "survival_probability": 0.75},
            {"transport_type": "freight", "vehicle_type": "Trucks", "age": 1, "vintage_share": 0.40, "survival_probability": 0.00},
        ]
    )

    result = export_lifecycle_profiles_from_t6v(
        t6v,
        tmp_path,
        economy="99_TST",
        area_name="Test transport",
    )

    manifest = result["manifest"]
    assert len(manifest) == 4
    assert set(manifest["profile_type"]) == {"vehicle_survival", "vintage"}
    assert set(manifest["transport_type"]) == {"passenger", "freight"}
    assert result["manifest_path"].exists()
    assert result["zip_path"].exists()

    survival = _read_lifecycle_workbook(tmp_path / "99_TST_passenger_vehicle_survival.xlsx")
    assert survival["area"] == "Test transport"
    assert survival["profile"] == "99_TST passenger Vehicle Survival"
    assert survival["years"] == [0, 1, 2]
    assert survival["values"] == pytest.approx([100.0, 90.0, 72.0])

    vintage = _read_lifecycle_workbook(tmp_path / "99_TST_passenger_vintage.xlsx")
    assert vintage["profile"] == "99_TST passenger Vintage Profile"
    assert vintage["years"] == [0, 1, 2]
    assert sum(vintage["values"]) == pytest.approx(100.0)
    assert vintage["values"] == pytest.approx([50.0, 30.0, 20.0])

    with zipfile.ZipFile(result["zip_path"]) as zf:
        names = set(zf.namelist())
    assert "lifecycle_profile_manifest.csv" in names
    assert "99_TST_passenger_vehicle_survival.xlsx" in names
    assert "99_TST_passenger_vintage.xlsx" in names
    assert "99_TST_freight_vehicle_survival.xlsx" in names
    assert "99_TST_freight_vintage.xlsx" in names


def test_export_lifecycle_profiles_rejects_non_contiguous_ages(tmp_path):
    t6v = pd.DataFrame(
        [
            {"transport_type": "passenger", "vehicle_type": "LPVs", "age": 0, "vintage_share": 0.70, "survival_probability": 0.90},
            {"transport_type": "passenger", "vehicle_type": "LPVs", "age": 2, "vintage_share": 0.30, "survival_probability": 0.00},
        ]
    )

    with pytest.raises(ValueError, match="contiguous"):
        export_lifecycle_profiles_from_t6v(t6v, tmp_path, economy="99_TST")
