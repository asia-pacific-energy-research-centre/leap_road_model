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
from adapters import esto_inputs
from adapters.combined_exports import parse_branch_path
from adapters.road_module1_defaults import (
    _find_default_inputs_csv,
    _load_single_economy,
    _filter_out_of_scope_model_rows,
    get_vintage_profiles,
    get_phev_utilisation_rate,
    get_freight_gdp_elasticity_adjustment,
    get_passenger_saturation_level,
    get_passenger_saturation_reached,
    get_passenger_stock_growth_rate_adjustment,
    get_reconciliation_weights,
    get_vehicle_equivalent_weight_bounds,
    get_vehicle_type_stock_shares,
    load_road_module1_defaults,
    load_module1_leap_df,
)
from road_workflow import parse_leap_format_inputs


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


class TestEstoInputs:
    def test_default_esto_csv_is_repo_input_data_copy(self):
        default_path = esto_inputs._DEFAULT_ESTO_CSV

        assert default_path.name == "esto_transport_2000_2022.csv"
        assert default_path.parent.name == "input_data"
        assert default_path.exists()


class TestLeapFormatInputParsing:
    def test_stock_scale_millions_is_converted_to_devices(self):
        df = pd.DataFrame([
            {
                "Branch Path": "Demand\\Passenger road\\LPVs\\ICE small\\Motor gasoline",
                "Variable": "Stock",
                "Scenario": "Current Accounts",
                "Region": "20_USA",
                "Scale": "Millions",
                "Units": "Device",
                "2022": 1.25,
            }
        ])

        parsed = parse_leap_format_inputs(df, base_year=2022)

        assert parsed.loc[0, "variable"] == "stock"
        assert parsed.loc[0, "value"] == pytest.approx(1_250_000.0)

    def test_mileage_scale_thousands_is_converted_to_kilometres(self):
        df = pd.DataFrame([
            {
                "Branch Path": "Demand\\Passenger road\\LPVs\\ICE small\\Motor gasoline",
                "Variable": "Mileage",
                "Scenario": "Current Accounts",
                "Region": "20_USA",
                "Scale": "Thousands",
                "Units": "Kilometer",
                "2022": 40.0,
            },
        ])

        parsed = parse_leap_format_inputs(df, base_year=2022)

        parsed_by_variable = parsed.set_index("variable")
        assert parsed_by_variable.loc["mileage", "value"] == pytest.approx(40_000.0)

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

    def test_saturation_reached_flag_parsed(self, tmp_path: Path):
        df = pd.DataFrame([{
            "Branch Path": "Demand\\Passenger road",
            "Variable": "Passenger Saturation Reached",
            "Units": "Boolean",
            "Per...": "",
            "2022": "TRUE",
            "source_name": "test",
            "researcher_review_recommended": False,
            "review_reason": "",
        }])
        csv_path = tmp_path / "defaults.csv"
        df.to_csv(csv_path, index=False)

        loaded = _load_single_economy(csv_path, economy_code="20_USA", version_name="test")

        assert get_passenger_saturation_reached(loaded, economy="20_USA") is True

    def test_freight_elasticity_adjustment_parsed(self, tmp_path: Path):
        df = pd.DataFrame([{
            "Economy": "20_USA",
            "Scenario": "Current Accounts",
            "Branch Path": "Demand\\Freight road",
            "Variable": "Freight GDP Elasticity Adjustment",
            "Year": 2022,
            "Value": 1.25,
            "Units": "Multiplier",
        }])
        csv_path = tmp_path / "road_module1_values_20USA_vtest_20260603.csv"
        df.to_csv(csv_path, index=False)

        loaded = _load_single_economy(csv_path, economy_code="20_USA", version_name="test")

        assert get_freight_gdp_elasticity_adjustment(loaded, economy="20_USA") == pytest.approx(1.25)

    def test_passenger_stock_growth_rate_adjustment_parsed(self, tmp_path: Path):
        df = pd.DataFrame([{
            "Economy": "20_USA",
            "Scenario": "Current Accounts",
            "Branch Path": "Demand\\Passenger road",
            "Variable": "Passenger Stock Growth Rate Adjustment",
            "Year": 2022,
            "Value": 1.35,
            "Units": "Multiplier",
        }])
        csv_path = tmp_path / "road_module1_values_20USA_vtest_20260603.csv"
        df.to_csv(csv_path, index=False)

        loaded = _load_single_economy(csv_path, economy_code="20_USA", version_name="test")

        assert get_passenger_stock_growth_rate_adjustment(loaded, economy="20_USA") == pytest.approx(1.35)

    def test_passenger_stock_growth_rate_adjustment_defaults_to_1p2(self, tmp_path: Path):
        df = pd.DataFrame([{
            "Economy": "20_USA",
            "Scenario": "Current Accounts",
            "Branch Path": "Demand\\Passenger road",
            "Variable": "Passenger Vehicle Saturation",
            "Year": 2022,
            "Value": 890.0,
            "Units": "Device",
        }])
        csv_path = tmp_path / "road_module1_values_20USA_vtest_20260603.csv"
        df.to_csv(csv_path, index=False)

        loaded = _load_single_economy(csv_path, economy_code="20_USA", version_name="test")

        assert get_passenger_stock_growth_rate_adjustment(loaded, economy="20_USA") == pytest.approx(1.2)

    def test_vehicle_equivalent_weight_bounds_parsed(self, tmp_path: Path):
        df = pd.DataFrame([
            {
                "Branch Path": "Demand\\Passenger road\\Motorcycles",
                "Variable": "Vehicle Equivalent Weight Lower Bound",
                "Units": "Vehicle equivalent",
                "Per...": "",
                "2022": 0.10,
                "source_name": "test",
                "researcher_review_recommended": False,
                "review_reason": "",
            },
            {
                "Branch Path": "Demand\\Passenger road\\Motorcycles",
                "Variable": "Vehicle Equivalent Weight Upper Bound",
                "Units": "Vehicle equivalent",
                "Per...": "",
                "2022": 0.70,
                "source_name": "test",
                "researcher_review_recommended": False,
                "review_reason": "",
            },
        ])
        csv_path = tmp_path / "defaults.csv"
        df.to_csv(csv_path, index=False)

        loaded = _load_single_economy(csv_path, economy_code="20_USA", version_name="test")
        bounds = get_vehicle_equivalent_weight_bounds(loaded, economy="20_USA")

        assert bounds["Motorcycles"] == pytest.approx((0.10, 0.70))
        assert bounds["Buses"] == pytest.approx((8.0, 30.0))

    def test_long_module1_values_csv_is_loaded(self, tmp_path: Path):
        df = pd.DataFrame([
            {
                "Economy": "20USA",
                "Scenario": "Current Accounts",
                "Branch Path": "Demand\\Passenger road",
                "Variable": "Passenger Vehicle Saturation",
                "Year": 2022,
                "Value": 890.0,
                "Units": "Device",
                "Source": "test_source.csv",
                "Source Method": "supplemental_csv",
                "Comment": "per 1000 people",
                "Version": "vtest",
            }
        ])
        csv_path = tmp_path / "road_module1_values_20USA_vtest_20260603.csv"
        df.to_csv(csv_path, index=False)

        loaded = _load_single_economy(csv_path, economy_code="20_USA", version_name="vtest")

        assert get_passenger_saturation_level(loaded, economy="20_USA") == pytest.approx(0.89)
        assert loaded.iloc[0]["source"] == "test_source.csv"
        assert loaded.iloc[0]["notes"] == "per 1000 people"

    def test_long_module1_values_file_preferred_over_legacy(self, tmp_path: Path):
        legacy = tmp_path / "road_module1_default_filled_inputs_20USA.csv"
        legacy.write_text("Branch Path,Variable,Scenario,Region,2022\n", encoding="utf-8")
        long_path = tmp_path / "road_module1_values_20USA_vtest_20260603.csv"
        long_path.write_text("Economy,Scenario,Branch Path,Variable,Year,Value\n", encoding="utf-8")

        assert _find_default_inputs_csv(tmp_path, "20_USA") == long_path

    def test_load_module1_leap_df_converts_long_csv_to_wide(self, tmp_path: Path):
        version_dir = tmp_path / "vtest"
        economy_dir = version_dir / "20USA"
        economy_dir.mkdir(parents=True)
        df = pd.DataFrame([
            {
                "Economy": "20USA",
                "Scenario": "Current Accounts",
                "Branch Path": "Demand\\Passenger road\\LPVs\\ICE small\\Motor gasoline",
                "Variable": "Stock",
                "Year": 2022,
                "Value": 100.0,
                "Units": "Vehicle",
            }
        ])
        df.to_csv(economy_dir / "road_module1_values_20USA_vtest_20260603.csv", index=False)

        loaded = load_module1_leap_df(tmp_path, economy="20_USA", version="vtest")

        assert "2022" in loaded.columns
        assert loaded.loc[0, "Region"] == "20_USA"
        assert loaded.loc[0, "2022"] == pytest.approx(100.0)

    def test_long_module1_scale_survives_loader_and_parses_to_devices(self, tmp_path: Path):
        version_dir = tmp_path / "vtest"
        economy_dir = version_dir / "20USA"
        economy_dir.mkdir(parents=True)
        df = pd.DataFrame([
            {
                "Economy": "20USA",
                "Scenario": "Current Accounts",
                "Branch Path": "Demand\\Passenger road\\LPVs\\ICE small\\Motor gasoline",
                "Variable": "Stock",
                "Year": 2022,
                "Value": 1.25,
                "Scale": "Millions",
                "Units": "Vehicle",
            }
        ])
        df.to_csv(economy_dir / "road_module1_values_20USA_vtest_20260603.csv", index=False)

        loaded = load_module1_leap_df(tmp_path, economy="20_USA", version="vtest")
        parsed = parse_leap_format_inputs(loaded, base_year=2022)

        assert loaded.loc[0, "Scale"] == "Millions"
        assert parsed.loc[0, "value"] == pytest.approx(1_250_000.0)

    def test_vehicle_type_stock_shares_use_only_exact_vehicle_branches(self):
        # Long-format defaults_df — mirrors what load_road_module1_defaults() produces.
        defaults_df = pd.DataFrame([
            {"economy": "20_USA", "variable": "stock_share", "leap_branch_path": "Demand\\Freight road\\Trucks", "year": 2022, "value": 33.52055086},
            {"economy": "20_USA", "variable": "stock_share", "leap_branch_path": "Demand\\Freight road\\Trucks", "year": 2040, "value": 40.0},
            {"economy": "20_USA", "variable": "stock_share", "leap_branch_path": "Demand\\Freight road\\LCVs", "year": 2022, "value": 66.47944914},
            {"economy": "20_USA", "variable": "stock_share", "leap_branch_path": "Demand\\Freight road\\LCVs", "year": 2040, "value": 60.0},
            {"economy": "20_USA", "variable": "stock_share", "leap_branch_path": "Demand\\Passenger road\\Motorcycles", "year": 2022, "value": 3.135620686},
            {"economy": "20_USA", "variable": "stock_share", "leap_branch_path": "Demand\\Passenger road\\Buses", "year": 2022, "value": 0.347687436},
            {"economy": "20_USA", "variable": "stock_share", "leap_branch_path": "Demand\\Passenger road\\LPVs", "year": 2022, "value": 96.51669188},
            # sub-branch row — must be filtered out
            {"economy": "20_USA", "variable": "stock_share", "leap_branch_path": "Demand\\Freight road\\Trucks\\ICE heavy", "year": 2022, "value": 99.0},
        ])

        shares = get_vehicle_type_stock_shares(defaults_df, economy="20_USA")

        assert shares["Trucks"].loc[2022] == pytest.approx(0.3352055086)
        assert shares["Trucks"].loc[2040] == pytest.approx(0.40)
        assert shares["LCVs"].loc[2040] == pytest.approx(0.60)
        assert shares["LPVs"].loc[2022] == pytest.approx(0.9651669188)
        assert "ICE heavy" not in shares

    def test_global_profile_prefixed_branch_path_age_is_loaded(self, tmp_path: Path):
        df = pd.DataFrame([
            {
                "Economy": "20USA",
                "Scenario": "Current Accounts",
                "Branch Path": "Age Profile\\5",
                "Variable": "Vintage Profile Share",
                "Year": 2022,
                "Value": 0.25,
                "Units": "Share",
            }
        ])
        csv_path = tmp_path / "road_module1_values_20USA_vtest_20260603.csv"
        df.to_csv(csv_path, index=False)

        loaded = _load_single_economy(csv_path, economy_code="20_USA", version_name="vtest")
        profile = get_vintage_profiles(loaded, economy="20_USA", transport_type="passenger")

        assert profile.loc[0, "age"] == 5
        assert profile.loc[0, "vintage_share"] == pytest.approx(0.25)

    def test_flat_stable_long_package_is_loaded(self, tmp_path: Path):
        df = pd.DataFrame([
            {
                "Economy": "20_USA",
                "Scenario": "Current Accounts",
                "Branch Path": "Demand\\Transport passenger road\\LPVs\\HEV small\\Motor gasoline",
                "Variable": "Stock",
                "Year": 2022,
                "Value": 123.0,
                "Units": "Device",
            },
            {
                "Economy": "20_USA",
                "Scenario": "Current Accounts",
                "Branch Path": "PHEV Electric Utilisation Rate/passenger",
                "Variable": "PHEV Electric Utilisation Rate",
                "Year": 2022,
                "Value": 0.42,
                "Units": "Share",
            },
            {
                "Economy": "20_USA",
                "Scenario": "Current Accounts",
                "Branch Path": "Reconciliation/weight/Fuel Economy",
                "Variable": "Reconciliation Weight",
                "Year": 2022,
                "Value": 0.25,
                "Units": "Weight",
            },
        ])
        df.to_csv(tmp_path / "road_module1_values_20_USA.csv", index=False)

        loaded = load_road_module1_defaults(tmp_path, economy_filter=["20_USA"])

        assert "stock" in set(loaded["variable"])
        assert "reconciliation_weight_efficiency" in set(loaded["variable"])
        assert get_phev_utilisation_rate(loaded, economy="20_USA") == pytest.approx(0.42)

        raw = load_module1_leap_df(tmp_path, economy="20_USA")
        assert "2022" in raw.columns
        assert raw.loc[raw["Variable"].eq("Stock"), "Region"].iloc[0] == "20_USA"

    def test_component_reconciliation_weights_from_pseudo_branches(self, tmp_path: Path):
        rows = []
        for branch, value in [
            ("Reconciliation/weight/Stock", 0.5),
            ("Reconciliation/weight/Mileage", 0.25),
            ("Reconciliation/weight/Fuel Economy", 0.25),
        ]:
            rows.append({
                "Economy": "20_USA",
                "Scenario": "Current Accounts",
                "Branch Path": branch,
                "Variable": "Reconciliation Weight",
                "Year": 2022,
                "Value": value,
                "Units": "Weight",
            })
        pd.DataFrame(rows).to_csv(tmp_path / "road_module1_values_20_USA.csv", index=False)

        loaded = load_road_module1_defaults(tmp_path, economy_filter=["20_USA"])
        weights = get_reconciliation_weights(loaded, economy="20_USA")

        assert weights == pytest.approx({"stock": 0.5, "mileage": 0.25, "efficiency": 0.25})

    def test_out_of_scope_truck_hybrid_rows_are_filtered(self, tmp_path: Path):
        df = pd.DataFrame([
            {
                "Branch Path": "Demand\\Freight road\\Trucks\\PHEV heavy",
                "Variable": "Stock",
                "Scenario": "Reference",
                "Region": "20_USA",
                "Units": "Device",
                "2022": 10.0,
            },
            {
                "Branch Path": "Demand\\Freight road\\Trucks\\HEV medium",
                "Variable": "Stock",
                "Scenario": "Reference",
                "Region": "20_USA",
                "Units": "Device",
                "2022": 20.0,
            },
            {
                "Branch Path": "Demand\\Freight road\\Trucks\\BEV heavy",
                "Variable": "Stock",
                "Scenario": "Reference",
                "Region": "20_USA",
                "Units": "Device",
                "2022": 30.0,
            },
        ])

        filtered = _filter_out_of_scope_model_rows(df)
        assert filtered["Branch Path"].tolist() == ["Demand\\Freight road\\Trucks\\BEV heavy"]

        csv_path = tmp_path / "road_module1_default_filled_inputs_20USA.csv"
        df.to_csv(csv_path, index=False)
        loaded = _load_single_economy(csv_path, economy_code="20_USA", version_name="vtest")

        assert set(loaded["drive_type"]) == {"BEV"}
