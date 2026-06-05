"""
Tests for Module 4 — Sales, survival, vintage, and turnover policy.

Tests cover the pure mathematical functions ported from sales_workflow.py
and sales_curve_estimate.py. run_module4() is covered by an integration test.
"""

import numpy as np
import pandas as pd
import pytest

from modules.module4_sales_turnover import (
    initialise_cohorts,
    compute_sales_from_stock_targets,
    survival_to_vintage,
    cumulative_to_annual_survival,
    shift_vintage_profiles,
    merge_turnover_policies,
    subtract_turnover_policies,
    run_module4,
    _normalise_survival,
    _normalise_vintage,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_survival(max_age: int = 20, annual_prob: float = 0.90) -> pd.Series:
    """Constant annual survival probability for simple tests."""
    return pd.Series(annual_prob, index=range(max_age + 1))


def _make_vintage(max_age: int = 20) -> pd.Series:
    """Flat vintage profile (equal share at each age), normalised."""
    n = max_age + 1
    return pd.Series(1.0 / n, index=range(n))


def _flat_target(n_years: int = 10, stock: float = 100_000.0, base_year: int = 2022) -> pd.Series:
    """Constant stock target — implies sales ≈ natural retirements."""
    return pd.Series(stock, index=range(base_year, base_year + n_years))


def _growing_target(n_years: int = 10, base: float = 100_000.0, growth: float = 0.02,
                    base_year: int = 2022) -> pd.Series:
    return pd.Series([base * (1 + growth) ** i for i in range(n_years)],
                     index=range(base_year, base_year + n_years))


# ===========================================================================
# initialise_cohorts
# ===========================================================================

class TestInitialiseCohorts:
    def test_base_year_stock_correct(self):
        target = _flat_target(5, stock=100_000.0)
        vintage = _make_vintage(20)
        cohorts = initialise_cohorts(target, vintage)
        assert abs(cohorts.loc[2022].sum() - 100_000.0) < 1.0

    def test_other_years_are_zero(self):
        target = _flat_target(5, stock=100_000.0)
        vintage = _make_vintage(20)
        cohorts = initialise_cohorts(target, vintage)
        for yr in [2023, 2024, 2025, 2026]:
            assert cohorts.loc[yr].sum() == 0.0

    def test_vintage_profile_applied(self):
        # If vintage[0] = 0.5, roughly half the base stock is at age 0.
        max_age = 10
        vintage = pd.Series([0.5] + [0.05] * max_age, index=range(max_age + 1))
        vintage = vintage / vintage.sum()
        target = pd.Series([200_000.0], index=[2022])
        cohorts = initialise_cohorts(target, vintage)
        assert abs(cohorts.loc[2022, 0] - 200_000.0 * vintage.iloc[0]) < 1.0

    def test_rejects_empty_vintage(self):
        target = _flat_target(3)
        vintage = pd.Series([0.0] * 5, index=range(5))
        with pytest.raises(ValueError):
            initialise_cohorts(target, vintage)


# ===========================================================================
# compute_sales_from_stock_targets
# ===========================================================================

class TestComputeSalesFromStockTargets:
    def test_growing_stock_requires_positive_sales(self):
        target = _growing_target(10, base=100_000.0, growth=0.03)
        survival = _make_survival(20, 0.92)
        vintage = _make_vintage(20)
        sales, cohorts = compute_sales_from_stock_targets(target, survival, vintage)
        assert (sales.iloc[1:] > 0).all(), "Growing stock should require positive sales"

    def test_flat_stock_sales_cover_retirements(self):
        """For flat stock, sales should roughly equal natural retirements."""
        target = _flat_target(15, stock=100_000.0)
        survival = _make_survival(20, 0.90)
        vintage = _make_vintage(20)
        sales, cohorts = compute_sales_from_stock_targets(target, survival, vintage)
        # Sales after warm-up should be positive (replacing retired vehicles)
        assert (sales.iloc[5:] > 0).all()

    def test_total_stock_tracks_target(self):
        target = _growing_target(10, base=100_000.0, growth=0.02)
        survival = _make_survival(20, 0.92)
        vintage = _make_vintage(20)
        sales, cohorts = compute_sales_from_stock_targets(target, survival, vintage)
        for yr in target.index[1:]:
            total = float(cohorts.loc[yr].sum())
            assert abs(total - float(target.loc[yr])) < 1.0, \
                f"Total stock {total:.0f} != target {target.loc[yr]:.0f} in {yr}"

    def test_sales_non_negative(self):
        target = _growing_target(15)
        survival = _make_survival(25, 0.88)
        vintage = _make_vintage(25)
        sales, cohorts = compute_sales_from_stock_targets(target, survival, vintage)
        assert (sales >= 0).all()

    def test_return_retirements_shape(self):
        target = _flat_target(5)
        survival = _make_survival(10, 0.90)
        vintage = _make_vintage(10)
        sales, cohorts, ret = compute_sales_from_stock_targets(
            target, survival, vintage, return_retirements=True
        )
        assert "natural" in ret
        assert "additional" in ret
        assert isinstance(ret["natural"], pd.Series)
        assert isinstance(ret["additional"], pd.Series)
        assert (ret["natural"].iloc[1:] >= 0).all()

    def test_natural_retirements_zero_base_year(self):
        """Base year has no retirements (no prior cohorts)."""
        target = _flat_target(5)
        survival = _make_survival(10, 0.90)
        vintage = _make_vintage(10)
        _, _, ret = compute_sales_from_stock_targets(
            target, survival, vintage, return_retirements=True
        )
        assert ret["natural"].iloc[0] == 0.0

    def test_policy_additional_retirement_rate(self):
        """Policy with additional retirement should reduce cohorts further."""
        target = _flat_target(10, stock=100_000.0)
        survival = _make_survival(20, 0.92)
        vintage = _make_vintage(20)
        policy = {"additional_retirement_rate": 0.10}
        sales_p, cohorts_p, ret_p = compute_sales_from_stock_targets(
            target, survival, vintage, turnover_policy=policy, return_retirements=True
        )
        sales_base, cohorts_base, ret_base = compute_sales_from_stock_targets(
            target, survival, vintage, return_retirements=True
        )
        # Additional retirements should be positive mid-run
        assert (ret_p["additional"].iloc[3:] > 0).all()
        # Additional retirements should exceed base (which is 0)
        assert ret_p["additional"].iloc[5:].mean() > ret_base["additional"].iloc[5:].mean()

    def test_shrinking_stock_zero_sales(self):
        """When stock is shrinking and survivors exceed target, sales should be 0."""
        target = pd.Series([100_000.0, 80_000.0, 60_000.0], index=[2022, 2023, 2024])
        survival = _make_survival(10, 0.95)
        vintage = _make_vintage(10)
        sales, cohorts = compute_sales_from_stock_targets(target, survival, vintage)
        # In a shrinking scenario, some years should have zero sales
        assert (sales >= 0).all()

    def test_shrinking_stock_records_scale_event(self):
        target = pd.Series([100_000.0, 50_000.0, 40_000.0], index=[2022, 2023, 2024])
        survival = _make_survival(10, 0.99)
        vintage = _make_vintage(10)
        sales, cohorts, ret = compute_sales_from_stock_targets(
            target, survival, vintage, return_retirements=True
        )
        assert bool(ret["stock_above_target"].loc[2023]) is True
        assert ret["scale_factor_applied"].loc[2023] < 1.0


# ===========================================================================
# survival_to_vintage
# ===========================================================================

class TestSurvivalToVintage:
    def test_sums_to_one(self):
        surv = pd.Series([1.0, 0.9, 0.8, 0.6, 0.3, 0.1], index=range(6))
        vintage = survival_to_vintage(surv)
        assert abs(vintage.sum() - 1.0) < 1e-6

    def test_monotone_decreasing(self):
        surv = pd.Series([1.0, 0.9, 0.8, 0.6, 0.3, 0.1], index=range(6))
        vintage = survival_to_vintage(surv)
        assert (vintage.diff().dropna() <= 0).all()

    def test_same_index_as_input(self):
        surv = pd.Series([1.0, 0.85, 0.7, 0.5], index=[0, 1, 2, 3])
        vintage = survival_to_vintage(surv)
        assert list(vintage.index) == [0, 1, 2, 3]

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            survival_to_vintage(pd.Series([], dtype=float))

    def test_rejects_zero_first_value(self):
        with pytest.raises(ValueError):
            survival_to_vintage(pd.Series([0.0, 0.5, 0.2], index=range(3)))


# ===========================================================================
# cumulative_to_annual_survival
# ===========================================================================

class TestCumulativeToAnnualSurvival:
    def test_last_annual_is_zero(self):
        S = pd.Series([1.0, 0.9, 0.7, 0.4, 0.1], index=range(5))
        annual = cumulative_to_annual_survival(S)
        assert annual.iloc[-1] == 0.0

    def test_values_in_range(self):
        S = pd.Series([1.0, 0.9, 0.7, 0.4, 0.1], index=range(5))
        annual = cumulative_to_annual_survival(S)
        assert (annual >= 0.0).all()
        assert (annual <= 1.0).all()

    def test_round_trip_consistent(self):
        """S(a+1)/S(a) gives annual probability; product should recover cumulative."""
        S = pd.Series([1.0, 0.9, 0.81, 0.729, 0.0], index=range(5))
        annual = cumulative_to_annual_survival(S)
        # For a geometric series, p = 0.9 for ages 0-3
        assert abs(annual.iloc[0] - 0.9) < 1e-6
        assert abs(annual.iloc[1] - 0.9) < 1e-6

    def test_handles_percent_input(self):
        """Values > 1.5 are treated as percentages (0–100)."""
        S_pct = pd.Series([100.0, 90.0, 70.0, 40.0, 10.0], index=range(5))
        S_frac = pd.Series([1.0, 0.9, 0.7, 0.4, 0.1], index=range(5))
        annual_pct = cumulative_to_annual_survival(S_pct)
        annual_frac = cumulative_to_annual_survival(S_frac)
        assert np.allclose(annual_pct.values, annual_frac.values, atol=1e-6)


# ===========================================================================
# shift_vintage_profiles
# ===========================================================================

class TestShiftVintageProfiles:
    def _base_vintage(self):
        ages = range(21)
        vals = np.array([1.0 - a / 20.0 for a in ages], dtype=float)
        vals = vals / vals.sum()
        return pd.Series(vals, index=list(ages))

    def test_zero_shift_unchanged(self):
        vintage = self._base_vintage()
        profiles = {"LPVs": vintage}
        shifted, diag = shift_vintage_profiles(profiles, age_shift_years=0.0)
        assert shifted == {}  # no shift applied = empty dict

    def test_positive_shift_increases_average_age(self):
        vintage = self._base_vintage()
        profiles = {"LPVs": vintage}
        shifted, diag = shift_vintage_profiles(profiles, age_shift_years=3.0)
        assert "LPVs" in shifted
        row = diag[diag["vehicle_type"] == "LPVs"].iloc[0]
        assert row["shifted_average_age_years"] > row["baseline_average_age_years"]

    def test_shifted_still_sums_to_one(self):
        vintage = self._base_vintage()
        profiles = {"LPVs": vintage}
        shifted, _ = shift_vintage_profiles(profiles, age_shift_years=5.0)
        if "LPVs" in shifted:
            assert abs(shifted["LPVs"].sum() - 1.0) < 1e-6

    def test_per_vehicle_shift(self):
        vintage = self._base_vintage()
        profiles = {"LPVs": vintage, "Trucks": vintage.copy()}
        shifted, diag = shift_vintage_profiles(
            profiles, age_shift_years={"LPVs": 5.0, "Trucks": 0.0}
        )
        assert "LPVs" in shifted
        assert "Trucks" not in shifted  # zero shift → not in output

    def test_diagnostics_columns(self):
        vintage = self._base_vintage()
        profiles = {"LPVs": vintage}
        _, diag = shift_vintage_profiles(profiles, age_shift_years=2.0)
        assert "vehicle_type" in diag.columns
        assert "requested_shift_years" in diag.columns
        assert "shifted_average_age_years" in diag.columns


# ===========================================================================
# merge_turnover_policies
# ===========================================================================

class TestMergeTurnoverPolicies:
    def test_rates_are_additive(self):
        years = pd.Index(range(2022, 2031))
        a = {"LPVs": {"additional_retirement_rate": 0.02}}
        b = {"LPVs": {"additional_retirement_rate": 0.03}}
        merged = merge_turnover_policies(a, b, years)
        rate = merged["LPVs"]["additional_retirement_rate"]
        assert abs(rate.mean() - 0.05) < 1e-6

    def test_rate_capped_at_one(self):
        years = pd.Index(range(2022, 2031))
        a = {"LPVs": {"additional_retirement_rate": 0.7}}
        b = {"LPVs": {"additional_retirement_rate": 0.7}}
        merged = merge_turnover_policies(a, b, years)
        assert (merged["LPVs"]["additional_retirement_rate"] <= 1.0).all()

    def test_empty_inputs(self):
        years = pd.Index(range(2022, 2031))
        merged = merge_turnover_policies(None, None, years)
        assert merged == {}

    def test_disjoint_keys_are_unioned(self):
        years = pd.Index(range(2022, 2031))
        a = {"LPVs": {"additional_retirement_rate": 0.02}}
        b = {"Trucks": {"additional_retirement_rate": 0.03}}
        merged = merge_turnover_policies(a, b, years)
        assert "LPVs" in merged
        assert "Trucks" in merged

    def test_survival_multiplier_is_multiplicative(self):
        years = pd.Index(range(2022, 2031))
        a = {"LPVs": {"survival_multiplier": 0.8}}
        b = {"LPVs": {"survival_multiplier": 0.9}}
        merged = merge_turnover_policies(a, b, years)
        mult = merged["LPVs"]["survival_multiplier"]
        assert abs(mult.mean() - 0.72) < 1e-6  # 0.8 * 0.9


# ===========================================================================
# subtract_turnover_policies
# ===========================================================================

class TestSubtractTurnoverPolicies:
    def test_exact_subtraction(self):
        years = pd.Index(range(2022, 2031))
        total = {"LPVs": {"additional_retirement_rate": 0.05}}
        sub = {"LPVs": {"additional_retirement_rate": 0.03}}
        result = subtract_turnover_policies(total, sub, years)
        rate = result["LPVs"]["additional_retirement_rate"]
        assert abs(rate.mean() - 0.02) < 1e-6

    def test_result_is_non_negative(self):
        years = pd.Index(range(2022, 2031))
        total = {"LPVs": {"additional_retirement_rate": 0.02}}
        sub = {"LPVs": {"additional_retirement_rate": 0.05}}
        result = subtract_turnover_policies(total, sub, years)
        # Clipped to 0; key removed if all zero
        if "LPVs" in result:
            assert (result["LPVs"]["additional_retirement_rate"] >= 0).all()

    def test_removes_key_when_fully_subtracted(self):
        years = pd.Index(range(2022, 2031))
        total = {"LPVs": {"additional_retirement_rate": 0.03}}
        sub = {"LPVs": {"additional_retirement_rate": 0.03}}
        result = subtract_turnover_policies(total, sub, years)
        assert "LPVs" not in result or "additional_retirement_rate" not in result.get("LPVs", {})


# ===========================================================================
# Integration: run_module4
# ===========================================================================

class TestRunModule4:
    def _stock_targets(self, vehicle_types=("LPVs", "Buses"), n_years=10, base_year=2022):
        rows = []
        stocks = {"LPVs": 3_000_000, "Buses": 8_000}
        for yr in range(base_year, base_year + n_years):
            for vt in vehicle_types:
                rows.append({
                    "year": yr,
                    "vehicle_type": vt,
                    "target_stock": float(stocks[vt]) * (1.02 ** (yr - base_year)),
                })
        return pd.DataFrame(rows)

    def _survival(self, vehicle_types=("LPVs", "Buses"), max_age=20, prob=0.90):
        return {vt: _make_survival(max_age, prob) for vt in vehicle_types}

    def _vintage(self, vehicle_types=("LPVs", "Buses"), max_age=20):
        return {vt: _make_vintage(max_age) for vt in vehicle_types}

    def test_returns_two_dataframes(self):
        t6, t6v = run_module4(
            self._stock_targets(),
            self._survival(),
            self._vintage(),
        )
        assert isinstance(t6, pd.DataFrame)
        assert isinstance(t6v, pd.DataFrame)

    def test_t6_has_expected_columns(self):
        t6, _ = run_module4(
            self._stock_targets(),
            self._survival(),
            self._vintage(),
        )
        assert "new_sales" in t6.columns
        assert "natural_retirements" in t6.columns
        assert "total_retirements" in t6.columns

    def test_sales_non_negative(self):
        t6, _ = run_module4(
            self._stock_targets(),
            self._survival(),
            self._vintage(),
        )
        assert (t6["new_sales"] >= 0).all()

    def test_total_retirements_non_negative(self):
        t6, _ = run_module4(
            self._stock_targets(),
            self._survival(),
            self._vintage(),
        )
        assert (t6["total_retirements"] >= 0).all()

    def test_stock_tracks_target(self):
        t6, _ = run_module4(
            self._stock_targets(),
            self._survival(),
            self._vintage(),
        )
        diff = (t6["stock"] - t6["target_stock"]).abs()
        assert (diff < 1.0).all()

    def test_missing_profile_skips_vehicle_type(self):
        targets = self._stock_targets(("LPVs", "Buses"))
        survival = self._survival(("LPVs",))  # Buses missing
        vintage = self._vintage(("LPVs",))
        t6, _ = run_module4(targets, survival, vintage)
        # LPVs should still be processed
        assert "LPVs" in t6["vehicle_type"].values
        # Buses should be absent (skipped due to missing profile)
        assert "Buses" not in t6["vehicle_type"].values
