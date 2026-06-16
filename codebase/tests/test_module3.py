"""
Tests for Module 3 — Stock target projection.

Tests focus on the pure mathematical functions, which are already implemented.
run_module3() is tested only with a minimal stub until Modules 1 and 2 are ready.
"""

import numpy as np
import pandas as pd
import pytest

from modules.module3_stock_targets import (
    compute_motorisation_base,
    estimate_recent_energy_growth,
    estimate_passenger_k,
    estimate_passenger_income_elasticity,
    project_passenger_motorisation_envelope_from_gdp_per_capita,
    project_motorisation_envelope,
    resolve_saturation,
    estimate_freight_elasticity,
    project_passenger_stocks,
    project_freight_stocks,
    calibrate_passenger_vehicle_equivalent_weights,
    _read_base_stocks,
)


# ===========================================================================
# compute_motorisation_base
# ===========================================================================

class TestComputemotorisationBase:
    def test_basic(self):
        base_stocks = {"LPVs": 1_000_000, "Motorcycles": 500_000, "Buses": 10_000}
        weights = {"LPVs": 1.0, "Motorcycles": 0.8, "Buses": 20.0}
        population = 5_000_000

        M_base, shares = compute_motorisation_base(base_stocks, weights, population)

        weighted_total = 1_000_000 * 1.0 + 500_000 * 0.8 + 10_000 * 20.0
        expected_M = weighted_total / population
        assert abs(M_base - expected_M) < 1e-6

    def test_shares_sum_to_one(self):
        base_stocks = {"LPVs": 1_000_000, "Motorcycles": 500_000}
        weights = {"LPVs": 1.0, "Motorcycles": 0.8}
        _, shares = compute_motorisation_base(base_stocks, weights, 5_000_000)
        assert abs(sum(shares.values()) - 1.0) < 1e-6

    def test_zero_population(self):
        M_base, _ = compute_motorisation_base({"LPVs": 1000}, {"LPVs": 1.0}, 0)
        assert M_base == 0.0


# ===========================================================================
# estimate_recent_energy_growth
# ===========================================================================

class TestEstimateRecentEnergyGrowth:
    def test_constant_energy_returns_zero(self):
        energy = pd.Series([100.0] * 11, index=range(2012, 2023))
        g = estimate_recent_energy_growth(energy, lookback_years=10, base_year=2022)
        assert abs(g) < 1e-6

    def test_growing_energy(self):
        years = range(2012, 2023)
        # Exactly 5% growth per year
        energy = pd.Series([100.0 * (1.05 ** i) for i in range(11)], index=years)
        g = estimate_recent_energy_growth(energy, lookback_years=10, base_year=2022)
        assert abs(g - np.log(1.05)) < 1e-3

    def test_excludes_covid_years(self):
        years = list(range(2012, 2023))
        energy_vals = [100.0 * (1.05 ** i) for i in range(11)]
        # Add a severe COVID dip only in 2020 and 2021 (2022 recovers normally)
        energy_vals[8] = 50.0   # 2020 index
        energy_vals[9] = 55.0   # 2021 index
        energy = pd.Series(energy_vals, index=years)

        # Exclude only the two dip years — the window is 2012-2022 with gaps at 2020, 2021
        g_with_exclusion = estimate_recent_energy_growth(
            energy, lookback_years=10, base_year=2022, exclude_years=[2020, 2021]
        )
        # Without exclusion the large dip years drag the average down
        g_without_exclusion = estimate_recent_energy_growth(
            energy, lookback_years=10, base_year=2022, exclude_years=[]
        )
        # Exclusion of the COVID dip should give a meaningfully higher growth rate
        assert g_with_exclusion > g_without_exclusion + 0.001

    def test_insufficient_data_returns_zero(self):
        energy = pd.Series([100.0], index=[2022])
        g = estimate_recent_energy_growth(energy, lookback_years=10, base_year=2022)
        assert g == 0.0


# ===========================================================================
# estimate_passenger_k
# ===========================================================================

