"""
Tests for adapters — especially the LEAP expression parser
and branch path parser, which have no external dependencies.
"""

from pathlib import Path

import pytest
import pandas as pd

from adapters.leap_expressions import (
    to_leap_expression,
    from_leap_expression,
    parse_expression_column,
)
from adapters.combined_exports import parse_branch_path
from adapters.road_module1_defaults import _load_single_economy, get_passenger_saturation_level


# ===========================================================================
# LEAP expression round-trip
# ===========================================================================

class TestLeapExpressions:
    def test_to_expression(self):
        s = pd.Series({2022: 0.0, 2023: 100.5, 2024: 200.1})
        expr = to_leap_expression(s)
        assert expr.startswith("Data(")
        assert "2022" in expr
        assert "2023" in expr

    def test_from_expression(self):
        expr = "Data(2022, 0.0, 2023, 100.5, 2024, 200.1)"
        s = from_leap_expression(expr)
        assert s[2022] == 0.0
        assert abs(s[2023] - 100.5) < 1e-6
        assert len(s) == 3

    def test_round_trip(self):
        original = pd.Series({2022: 1.0, 2023: 2.0, 2024: 3.0})
        expr = to_leap_expression(original)
        recovered = from_leap_expression(expr)
        for year in original.index:
            assert abs(original[year] - recovered[year]) < 1e-6

    def test_scientific_notation(self):
        expr = "Data(2022, 8.77273e+07, 2023, 8.41715e+07)"
        s = from_leap_expression(expr)
        assert s[2022] > 1e7

    def test_empty_expression(self):
        s = from_leap_expression("")
        assert len(s) == 0

    def test_parse_expression_column(self):
        df = pd.DataFrame({
            "Branch Path": ["Demand\\Passenger road\\LPVs\\ICE\\Motor gasoline"],
            "Variable":    ["Sales"],
            "Expression":  ["Data(2022, 100.0, 2023, 110.0)"],
        })
        tidy = parse_expression_column(df, "Expression")
        assert len(tidy) == 2
        assert set(tidy["year"]) == {2022, 2023}


# ===========================================================================
# Branch path parsing
# ===========================================================================

class TestBranchPathParsing:
    def test_full_path(self):
        path = "Demand\\Passenger road\\LPVs\\ICE small\\Motor gasoline"
        result = parse_branch_path(path)
        assert result["transport_type"] == "Passenger road"
        assert result["vehicle_type"] == "LPVs"
        assert result["technology"] == "ICE small"
        assert result["fuel"] == "Motor gasoline"

    def test_freight_path(self):
        path = "Demand\\Freight road\\Trucks\\ICE heavy\\Gas and diesel oil"
        result = parse_branch_path(path)
        assert result["transport_type"] == "Freight road"
        assert result["vehicle_type"] == "Trucks"

    def test_partial_path(self):
        path = "Demand\\Passenger road\\LPVs"
        result = parse_branch_path(path)
        assert result["vehicle_type"] == "LPVs"
        assert result["technology"] is None
        assert result["fuel"] is None


# ===========================================================================
# Module 1 defaults adapter
# ===========================================================================

class TestModule1DefaultsSaturationUnits:
    def test_saturation_per_1000_people_converted_to_per_capita(self, tmp_path: Path):
        df = pd.DataFrame([
            {
                "Branch Path": "Demand\\Passenger road",
                "Variable": "Passenger Vehicle Saturation",
                "Units": "Device",
                "Per...": "1000 people",
                "2022": 890.0,
                "source_name": "test",
                "researcher_review_recommended": False,
                "review_reason": "",
            }
        ])
        csv_path = tmp_path / "defaults.csv"
        df.to_csv(csv_path, index=False)

        loaded = _load_single_economy(csv_path, economy_code="20_USA", version_name="test")
        sat = get_passenger_saturation_level(loaded, economy="20_USA")
        assert sat == pytest.approx(0.89)

    def test_saturation_without_per_1000_is_not_rescaled(self, tmp_path: Path):
        df = pd.DataFrame([
            {
                "Branch Path": "Demand\\Passenger road",
                "Variable": "Passenger Vehicle Saturation",
                "Units": "Device",
                "Per...": "",
                "2022": 0.95,
                "source_name": "test",
                "researcher_review_recommended": False,
                "review_reason": "",
            }
        ])
        csv_path = tmp_path / "defaults.csv"
        df.to_csv(csv_path, index=False)

        loaded = _load_single_economy(csv_path, economy_code="20_USA", version_name="test")
        sat = get_passenger_saturation_level(loaded, economy="20_USA")
        assert sat == pytest.approx(0.95)
