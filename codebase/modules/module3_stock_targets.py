"""
Module 3 — Stock target projection.

Derives annual target vehicle stocks before the survival, vintage, and sales
module is applied.

Passenger stocks use a logistic / Gompertz-style motorisation curve calibrated
from recent historical energy growth.

Freight stocks use GDP elasticity calibrated from recent historical energy
and GDP growth.

Both exclude COVID-affected years (2020–2022) from trend estimation.

Outputs: T5_stock_targets DataFrame.

Core logic ported from:
    leap_transport/codebase/functions/sales_curve_estimate.py
    leap_transport/codebase/sales_workflow.py
"""

from __future__ import annotations

import logging
import warnings
from typing import Collection

import numpy as np
import pandas as pd

from diagnostics.module_charts import write_module3_charts
from schemas.validation import validate_table

log = logging.getLogger(__name__)

# Default config values (overridden by model_defaults.yaml in run_module3)
_DEFAULTS = {
    "k_min": 0.0,
    "k_max": 0.15,
    "lookback_window_years": 10,
    "covid_exclude_years": [2020, 2021, 2022],
    "saturation_fallback_multiplier": 3.0,
    "saturation_already_reached_threshold": 0.95,
    "elasticity_min": 0.0,
    "elasticity_max": 2.0,
    "default_elasticity": 0.8,
}


# ===========================================================================
# Public API
# ===========================================================================

def run_module3(
    base_year_branches: pd.DataFrame,
    population: pd.Series,
    gdp: pd.Series,
    esto_road_energy_pj: pd.DataFrame,
    projection_years: Collection[int],
    vehicle_type_shares: dict[str, pd.Series] | None = None,
    saturation_overrides: dict[str, float] | None = None,
    elasticity_overrides: dict[str, float] | None = None,
    vehicle_equivalent_weights: dict[str, float] | None = None,
    config: dict | None = None,
    diagnostics_dir: str | None = None,
    economy: str = "",
    scenario: str = "",
) -> pd.DataFrame:
    """
    Run Module 3: project passenger and freight target stocks.

    Args:
        base_year_branches: T4_base_year_branches from Module 2. Used to read
            base-year stock by vehicle type.
        population: pd.Series indexed by year (persons).
        gdp: pd.Series indexed by year (consistent units).
        esto_road_energy_pj: DataFrame with columns [year, transport_type, energy_pj].
            Used for energy trend calibration.
        projection_years: Years to project over (e.g. range(2022, 2061)).
        vehicle_type_shares: Optional dict mapping vehicle_type → pd.Series indexed
            by year giving the share of total passenger/freight stock for that type.
            If None, shares are held constant at base-year proportions.
        saturation_overrides: Optional dict mapping vehicle_type → saturation
            motorisation level (car-equiv per capita). Overrides default fallback.
        elasticity_overrides: Optional dict mapping vehicle_type → GDP elasticity.
            Overrides estimated elasticity.
        vehicle_equivalent_weights: Optional dict mapping vehicle_type → weight.
            Defaults to values in model_defaults.yaml.
        config: Optional dict overriding _DEFAULTS.
        diagnostics_dir: Optional directory root for Module 3 PNG diagnostic
            charts. When provided, charts are written to
            diagnostics_dir/module3/.

    Returns:
        T5_stock_targets DataFrame.
    """
    cfg = {**_DEFAULTS, **(config or {})}
    weights = vehicle_equivalent_weights or {
        "LPVs": 1.0, "Motorcycles": 0.8, "Buses": 20.0,
        "Trucks": 5.0, "LCVs": 1.5,
    }

    years = sorted(projection_years)
    base_year = years[0]

    base_stocks = _read_base_stocks(base_year_branches, base_year)
    log.info("Base stocks: %s", base_stocks)

    passenger_types = ["LPVs", "Motorcycles", "Buses"]
    freight_types = ["Trucks", "LCVs"]

    # Passenger projection
    pax_energy = _extract_energy(esto_road_energy_pj, "passenger", cfg)
    pax_stocks = project_passenger_stocks(
        years=years,
        population=population,
        energy_series=pax_energy,
        base_stocks={vt: base_stocks.get(vt, 0.0) for vt in passenger_types},
        weights=weights,
        vehicle_type_shares=vehicle_type_shares,
        saturation_overrides=saturation_overrides or {},
        cfg=cfg,
    )

    # Freight projection
    frt_energy = _extract_energy(esto_road_energy_pj, "freight", cfg)
    frt_stocks = project_freight_stocks(
        years=years,
        gdp=gdp,
        energy_series=frt_energy,
        base_stocks={vt: base_stocks.get(vt, 0.0) for vt in freight_types},
        elasticity_overrides=elasticity_overrides or {},
        cfg=cfg,
    )

    _year_set = set(years)
    rows = []
    for transport_type, stocks_dict in [("passenger", pax_stocks), ("freight", frt_stocks)]:
        for vt, series in stocks_dict["target_stocks"].items():
            for yr, val in series.items():
                if yr not in _year_set:
                    continue
                row = {
                    "economy": economy,
                    "scenario": scenario,
                    "year": yr,
                    "transport_type": transport_type,
                    "vehicle_type": vt,
                    "target_stock": val,
                }
                if transport_type == "passenger":
                    row["motorisation_level"] = stocks_dict["M_envelope"].get(yr)
                    row["saturation_level"] = stocks_dict["M_sat"]
                    row["k_used"] = stocks_dict["k_used"]
                    row["k_clamped"] = stocks_dict["k_clamped"]
                    row["is_saturated"] = stocks_dict["is_saturated"]
                    row["saturation_source_flag"] = stocks_dict["saturation_source_flag"]
                else:
                    row["gdp_elasticity_used"] = stocks_dict["elasticities"].get(vt)
                rows.append(row)

    result = pd.DataFrame(rows)
    errors = validate_table(result, "T5_stock_targets")
    for err in errors:
        log.warning("Validation: %s", err)

    if diagnostics_dir is not None:
        try:
            written = write_module3_charts(result, diagnostics_dir)
            log.info("Module 3 diagnostics: wrote %d chart(s)", len(written))
        except Exception as exc:
            log.warning("Module 3 diagnostics chart generation failed: %s", exc)

    return result