class TestEstimatePassengerK:
    def test_basic_calculation(self):
        # k = g_E / (1 - M_base / M_sat)
        g_E = 0.03
        M_base = 0.3
        M_sat = 0.5
        expected_k = g_E / (1 - M_base / M_sat)  # = 0.03 / 0.4 = 0.075
        k, clamped = estimate_passenger_k(g_E, M_base, M_sat)
        assert abs(k - expected_k) < 1e-6
        assert not clamped

    def test_clamps_to_min(self):
        k, clamped = estimate_passenger_k(g_E=-0.05, M_base=0.3, M_sat=0.5)
        assert k == 0.0
        assert clamped

    def test_clamps_to_max(self):
        k, clamped = estimate_passenger_k(g_E=0.20, M_base=0.1, M_sat=0.5)
        assert k == 0.15
        assert clamped

    def test_saturated_returns_min(self):
        k, clamped = estimate_passenger_k(g_E=0.03, M_base=0.5, M_sat=0.5)
        assert k == 0.0

    def test_custom_bounds(self):
        k, clamped = estimate_passenger_k(g_E=0.10, M_base=0.1, M_sat=1.0, k_min=0.05, k_max=0.08)
        assert 0.05 <= k <= 0.08


# ===========================================================================
# project_motorisation_envelope
# ===========================================================================

class TestProjectMotorisationEnvelope:
    def test_base_year_matches(self):
        years = list(range(2022, 2061))
        M_base, M_sat, k = 0.3, 0.6, 0.05
        envelope = project_motorisation_envelope(2022, years, M_base, M_sat, k)
        assert abs(envelope[2022] - M_base) < 1e-4

    def test_approaches_saturation(self):
        years = list(range(2022, 2061))
        M_base, M_sat, k = 0.3, 0.6, 0.10
        envelope = project_motorisation_envelope(2022, years, M_base, M_sat, k)
        assert envelope[2060] < M_sat
        assert envelope[2060] > envelope[2022]

    def test_zero_k_is_flat(self):
        years = list(range(2022, 2061))
        envelope = project_motorisation_envelope(2022, years, 0.3, 0.6, k=0.0)
        assert (envelope == 0.3).all()

    def test_monotone_increasing(self):
        years = list(range(2022, 2061))
        envelope = project_motorisation_envelope(2022, years, 0.3, 0.6, k=0.05)
        diffs = envelope.diff().dropna()
        assert (diffs >= 0).all()


# ===========================================================================
# resolve_saturation
# ===========================================================================

class TestResolveSaturation:
    def test_uses_researcher_override(self):
        M_sat, flag = resolve_saturation(0.3, saturation_overrides={"researcher": 0.7})
        assert M_sat == 0.7
        assert flag == "researcher"

    def test_fallback_multiplier(self):
        M_sat, flag = resolve_saturation(0.2, saturation_overrides={}, fallback_multiplier=3.0)
        assert abs(M_sat - 0.6) < 1e-6
        assert flag == "fallback"


# ===========================================================================
# estimate_freight_elasticity
# ===========================================================================

class TestEstimateFreightElasticity:
    def test_unit_elasticity(self):
        years = list(range(2012, 2023))
        # Energy grows at same rate as GDP → elasticity = 1.0
        energy = pd.Series([100.0 * (1.03 ** i) for i in range(11)], index=years)
        gdp = pd.Series([1000.0 * (1.03 ** i) for i in range(11)], index=years)
        diag = estimate_freight_elasticity(energy, gdp, lookback_years=10, base_year=2022)
        assert abs(diag["elasticity"] - 1.0) < 0.01
        assert diag["data_source"] == "estimated"

    def test_clamped_to_bounds(self):
        years = list(range(2012, 2023))
        # Energy grows much faster than GDP → elasticity would be > 2.0
        energy = pd.Series([100.0 * (1.10 ** i) for i in range(11)], index=years)
        gdp = pd.Series([1000.0 * (1.01 ** i) for i in range(11)], index=years)
        diag = estimate_freight_elasticity(
            energy, gdp, lookback_years=10, base_year=2022,
            elasticity_max=2.0
        )
        assert diag["elasticity"] <= 2.0
        assert diag["elasticity_clamped"] is True

    def test_returns_default_on_zero_gdp_growth(self):
        years = list(range(2012, 2023))
        energy = pd.Series([100.0 * (1.03 ** i) for i in range(11)], index=years)
        gdp = pd.Series([1000.0] * 11, index=years)  # flat GDP
        diag = estimate_freight_elasticity(
            energy, gdp, lookback_years=10, base_year=2022, default_elasticity=0.8
        )
        assert diag["elasticity"] == 0.8
        assert diag["data_source"] == "default"


