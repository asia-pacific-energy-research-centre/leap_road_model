import pandas as pd
import pytest
from openpyxl import load_workbook

from adapters.lifecycle_profile_exporter import (
    _normalise_excel_profile_name,
    export_lifecycle_profiles_from_t6v,
)


def _read_profile_sheet(xlsx_path, sheet_name):
    raw = pd.read_excel(xlsx_path, sheet_name=sheet_name, header=None)
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
    assert result["xlsx_path"].exists()

    xlsx_path = result["xlsx_path"]

    survival = _read_profile_sheet(xlsx_path, "Passenger_vehicle_survival")
    assert survival["area"] == "Test transport"
    assert survival["profile"] == "99_TST passenger Vehicle Survival"
    assert survival["years"] == [0, 1, 2]
    assert survival["values"] == pytest.approx([100.0, 90.0, 72.0])

    vintage = _read_profile_sheet(xlsx_path, "Passenger_vintage_profile")
    assert vintage["profile"] == "99_TST passenger Vintage Profile"
    assert vintage["years"] == [0, 1, 2, 3]
    assert sum(vintage["values"]) == pytest.approx(100.0)
    assert vintage["values"] == pytest.approx([0.0, 50.0, 30.0, 20.0])

    xl = pd.ExcelFile(xlsx_path)
    assert set(xl.sheet_names) == {
        "Passenger_vehicle_survival",
        "Passenger_vintage_profile",
        "Freight_vehicle_survival",
        "Freight_vintage_profile",
    }

    workbook = load_workbook(xlsx_path, read_only=False, data_only=False)
    expected_named_ranges = {
        "Passenger_vehicle_survival": "'Passenger_vehicle_survival'!$B$5:$B$7",
        "Passenger_vintage_profile": "'Passenger_vintage_profile'!$B$5:$B$8",
        "Freight_vehicle_survival": "'Freight_vehicle_survival'!$B$5:$B$6",
        "Freight_vintage_profile": "'Freight_vintage_profile'!$B$5:$B$7",
    }
    assert set(workbook.defined_names) == set(expected_named_ranges)
    for range_name, cell_reference in expected_named_ranges.items():
        assert workbook.defined_names[range_name].attr_text == cell_reference

    assert set(manifest["named_range"]) == set(expected_named_ranges)
    assert set(manifest["named_range_cells"]) == {"B5:B6", "B5:B7", "B5:B8"}


def test_export_lifecycle_profiles_rejects_non_contiguous_ages(tmp_path):
    t6v = pd.DataFrame(
        [
            {"transport_type": "passenger", "vehicle_type": "LPVs", "age": 0, "vintage_share": 0.70, "survival_probability": 0.90},
            {"transport_type": "passenger", "vehicle_type": "LPVs", "age": 2, "vintage_share": 0.30, "survival_probability": 0.00},
        ]
    )

    with pytest.raises(ValueError, match="contiguous"):
        export_lifecycle_profiles_from_t6v(t6v, tmp_path, economy="99_TST")


def test_excel_profile_name_uses_sentence_case_underscores_and_no_special_characters():
    assert (
        _normalise_excel_profile_name("freight / vehicle survival!")
        == "Freight_vehicle_survival"
    )