# ===========================================================================
# Passenger stock projection
# ===========================================================================

def project_passenger_stocks(
    years: list[int],
    population: pd.Series,
    energy_series: pd.Series,
    base_stocks: dict[str, float],
    weights: dict[str, float],
    vehicle_type_shares: dict[str, pd.Series] | None = None,
    saturation_overrides: dict[str, float] | None = None,
    cfg: dict | None = None,
) -> dict:
    """
    Project passenger target stocks using a logistic motorisation envelope.

    Args:
        years: List of years to project.
        population: pd.Series indexed by year (persons).
        energy_series: pd.Series indexed by year (PJ), passenger road energy.
            Used to calibrate S-curve steepness k.
        base_stocks: Dict mapping vehicle_type → base-year vehicle count.
        weights: Vehicle-equivalent weights per vehicle type.
        vehicle_type_shares: Optional time-varying shares per vehicle type.
        saturation_overrides: Optional economy-specific saturation levels.
        cfg: Config dict with k_min, k_max, lookback_window_years, etc.

    Returns:
        Dict with keys: M_envelope, M_sat, M_base, k_used, k_clamped,
        is_saturated, saturation_source_flag, target_stocks, vehicle_type_shares.
    """
    cfg = cfg or _DEFAULTS
    base_year = years[0]

    M_base, capacity_shares = compute_motorisation_base(
        base_stocks, weights, population[base_year]
    )
    log.info("Base-year motorisation M_base=%.4f car-equiv/capita", M_base)

    M_sat, sat_source = resolve_saturation(
        M_base,
        saturation_overrides=saturation_overrides or {},
        fallback_multiplier=cfg["saturation_fallback_multiplier"],
    )
    log.info("Saturation level M_sat=%.4f (source: %s)", M_sat, sat_source)

    is_saturated = M_base >= cfg["saturation_already_reached_threshold"] * M_sat

    if is_saturated:
        k = 0.0
        k_clamped = False
        log.info("Economy treated as saturated — k set to 0.0")
    else:
        g_E = estimate_recent_energy_growth(
            energy_series,
            lookback_years=cfg["lookback_window_years"],
            base_year=base_year,
            exclude_years=cfg["covid_exclude_years"],
        )
        k, k_clamped = estimate_passenger_k(
            g_E, M_base, M_sat,
            k_min=cfg["k_min"], k_max=cfg["k_max"],
        )
        log.info("Estimated k=%.4f (clamped=%s, g_E=%.4f)", k, k_clamped, g_E)
        if k_clamped:
            log.warning("k was clamped to bounds — flag for review")

    M_envelope = project_motorisation_envelope(
        base_year=base_year,
        projection_years=years,
        M_base=M_base,
        M_sat=M_sat,
        k=k,
        population=population,
    )

    # Constant base-year X-LPV-equivalent shares if not supplied.  The
    # motorisation envelope is in weighted vehicle-equivalents, so convert each
    # vehicle type back to physical vehicles after allocation.
    if vehicle_type_shares is None:
        vehicle_type_shares = {
            vt: pd.Series(capacity_shares.get(vt, 0.0), index=years)
            for vt in base_stocks
        }

    total_target_stock = M_envelope * population
    target_stocks = {
        vt: (total_target_stock * shares) / weights.get(vt, 1.0)
        for vt, shares in vehicle_type_shares.items()
        if vt in base_stocks
    }

    return {
        "M_envelope": M_envelope,
        "M_sat": M_sat,
        "M_base": M_base,
        "k_used": k,
        "k_clamped": k_clamped,
        "is_saturated": is_saturated,
        "saturation_source_flag": sat_source,
        "target_stocks": target_stocks,
        "vehicle_type_shares": vehicle_type_shares,
    }