class TestProjectFreightStocks:
    def test_projects_total_freight_then_splits_by_vehicle_type_share(self):
        years = [2022, 2023, 2024]
        gdp = pd.Series([100.0, 110.0, 121.0], index=years)
        energy = pd.Series([50.0, 55.0, 60.5], index=years)
        shares = {
            "Trucks": pd.Series({2022: 0.30, 2024: 0.40}),
            "LCVs": pd.Series({2022: 0.70, 2024: 0.60}),
        }

        result = project_freight_stocks(
            years=years,
            gdp=gdp,
            energy_series=energy,
            base_stocks={"Trucks": 300.0, "LCVs": 700.0},
            vehicle_type_shares=shares,
            elasticity_overrides={"freight_total": 1.0},
        )

        total_2024 = 1000.0 * (121.0 / 100.0)
        assert result["target_stocks"]["Trucks"].loc[2024] == pytest.approx(total_2024 * 0.40)
        assert result["target_stocks"]["LCVs"].loc[2024] == pytest.approx(total_2024 * 0.60)
        assert (
            result["target_stocks"]["Trucks"].loc[2024]
            + result["target_stocks"]["LCVs"].loc[2024]
        ) == pytest.approx(total_2024)
        assert result["elasticity_diagnostics"]["data_source"] == "override"

    def test_applies_elasticity_adjustment_after_estimation(self):
        years = [2022, 2023, 2024]
        gdp = pd.Series(
            [100.0, 110.0, 121.0, 133.1, 146.41],
            index=[2020, 2021, 2022, 2023, 2024],
        )
        energy = pd.Series(
            [50.0, 55.0, 60.5, 66.55, 73.205],
            index=[2020, 2021, 2022, 2023, 2024],
        )

        result = project_freight_stocks(
            years=years,
            gdp=gdp,
            energy_series=energy,
            base_stocks={"Trucks": 300.0, "LCVs": 700.0},
            elasticity_adjustments={"freight_total": 0.5},
            cfg={
                "lookback_window_years": 2,
                "covid_exclude_years": [],
                "elasticity_min": 0.0,
                "elasticity_max": 2.0,
                "default_elasticity": 0.8,
            },
        )

        total_2024 = (
            result["target_stocks"]["Trucks"].loc[2024]
            + result["target_stocks"]["LCVs"].loc[2024]
        )
        assert total_2024 == pytest.approx(1000.0 * ((146.41 / 121.0) ** 0.5))
        assert result["elasticity_diagnostics"]["elasticity_adjustment"] == pytest.approx(0.5)
        assert result["elasticity_diagnostics"]["data_source"] == "estimated_adjusted"


# ===========================================================================
# Integration: project_passenger_stocks
# ===========================================================================

class TestPassengerIncomeElasticity:
    def test_estimates_from_passenger_energy_and_gdp_per_capita(self):
        years = list(range(2012, 2023))
        energy = pd.Series([100.0 * (1.03 ** i) for i in range(len(years))], index=years)
        gdp = pd.Series([1000.0 * (1.04 ** i) for i in range(len(years))], index=years)
        population = pd.Series([10.0 * (1.01 ** i) for i in range(len(years))], index=years)

        diag = estimate_passenger_income_elasticity(
            passenger_energy=energy,
            gdp=gdp,
            population=population,
            lookback_years=10,
            base_year=2022,
            exclude_years=[],
        )

        assert diag["data_source"] == "estimated"
        assert diag["elasticity"] == pytest.approx(
            diag["energy_growth_rate"] / diag["gdp_per_capita_growth_rate"]
        )


