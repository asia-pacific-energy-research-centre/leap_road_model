"""
Shared fixtures for road transport model tests.

The test economy is 12_NZ (New Zealand) — small, well-documented,
good for fast iteration.
"""

import pytest
import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

TEST_ECONOMY = "12_NZ"
TEST_BASE_YEAR = 2022
TEST_YEARS = list(range(2022, 2061))
TEST_SCENARIOS = ["Reference", "Target"]

PASSENGER_VEHICLE_TYPES = ["LPVs", "Motorcycles", "Buses"]
FREIGHT_VEHICLE_TYPES = ["Trucks", "LCVs"]


# ---------------------------------------------------------------------------
# Minimal fixtures for Module 3
# ---------------------------------------------------------------------------

@pytest.fixture
def population_series():
    """Synthetic NZ-like population: ~5M growing slowly."""
    years = TEST_YEARS
    pop = 5_000_000 * (1.01 ** np.arange(len(years)))
    return pd.Series(pop, index=years)


@pytest.fixture
def gdp_series():
    """Synthetic GDP series growing at ~2% per year."""
    years = TEST_YEARS
    gdp = 200_000 * (1.02 ** np.arange(len(years)))
    return pd.Series(gdp, index=years)


@pytest.fixture
def passenger_energy_series():
    """
    Synthetic passenger road energy series (PJ).
    Historical: 2010-2022, with COVID dip in 2020-2021.
    """
    historical_years = list(range(2010, 2023))
    base_energy = 50.0
    values = []
    for i, yr in enumerate(historical_years):
        energy = base_energy * (1.025 ** i)
        if yr in (2020, 2021):
            energy *= 0.85  # COVID dip
        values.append(energy)
    return pd.Series(values, index=historical_years)


@pytest.fixture
def freight_energy_series():
    """Synthetic freight road energy series (PJ)."""
    historical_years = list(range(2010, 2023))
    values = [20.0 * (1.03 ** i) for i in range(len(historical_years))]
    return pd.Series(values, index=historical_years)


@pytest.fixture
def base_stocks():
    """Synthetic NZ-like base-year vehicle stock."""
    return {
        "LPVs":        3_000_000,
        "Motorcycles":   150_000,
        "Buses":           8_000,
        "Trucks":         90_000,
        "LCVs":          400_000,
    }


@pytest.fixture
def vehicle_weights():
    """Default vehicle-equivalent weights."""
    return {
        "LPVs": 1.0,
        "Motorcycles": 0.8,
        "Buses": 20.0,
        "Trucks": 5.0,
        "LCVs": 1.5,
    }


@pytest.fixture
def survival_curves():
    """
    Synthetic annual survival probability curves for each vehicle type.

    S_cumulative(a) = exp(-(a/L)^k) (Weibull-like).
    Annual probability: p(a) = S(a+1) / S(a), with p(max_age) = 0.
    """
    curves = {}
    max_age = 30
    L, k = 15.0, 2.0
    ages = np.arange(max_age + 1)
    S = np.exp(-((ages / L) ** k))  # cumulative survival
    annual = np.where(S[:-1] > 0, S[1:] / S[:-1], 0.0)
    annual = np.clip(annual, 0.0, 1.0)
    annual_full = np.append(annual, 0.0)  # last age survives with prob 0
    for vt in PASSENGER_VEHICLE_TYPES + FREIGHT_VEHICLE_TYPES:
        curves[vt] = pd.Series(annual_full, index=ages)
    return curves


@pytest.fixture
def vintage_profiles(survival_curves):
    """
    Steady-state vintage profiles.

    Under steady-state with stationary survival, stock at age a is proportional
    to the cumulative survival S(a). We reconstruct S(a) from annual p(a)
    and normalise to sum 1.
    """
    profiles = {}
    max_age = 30
    L, k_val = 15.0, 2.0
    ages = np.arange(max_age + 1)
    S = np.exp(-((ages / L) ** k_val))  # cumulative survival proportional to stock
    S_norm = S / S.sum()
    for vt in survival_curves:
        profiles[vt] = pd.Series(S_norm, index=ages)
    return profiles