def compute_motorisation_base(
    base_stocks: dict[str, float],
    weights: dict[str, float],
    population_base: float,
) -> tuple[float, dict[str, float]]:
    """
    Calculate base-year motorisation level M_base (car-equiv per capita).

    Also returns capacity-weighted shares per vehicle type.

    Args:
        base_stocks: Dict mapping vehicle_type → vehicle count.
        weights: Dict mapping vehicle_type → vehicle-equivalent weight.
        population_base: Base-year population (persons).

    Returns:
        (M_base, capacity_shares) where M_base is car-equivalents per capita
        and capacity_shares is a dict of shares.
    """
    weighted_total = sum(
        count * weights.get(vt, 1.0)
        for vt, count in base_stocks.items()
    )
    M_base = weighted_total / population_base if population_base > 0 else 0.0

    capacity_shares = {
        vt: (count * weights.get(vt, 1.0)) / (weighted_total or 1.0)
        for vt, count in base_stocks.items()
    }
    return M_base, capacity_shares


def estimate_recent_energy_growth(
    energy_series: pd.Series,
    lookback_years: int,
    base_year: int,
    exclude_years: Collection[int] | None = None,
) -> float:
    """
    Estimate recent average annual log growth rate of road energy.

    g_E = mean(log(E[t] / E[t-1])) over the lookback window,
    excluding COVID-affected years.

    Args:
        energy_series: pd.Series indexed by year (PJ or any consistent unit).
        lookback_years: Number of years before base_year to look back.
        base_year: The base year (end of the lookback window).
        exclude_years: Years to exclude (e.g. [2020, 2021, 2022]).

    Returns:
        Average annual log growth rate (float). Returns 0.0 if insufficient data.
    """
    exclude = set(exclude_years or [])
    window_start = base_year - lookback_years
    mask = (
        (energy_series.index >= window_start) &
        (energy_series.index <= base_year) &
        (~energy_series.index.isin(exclude))
    )
    filtered = energy_series[mask].dropna().sort_index()

    if len(filtered) < 2:
        log.warning(
            "Insufficient energy data for trend estimation "
            "(got %d points after exclusions)", len(filtered)
        )
        return 0.0

    log_growth = np.log(filtered / filtered.shift(1)).dropna()
    return float(log_growth.mean())


def estimate_passenger_k(
    g_E: float,
    M_base: float,
    M_sat: float,
    k_min: float = 0.0,
    k_max: float = 0.15,
) -> tuple[float, bool]:
    """
    Estimate S-curve steepness k from recent energy growth rate.

    k ≈ g_E / (1 - M_base / M_sat)

    Args:
        g_E: Recent average annual log growth rate of passenger road energy.
        M_base: Base-year motorisation level (car-equiv per capita).
        M_sat: Saturation motorisation level (car-equiv per capita).
        k_min: Minimum allowed k (default 0.0).
        k_max: Maximum allowed k (default 0.15).

    Returns:
        (k, clamped) where k is the estimated steepness and clamped is True
        if k was forced to the boundary.
    """
    if M_sat <= 0 or M_base >= M_sat:
        return k_min, True

    remaining_fraction = 1.0 - M_base / M_sat
    if remaining_fraction <= 0:
        return k_min, True

    k_raw = g_E / remaining_fraction
    k_clamped = float(np.clip(k_raw, k_min, k_max))
    was_clamped = not np.isclose(k_raw, k_clamped)
    return k_clamped, was_clamped