class TestPassengerGDPPerCapitaEnvelope:
    def test_rising_gdp_per_capita_increases_motorisation_below_saturation(self):
        years = [2022, 2023, 2024]
        population = pd.Series([100.0, 100.0, 100.0], index=years)
        gdp = pd.Series([100.0, 110.0, 121.0], index=years)

        envelope = project_passenger_motorisation_envelope_from_gdp_per_capita(
            base_year=2022,
            projection_years=years,
            population=population,
            gdp=gdp,
            M_base=0.2,
            M_sat=0.6,
            income_elasticity=1.0,
        )

        assert envelope.loc[2022] == pytest.approx(0.2)
        assert envelope.loc[2024] > envelope.loc[2022]
        assert envelope.loc[2024] < 0.6


class TestProjectPassengerStocks:
    def test_base_year_stock_preserved(self, population_series, gdp_series, passenger_energy_series):
        years = list(range(2022, 2061))
        base_stocks = {"LPVs": 3_000_000, "Motorcycles": 150_000, "Buses": 8_000}
        weights = {"LPVs": 1.0, "Motorcycles": 0.8, "Buses": 20.0}

        result = project_passenger_stocks(
            years=years,
            population=population_series,
            gdp=gdp_series,
            energy_series=passenger_energy_series,
            base_stocks=base_stocks,
            weights=weights,
        )

        # The motorisation envelope is in car-equivalents per capita.
        # M_envelope[base_year] should equal M_base (the logistic curve is anchored there).
        weighted_total = sum(count * weights[vt] for vt, count in base_stocks.items())
        M_base = weighted_total / population_series[2022]
        assert abs(result["M_envelope"][2022] - M_base) < 1e-4

        for vt, stock in base_stocks.items():
            assert abs(result["target_stocks"][vt][2022] - stock) < 1e-4

    def test_stocks_non_negative(self, population_series, gdp_series, passenger_energy_series):
        years = list(range(2022, 2061))
        base_stocks = {"LPVs": 3_000_000, "Motorcycles": 150_000, "Buses": 8_000}
        weights = {"LPVs": 1.0, "Motorcycles": 0.8, "Buses": 20.0}

        result = project_passenger_stocks(
            years=years,
            population=population_series,
            gdp=gdp_series,
            energy_series=passenger_energy_series,
            base_stocks=base_stocks,
            weights=weights,
        )

        for vt, series in result["target_stocks"].items():
            assert (series >= 0).all(), f"Negative stock for {vt}"

    def test_growth_rate_adjustment_speeds_passenger_stock_growth(self, population_series, gdp_series, passenger_energy_series):
        years = list(range(2022, 2061))
        base_stocks = {"LPVs": 3_000_000, "Motorcycles": 150_000, "Buses": 8_000}
        weights = {"LPVs": 1.0, "Motorcycles": 0.8, "Buses": 20.0}

        baseline = project_passenger_stocks(
            years=years,
            population=population_series,
            gdp=gdp_series,
            energy_series=passenger_energy_series,
            base_stocks=base_stocks,
            weights=weights,
            growth_rate_adjustment=1.0,
        )
        faster = project_passenger_stocks(
            years=years,
            population=population_series,
            gdp=gdp_series,
            energy_series=passenger_energy_series,
            base_stocks=base_stocks,
            weights=weights,
            growth_rate_adjustment=1.5,
        )

        assert faster["target_stocks"]["LPVs"].loc[2022] == pytest.approx(
            baseline["target_stocks"]["LPVs"].loc[2022]
        )
        assert faster["target_stocks"]["LPVs"].loc[2040] > baseline["target_stocks"]["LPVs"].loc[2040]
        assert faster["growth_rate_adjustment"] == pytest.approx(1.5)

    def test_saturation_flag_calibrates_base_year_to_saturation(self, passenger_energy_series):
        years = list(range(2022, 2061))
        population = pd.Series(1000.0, index=years)
        gdp = pd.Series(1000.0 * (1.02 ** np.arange(len(years))), index=years)
        base_stocks = {"LPVs": 100_000, "Motorcycles": 100_000, "Buses": 10_000}
        weights = {"LPVs": 1.0, "Motorcycles": 0.25, "Buses": 12.0}
        target_sat = 300.0

        result = project_passenger_stocks(
            years=years,
            population=population,
            gdp=gdp,
            energy_series=passenger_energy_series,
            base_stocks=base_stocks,
            weights=weights,
            saturation_overrides={"researcher": target_sat},
            passenger_saturation_reached=True,
            vehicle_equivalent_weight_bounds={
                "Motorcycles": (0.05, 0.80),
                "Buses": (8.0, 30.0),
            },
        )

        assert result["M_envelope"][2022] == pytest.approx(target_sat)
        assert result["adjusted_weights"]["LPVs"] == pytest.approx(1.0)
        assert result["weight_calibration_applied"] is True


class TestPassengerWeightCalibration:
    def test_disabled_returns_original_weights(self):
        weights = {"LPVs": 1.1, "Motorcycles": 0.25, "Buses": 12.0}
        result = calibrate_passenger_vehicle_equivalent_weights(
            base_stocks={"LPVs": 100.0, "Motorcycles": 50.0, "Buses": 5.0},
            weights=weights,
            population_base=1000.0,
            saturation_level=0.5,
            passenger_saturation_reached=False,
        )

        assert result["adjusted_weights"] == weights
        assert result["applied"] is False

    def test_exact_feasible_solution_hits_saturation_and_keeps_lpv_fixed(self):
        result = calibrate_passenger_vehicle_equivalent_weights(
            base_stocks={"LPVs": 100.0, "Motorcycles": 100.0, "Buses": 10.0},
            weights={"LPVs": 1.0, "Motorcycles": 0.25, "Buses": 12.0},
            population_base=1000.0,
            saturation_level=0.30,
            passenger_saturation_reached=True,
            bounds={"Motorcycles": (0.05, 0.80), "Buses": (8.0, 30.0)},
        )

        adjusted = result["adjusted_weights"]
        weighted_stock = 100.0 + 100.0 * adjusted["Motorcycles"] + 10.0 * adjusted["Buses"]
        assert adjusted["LPVs"] == pytest.approx(1.0)
        assert weighted_stock == pytest.approx(300.0)
        assert result["gap"] == pytest.approx(0.0)

    def test_unreachable_target_clamps_to_nearest_bounds(self):
        result = calibrate_passenger_vehicle_equivalent_weights(
            base_stocks={"LPVs": 100.0, "Motorcycles": 10.0, "Buses": 1.0},
            weights={"LPVs": 1.0, "Motorcycles": 0.25, "Buses": 12.0},
            population_base=1000.0,
            saturation_level=1.0,
            passenger_saturation_reached=True,
            bounds={"Motorcycles": (0.05, 0.80), "Buses": (8.0, 30.0)},
        )

        assert result["applied"] is True
        assert result["adjusted_weights"]["Motorcycles"] == pytest.approx(0.80)
        assert result["adjusted_weights"]["Buses"] == pytest.approx(30.0)
        assert result["gap"] < 0.0


class TestReadBaseStocks:
    def test_fuel_rows_do_not_duplicate_vehicle_stock(self):
        t4 = pd.DataFrame([
            {"base_year": 2022, "transport_type": "passenger", "vehicle_type": "LPVs", "size": "medium", "drive_type": "ICE", "fuel": "Motor gasoline", "stock": 100.0},
            {"base_year": 2022, "transport_type": "passenger", "vehicle_type": "LPVs", "size": "medium", "drive_type": "ICE", "fuel": "Diesel", "stock": 100.0},
            {"base_year": 2022, "transport_type": "passenger", "vehicle_type": "LPVs", "size": "medium", "drive_type": "BEV", "fuel": "Electricity", "stock": 25.0},
        ])

        stocks = _read_base_stocks(t4, 2022)

        assert stocks["LPVs"] == 125.0