def project_motorisation_envelope(
    base_year: int,
    projection_years: list[int],
    M_base: float,
    M_sat: float,
    k: float,
    population: pd.Series | None = None,
) -> pd.Series:
    """
    Project motorisation envelope M(year) using a logistic curve.

    M(year) = M_sat / (1 + exp(-k * (year - y0)))

    where y0 is chosen so that M(base_year) = M_base.

    If k == 0, M is held constant at M_base.

    Args:
        base_year: Base year.
        projection_years: List of years to project.
        M_base: Base-year motorisation (car-equiv per capita).
        M_sat: Saturation level (car-equiv per capita).
        k: S-curve steepness parameter.
        population: Ignored here (kept for interface consistency). Total
            passenger stock is computed outside this function.

    Returns:
        pd.Series indexed by year with motorisation level values.
    """
    years = np.array(sorted(projection_years))

    if k == 0.0 or M_sat <= 0:
        return pd.Series(M_base, index=years)

    # Solve for y0: M_base = M_sat / (1 + exp(-k * (base_year - y0)))
    # => 1 + exp(-k * (base_year - y0)) = M_sat / M_base
    # => -k * (base_year - y0) = log(M_sat / M_base - 1)
    # => y0 = base_year + log(M_sat / M_base - 1) / k
    ratio = M_sat / M_base - 1.0
    if ratio <= 0:
        return pd.Series(M_base, index=years)

    y0 = base_year + np.log(ratio) / k
    M_values = M_sat / (1.0 + np.exp(-k * (years - y0)))

    return pd.Series(M_values, index=years)


def resolve_saturation(
    M_base: float,
    saturation_overrides: dict[str, float],
    fallback_multiplier: float = 3.0,
) -> tuple[float, str]:
    """
    Resolve the saturation motorisation level.

    Priority:
    1. Researcher-provided saturation (passed in saturation_overrides).
    2. Default fallback: M_base × fallback_multiplier.

    Args:
        M_base: Base-year motorisation level.
        saturation_overrides: Dict that may contain key 'global' or economy code.
        fallback_multiplier: Multiplier for default saturation.

    Returns:
        (M_sat, source_flag).
    """
    if "researcher" in saturation_overrides:
        return saturation_overrides["researcher"], "researcher"
    if "global" in saturation_overrides:
        return saturation_overrides["global"], "regional_default"

    M_sat = max(M_base * fallback_multiplier, M_base + 1e-6)
    return M_sat, "fallback"


# ===========================================================================
# Freight stock projection
# ===========================================================================

def project_freight_stocks(
    years: list[int],
    gdp: pd.Series,
    energy_series: pd.Series,
    base_stocks: dict[str, float],
    elasticity_overrides: dict[str, float] | None = None,
    cfg: dict | None = None,
) -> dict:
    """
    Project freight target stocks using GDP elasticity.

    target_stock(y) = base_stock × (GDP(y) / GDP_base) ^ elasticity

    Args:
        years: List of years to project.
        gdp: pd.Series indexed by year.
        energy_series: pd.Series indexed by year (PJ), freight road energy.
        base_stocks: Dict mapping vehicle_type → base-year count.
        elasticity_overrides: Optional dict mapping vehicle_type → override elasticity.
        cfg: Config dict.

    Returns:
        Dict with keys: elasticities, target_stocks.
    """
    cfg = cfg or _DEFAULTS
    overrides = elasticity_overrides or {}
    base_year = years[0]
    gdp_base = float(gdp[base_year])

    elasticity = estimate_freight_elasticity(
        energy_series,
        gdp,
        lookback_years=cfg["lookback_window_years"],
        base_year=base_year,
        exclude_years=cfg["covid_exclude_years"],
        elasticity_min=cfg["elasticity_min"],
        elasticity_max=cfg["elasticity_max"],
        default_elasticity=cfg["default_elasticity"],
    )
    log.info("Estimated freight GDP elasticity: %.4f", elasticity)

    target_stocks = {}
    elasticities = {}
    for vt, base_stock in base_stocks.items():
        e = overrides.get(vt, elasticity)
        elasticities[vt] = e
        gdp_ratio = gdp / gdp_base
        target_stocks[vt] = pd.Series(
            base_stock * (gdp_ratio ** e),
            index=gdp_ratio.index,
        ).reindex(years)

    return {"elasticities": elasticities, "target_stocks": target_stocks}


def estimate_freight_elasticity(
    energy_series: pd.Series,
    gdp: pd.Series,
    lookback_years: int,
    base_year: int,
    exclude_years: Collection[int] | None = None,
    elasticity_min: float = 0.0,
    elasticity_max: float = 2.0,
    default_elasticity: float = 0.8,
) -> float:
    """
    Estimate freight stock elasticity from historical energy and GDP growth.

    elasticity = average_freight_energy_growth / average_gdp_growth

    Both are geometric average annual growth rates over the lookback window.

    Args:
        energy_series: pd.Series indexed by year (freight road energy, PJ).
        gdp: pd.Series indexed by year.
        lookback_years: Years to look back from base_year.
        base_year: End of the lookback window.
        exclude_years: Years to exclude (e.g. [2020, 2021, 2022]).
        elasticity_min: Minimum allowed elasticity.
        elasticity_max: Maximum allowed elasticity.
        default_elasticity: Fallback if data are insufficient.

    Returns:
        Freight GDP elasticity (float).
    """
    exclude = set(exclude_years or [])
    window_start = base_year - lookback_years

    def _geometric_growth(series: pd.Series) -> float | None:
        mask = (
            (series.index >= window_start) &
            (series.index <= base_year) &
            (~series.index.isin(exclude))
        )
        s = series[mask].dropna().sort_index()
        if len(s) < 2 or s.iloc[0] <= 0:
            return None
        n = len(s) - 1
        return float((s.iloc[-1] / s.iloc[0]) ** (1 / n) - 1)

    energy_growth = _geometric_growth(energy_series)
    gdp_growth = _geometric_growth(gdp)

    if energy_growth is None or gdp_growth is None:
        log.warning("Insufficient data for freight elasticity estimation — using default %.2f", default_elasticity)
        return default_elasticity

    if abs(gdp_growth) < 1e-6:
        log.warning("Near-zero GDP growth — using default freight elasticity %.2f", default_elasticity)
        return default_elasticity

    raw_elasticity = energy_growth / gdp_growth
    clamped = float(np.clip(raw_elasticity, elasticity_min, elasticity_max))
    if not np.isclose(raw_elasticity, clamped):
        log.warning(
            "Freight elasticity clamped from %.4f to %.4f — flag for review",
            raw_elasticity, clamped,
        )
    return clamped


# ===========================================================================
# Internal helpers
# ===========================================================================

def _read_base_stocks(base_year_branches: pd.DataFrame, base_year: int) -> dict[str, float]:
    """Sum base-year stock by vehicle_type from T4 table.

    T4 is fuel-level, so multi-fuel drive stocks appear once per fuel.  Count
    each vehicle branch once before aggregating to avoid inflating stocks.
    """
    if "base_year" in base_year_branches.columns:
        df = base_year_branches[base_year_branches["base_year"] == base_year]
    else:
        df = base_year_branches

    if "stock" not in df.columns:
        log.warning("No 'stock' column in base_year_branches — returning zero stocks")
        return {}

    branch_keys = [
        c for c in ["transport_type", "vehicle_type", "size", "drive_type"]
        if c in df.columns
    ]
    if branch_keys:
        df = df.drop_duplicates(subset=branch_keys)

    return df.groupby("vehicle_type")["stock"].sum().to_dict()


def _extract_energy(
    esto_energy: pd.DataFrame,
    transport_type: str,
    cfg: dict,
) -> pd.Series:
    """Extract a total energy series by year for the given transport type."""
    if "transport_type" not in esto_energy.columns:
        return pd.Series(dtype=float)
    mask = esto_energy["transport_type"] == transport_type
    return esto_energy[mask].groupby("year")["energy_pj"].sum()
