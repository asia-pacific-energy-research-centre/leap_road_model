"""
Module 3 - Stock target projection.

Derives annual target vehicle stocks before the survival, vintage, and sales
module is applied.

Passenger stocks use a GDP-per-capita income-elasticity method, damped as
vehicle-equivalent ownership approaches saturation.

Freight stocks use GDP elasticity calibrated from recent historical energy
and GDP growth.

Both exclude COVID-affected years (2020-2022) from trend estimation.

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

# Local fallback config values. Prefer explicit Module 1/config inputs where available.
_DEFAULTS = {
    "k_min": 0.0,
    "k_max": 0.15,
    "lookback_window_years": 10,
    "covid_exclude_years": [2020, 2021, 2022],
    "saturation_fallback_multiplier": 3.0,
    "saturation_already_reached_threshold": 0.95,
    # If weight calibration falls short of M_sat by more than this fraction of
    # the target, M_sat is reduced to M_base so the projection stays flat at the
    # actual achieved level rather than projecting toward an unreachable ceiling.
    "saturation_calibration_fallback_threshold": 0.05,
    "passenger_stock_growth_rate_adjustment": 1.2,
    "passenger_income_elasticity_min": 0.0,
    "passenger_income_elasticity_max": 2.0,
    "passenger_default_income_elasticity": 0.8,
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
    passenger_saturation_reached: bool = False,
    elasticity_overrides: dict[str, float] | None = None,
    elasticity_adjustments: dict[str, float] | None = None,
    vehicle_equivalent_weights: dict[str, float] | None = None,
    vehicle_equivalent_weight_bounds: dict[str, tuple[float, float]] | None = None,
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
        vehicle_type_shares: Optional dict mapping vehicle_type -> pd.Series indexed
            by year giving the share of total passenger/freight stock for that type.
            If None, shares are held constant at base-year proportions.
        saturation_overrides: Optional dict mapping vehicle_type -> saturation
            motorisation level (car-equiv per capita). Overrides default fallback.
        elasticity_overrides: Optional dict mapping vehicle_type -> GDP elasticity.
            Overrides estimated elasticity.
        elasticity_adjustments: Optional dict mapping vehicle_type -> multiplier
            applied to the estimated GDP elasticity before clamping.
        vehicle_equivalent_weights: Optional dict mapping vehicle_type -> weight.
            Defaults to local fallback vehicle-equivalent weights.
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
        gdp=gdp,
        energy_series=pax_energy,
        base_stocks={vt: base_stocks.get(vt, 0.0) for vt in passenger_types},
        weights=weights,
        vehicle_type_shares=vehicle_type_shares,
        saturation_overrides=saturation_overrides or {},
        passenger_saturation_reached=passenger_saturation_reached,
        vehicle_equivalent_weight_bounds=vehicle_equivalent_weight_bounds,
        growth_rate_adjustment=float(cfg.get("passenger_stock_growth_rate_adjustment", 1.0)),
        cfg=cfg,
    )

    # Freight projection
    frt_energy = _extract_energy(esto_road_energy_pj, "freight", cfg)
    frt_stocks = project_freight_stocks(
        years=years,
        gdp=gdp,
        energy_series=frt_energy,
        base_stocks={vt: base_stocks.get(vt, 0.0) for vt in freight_types},
        vehicle_type_shares=vehicle_type_shares,
        elasticity_overrides=elasticity_overrides or {},
        elasticity_adjustments=elasticity_adjustments or {},
        cfg=cfg,
    )

    _year_set = set(years)
    gdp_base_value = gdp.get(base_year, pd.NA)
    rows = []
    for transport_type, stocks_dict in [("passenger", pax_stocks), ("freight", frt_stocks)]:
        for vt, series in stocks_dict["target_stocks"].items():
            for yr, val in series.items():
                if yr not in _year_set:
                    continue
                gdp_year_value = gdp.get(yr, pd.NA)
                gdp_index = pd.NA
                if pd.notna(gdp_year_value) and pd.notna(gdp_base_value) and float(gdp_base_value) != 0:
                    gdp_index = float(gdp_year_value) / float(gdp_base_value) * 100
                row = {
                    "economy": economy,
                    "scenario": scenario,
                    "year": yr,
                    "transport_type": transport_type,
                    "vehicle_type": vt,
                    "target_stock": val,
                    "gdp_index": gdp_index,
                }
                if transport_type == "passenger":
                    row["motorisation_level"] = stocks_dict["M_envelope"].get(yr)
                    row["saturation_level"] = stocks_dict["M_sat"]
                    row["original_saturation_level"] = stocks_dict["original_M_sat"]
                    row["saturation_was_adjusted"] = stocks_dict["saturation_was_adjusted"]
                    row["k_raw"] = stocks_dict["k_raw"]
                    row["k_used"] = stocks_dict["k_used"]
                    row["k_clamped"] = stocks_dict["k_clamped"]
                    row["passenger_stock_growth_rate_adjustment"] = stocks_dict["growth_rate_adjustment"]
                    row["passenger_income_elasticity_used"] = stocks_dict["income_elasticity_used"]
                    row["passenger_raw_income_elasticity"] = stocks_dict["raw_income_elasticity"]
                    row["passenger_income_elasticity_clamped"] = stocks_dict["income_elasticity_clamped"]
                    row["passenger_energy_growth_rate"] = stocks_dict["passenger_energy_growth_rate"]
                    row["passenger_gdp_per_capita_growth_rate"] = stocks_dict["passenger_gdp_per_capita_growth_rate"]
                    row["passenger_income_elasticity_data_source"] = stocks_dict["income_elasticity_data_source"]
                    row["passenger_income_elasticity_note"] = stocks_dict["income_elasticity_note"]
                    row["is_saturated"] = stocks_dict["is_saturated"]
                    row["saturation_source_flag"] = stocks_dict["saturation_source_flag"]
                    row["original_vehicle_equivalent_weight"] = stocks_dict["original_weights"].get(vt)
                    row["adjusted_vehicle_equivalent_weight"] = stocks_dict["adjusted_weights"].get(vt)
                    row["weight_calibration_applied"] = stocks_dict["weight_calibration_applied"]
                    row["weight_calibration_target"] = stocks_dict["weight_calibration_target"]
                    row["weight_calibration_gap"] = stocks_dict["weight_calibration_gap"]
                    vt_bounds = stocks_dict["weight_bounds_used"].get(vt, (None, None))
                    row["weight_lower_bound"] = vt_bounds[0] if vt_bounds[0] is not None else pd.NA
                    row["weight_upper_bound"] = vt_bounds[1] if vt_bounds[1] is not None else pd.NA
                else:
                    row["gdp_elasticity_used"] = stocks_dict["elasticities"].get(vt)
                    diagnostics = stocks_dict.get("elasticity_diagnostics", {})
                    row["freight_raw_elasticity"] = diagnostics.get("raw_elasticity")
                    row["freight_elasticity_clamped"] = diagnostics.get("elasticity_clamped")
                    row["freight_energy_growth_rate"] = diagnostics.get("energy_growth_rate")
                    row["freight_gdp_growth_rate"] = diagnostics.get("gdp_growth_rate")
                    row["freight_elasticity_adjustment"] = diagnostics.get("elasticity_adjustment")
                    row["freight_elasticity_data_source"] = diagnostics.get("data_source")
                    row["freight_elasticity_note"] = diagnostics.get("note")
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
    gdp: pd.Series,
    energy_series: pd.Series,
    base_stocks: dict[str, float],
    weights: dict[str, float],
    vehicle_type_shares: dict[str, pd.Series] | None = None,
    saturation_overrides: dict[str, float] | None = None,
    passenger_saturation_reached: bool = False,
    vehicle_equivalent_weight_bounds: dict[str, tuple[float, float]] | None = None,
    growth_rate_adjustment: float = 1.0,
    cfg: dict | None = None,
) -> dict:
    """
    Project passenger target stocks using a GDP-per-capita motorisation envelope.

    Args:
        years: List of years to project.
        population: pd.Series indexed by year (persons).
        gdp: pd.Series indexed by year (consistent units).
        energy_series: pd.Series indexed by year (PJ), passenger road energy.
            Used to estimate the GDP-per-capita income elasticity.
        base_stocks: Dict mapping vehicle_type -> base-year vehicle count.
        weights: Vehicle-equivalent weights per vehicle type.
        vehicle_type_shares: Optional time-varying shares per vehicle type.
        saturation_overrides: Optional economy-specific saturation levels.
        cfg: Config dict with elasticity bounds, lookback_window_years, etc.

    Returns:
        Dict with keys: M_envelope, M_sat, M_base, income_elasticity_used,
        is_saturated, saturation_source_flag, target_stocks, vehicle_type_shares.
    """
    cfg = cfg or _DEFAULTS
    base_year = years[0]

    original_weights = dict(weights)

    M_sat, sat_source = resolve_saturation(
        compute_motorisation_base(base_stocks, weights, population[base_year])[0],
        saturation_overrides=saturation_overrides or {},
        fallback_multiplier=cfg["saturation_fallback_multiplier"],
    )
    log.info("Saturation level M_sat=%.4f (source: %s)", M_sat, sat_source)

    calibration = calibrate_passenger_vehicle_equivalent_weights(
        base_stocks=base_stocks,
        weights=weights,
        population_base=float(population[base_year]),
        saturation_level=M_sat,
        passenger_saturation_reached=passenger_saturation_reached,
        bounds=vehicle_equivalent_weight_bounds,
    )
    weights = calibration["adjusted_weights"]

    M_base, capacity_shares = compute_motorisation_base(
        base_stocks, weights, population[base_year]
    )
    log.info("Base-year motorisation M_base=%.4f car-equiv/capita", M_base)

    original_M_sat = M_sat
    saturation_was_adjusted = False
    if passenger_saturation_reached and calibration["applied"]:
        target = calibration["target_weighted_stock"] or 1.0
        gap_fraction = abs(calibration["gap"]) / target
        fallback_threshold = cfg.get("saturation_calibration_fallback_threshold", 0.05)
        if gap_fraction > fallback_threshold:
            M_sat = M_base
            saturation_was_adjusted = True
            log.warning(
                "Saturation weight calibration gap too large (%.1f%% of target) - "
                "M_sat reduced from %.4f to M_base=%.4f; projection will be flat at current level.",
                gap_fraction * 100,
                original_M_sat,
                M_base,
            )

    is_saturated = M_base >= cfg["saturation_already_reached_threshold"] * M_sat
    growth_rate_adjustment = max(0.0, float(growth_rate_adjustment))

    if is_saturated:
        elasticity_diag = {
            "elasticity": 0.0,
            "raw_elasticity": 0.0,
            "elasticity_clamped": False,
            "energy_growth_rate": 0.0,
            "gdp_per_capita_growth_rate": 0.0,
            "data_source": "saturated",
            "note": "economy treated as saturated",
        }
        log.info("Economy treated as saturated; passenger motorisation held flat")
    else:
        elasticity_diag = estimate_passenger_income_elasticity(
            passenger_energy=energy_series,
            gdp=gdp,
            population=population,
            lookback_years=cfg["lookback_window_years"],
            base_year=base_year,
            exclude_years=cfg["covid_exclude_years"],
            elasticity_min=cfg["passenger_income_elasticity_min"],
            elasticity_max=cfg["passenger_income_elasticity_max"],
            default_elasticity=cfg["passenger_default_income_elasticity"],
        )
        if growth_rate_adjustment != 1.0:
            adjusted = elasticity_diag["elasticity"] * growth_rate_adjustment
            adjusted_clamped = float(np.clip(
                adjusted,
                cfg["passenger_income_elasticity_min"],
                cfg["passenger_income_elasticity_max"],
            ))
            elasticity_diag["elasticity"] = adjusted_clamped
            elasticity_diag["elasticity_clamped"] = (
                elasticity_diag["elasticity_clamped"] or not np.isclose(adjusted, adjusted_clamped)
            )
            if elasticity_diag["data_source"] == "estimated":
                elasticity_diag["data_source"] = "estimated_adjusted"
        log.info(
            "Estimated passenger income elasticity raw=%s, used=%.4f "
            "(adjustment=%.3f, clamped=%s, passenger_energy_growth=%s, gdp_pc_growth=%s)",
            elasticity_diag.get("raw_elasticity"),
            elasticity_diag["elasticity"],
            growth_rate_adjustment,
            elasticity_diag["elasticity_clamped"],
            elasticity_diag.get("energy_growth_rate"),
            elasticity_diag.get("gdp_per_capita_growth_rate"),
        )
        if elasticity_diag["elasticity_clamped"]:
            log.warning("Passenger income elasticity was clamped to bounds; flag for review")

    M_envelope = project_passenger_motorisation_envelope_from_gdp_per_capita(
        base_year=base_year,
        projection_years=years,
        population=population,
        gdp=gdp,
        M_base=M_base,
        M_sat=M_sat,
        income_elasticity=float(elasticity_diag["elasticity"]),
    )

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
        "original_M_sat": original_M_sat,
        "saturation_was_adjusted": saturation_was_adjusted,
        "M_base": M_base,
        "k_raw": pd.NA,
        "k_used": pd.NA,
        "k_clamped": False,
        "income_elasticity_used": elasticity_diag["elasticity"],
        "raw_income_elasticity": elasticity_diag["raw_elasticity"],
        "income_elasticity_clamped": elasticity_diag["elasticity_clamped"],
        "passenger_energy_growth_rate": elasticity_diag["energy_growth_rate"],
        "passenger_gdp_per_capita_growth_rate": elasticity_diag["gdp_per_capita_growth_rate"],
        "income_elasticity_data_source": elasticity_diag["data_source"],
        "income_elasticity_note": elasticity_diag["note"],
        "growth_rate_adjustment": growth_rate_adjustment,
        "is_saturated": is_saturated,
        "saturation_source_flag": sat_source,
        "target_stocks": target_stocks,
        "vehicle_type_shares": vehicle_type_shares,
        "original_weights": original_weights,
        "adjusted_weights": weights,
        "weight_calibration_applied": calibration["applied"],
        "weight_calibration_target": calibration["target_weighted_stock"],
        "weight_calibration_gap": calibration["gap"],
        "weight_bounds_used": calibration["bounds_used"],
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
        base_stocks: Dict mapping vehicle_type -> vehicle count.
        weights: Dict mapping vehicle_type -> vehicle-equivalent weight.
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


def calibrate_passenger_vehicle_equivalent_weights(
    base_stocks: dict[str, float],
    weights: dict[str, float],
    population_base: float,
    saturation_level: float,
    passenger_saturation_reached: bool,
    bounds: dict[str, tuple[float, float]] | None = None,
) -> dict:
    """
    Calibrate motorcycle and bus X-LPV weights to hit passenger saturation.

    LPVs remain fixed at 1.0.  If calibration is disabled, adjusted weights are
    identical to original weights and the reported gap is the pre-calibration gap.
    """
    default_bounds = {
        "Motorcycles": (0.05, 0.80),
        "Buses": (8.0, 30.0),
    }
    bounds = {**default_bounds, **(bounds or {})}
    adjusted_weights = dict(weights)

    target_weighted_stock = float(saturation_level) * float(population_base)
    current_weighted_stock = sum(
        float(base_stocks.get(vt, 0.0)) * float(adjusted_weights.get(vt, 1.0))
        for vt in base_stocks
    )

    if not passenger_saturation_reached:
        return {
            "adjusted_weights": adjusted_weights,
            "applied": False,
            "target_weighted_stock": target_weighted_stock,
            "gap": current_weighted_stock - target_weighted_stock,
            "bounds_used": bounds,
        }

    adjusted_weights["LPVs"] = 1.0
    lpv_stock = float(base_stocks.get("LPVs", 0.0))
    motorcycle_stock = float(base_stocks.get("Motorcycles", 0.0))
    bus_stock = float(base_stocks.get("Buses", 0.0))
    fixed_weighted_stock = lpv_stock * 1.0
    required_flexible_stock = target_weighted_stock - fixed_weighted_stock

    motorcycle_bounds = bounds["Motorcycles"]
    bus_bounds = bounds["Buses"]
    motorcycle_lo, motorcycle_hi = map(float, motorcycle_bounds)
    bus_lo, bus_hi = map(float, bus_bounds)

    min_flexible_stock = motorcycle_stock * motorcycle_lo + bus_stock * bus_lo
    max_flexible_stock = motorcycle_stock * motorcycle_hi + bus_stock * bus_hi
    if required_flexible_stock < min_flexible_stock or required_flexible_stock > max_flexible_stock:
        # Target is outside the achievable range of motorcycle/bus weight combinations
        # (common when LPV stock alone exceeds the saturation target, or when minimum
        # bus weight already pushes the combined stock above target). Clamp to the
        # nearest feasible solution and continue rather than hard-failing.
        if required_flexible_stock < min_flexible_stock:
            adjusted_weights["Motorcycles"] = motorcycle_lo
            adjusted_weights["Buses"] = bus_lo
        else:
            adjusted_weights["Motorcycles"] = motorcycle_hi
            adjusted_weights["Buses"] = bus_hi
        clamped_weighted_stock = sum(
            float(base_stocks.get(vt, 0.0)) * float(adjusted_weights.get(vt, 1.0))
            for vt in base_stocks
        )
        log.warning(
            "Passenger saturation weight calibration clamped to bounds (target unreachable): "
            "target=%.1f current=%.1f clamped=%.1f motorcycle_w=%.3f bus_w=%.3f "
            "motorcycle_bounds=%s bus_bounds=%s",
            target_weighted_stock, current_weighted_stock, clamped_weighted_stock,
            adjusted_weights["Motorcycles"], adjusted_weights["Buses"],
            motorcycle_bounds, bus_bounds,
        )
        return {
            "adjusted_weights": adjusted_weights,
            "applied": True,
            "target_weighted_stock": target_weighted_stock,
            "gap": clamped_weighted_stock - target_weighted_stock,
            "bounds_used": bounds,
        }

    if motorcycle_stock <= 0 and bus_stock <= 0:
        raise ValueError(
            "Passenger saturation weight calibration is infeasible: no motorcycle or bus stock "
            f"available to adjust, target_weighted_stock={target_weighted_stock:.6f}"
        )

    original_motorcycle = float(weights.get("Motorcycles", adjusted_weights.get("Motorcycles", 1.0)))
    original_bus = float(weights.get("Buses", adjusted_weights.get("Buses", 1.0)))
    motorcycle_width = motorcycle_hi - motorcycle_lo
    bus_width = bus_hi - bus_lo
    if motorcycle_width <= 0 or bus_width <= 0:
        raise ValueError(
            "Passenger saturation weight calibration requires positive-width bounds: "
            f"motorcycle_bounds={motorcycle_bounds}, bus_bounds={bus_bounds}"
        )

    if bus_stock == 0:
        motorcycle_weight = required_flexible_stock / motorcycle_stock
        bus_weight = original_bus
    elif motorcycle_stock == 0:
        motorcycle_weight = original_motorcycle
        bus_weight = required_flexible_stock / bus_stock
    else:
        # Minimize normalized squared distance from the original weights along
        # the exact target line: motorcycle_stock*x + bus_stock*y = required.
        feasible_lo = max(
            motorcycle_lo,
            (required_flexible_stock - bus_stock * bus_hi) / motorcycle_stock,
        )
        feasible_hi = min(
            motorcycle_hi,
            (required_flexible_stock - bus_stock * bus_lo) / motorcycle_stock,
        )
        a = motorcycle_stock
        b = bus_stock
        c = required_flexible_stock
        wm = motorcycle_width
        wb = bus_width
        numerator = (
            original_motorcycle / (wm * wm)
            - (a / b) * ((c / b - original_bus) / (wb * wb))
        )
        denominator = (1.0 / (wm * wm)) + ((a * a) / (b * b * wb * wb))
        motorcycle_weight = float(np.clip(numerator / denominator, feasible_lo, feasible_hi))
        bus_weight = (required_flexible_stock - motorcycle_stock * motorcycle_weight) / bus_stock

    adjusted_weights["Motorcycles"] = float(motorcycle_weight)
    adjusted_weights["Buses"] = float(bus_weight)
    calibrated_weighted_stock = sum(
        float(base_stocks.get(vt, 0.0)) * float(adjusted_weights.get(vt, 1.0))
        for vt in base_stocks
    )
    return {
        "adjusted_weights": adjusted_weights,
        "applied": True,
        "target_weighted_stock": target_weighted_stock,
        "gap": calibrated_weighted_stock - target_weighted_stock,
        "bounds_used": bounds,
    }


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

    k ~= g_E / (1 - M_base / M_sat)

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

    if k == 0.0:
        return pd.Series(M_base, index=years)
    if M_sat <= 0:
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


def estimate_passenger_income_elasticity(
    passenger_energy: pd.Series,
    gdp: pd.Series,
    population: pd.Series,
    lookback_years: int,
    base_year: int,
    exclude_years: Collection[int] | None = None,
    elasticity_min: float = 0.0,
    elasticity_max: float = 2.0,
    default_elasticity: float = 0.8,
) -> dict[str, float | bool | str | None]:
    """
    Estimate passenger motorisation income elasticity from historical trends.

    Passenger road energy is used as the activity proxy. GDP per capita is
    calculated from the macro GDP and population series, then the elasticity is
    the ratio of historical passenger activity growth to GDP-per-capita growth.
    """
    exclude = set(exclude_years or [])
    window_start = base_year - lookback_years

    common_years = gdp.index.intersection(population.index)
    gdp_pc = (gdp.loc[common_years] / population.loc[common_years].replace(0.0, np.nan)).dropna()

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

    energy_growth = _geometric_growth(passenger_energy)
    gdp_pc_growth = _geometric_growth(gdp_pc)

    if energy_growth is None or gdp_pc_growth is None:
        log.warning(
            "Insufficient data for passenger income elasticity estimation; using default %.2f",
            default_elasticity,
        )
        return {
            "elasticity": float(default_elasticity),
            "raw_elasticity": None,
            "elasticity_clamped": False,
            "energy_growth_rate": energy_growth,
            "gdp_per_capita_growth_rate": gdp_pc_growth,
            "data_source": "default",
            "note": "insufficient data",
        }

    if abs(gdp_pc_growth) < 1e-6:
        log.warning(
            "Near-zero GDP per capita growth; using default passenger income elasticity %.2f",
            default_elasticity,
        )
        return {
            "elasticity": float(default_elasticity),
            "raw_elasticity": None,
            "elasticity_clamped": False,
            "energy_growth_rate": energy_growth,
            "gdp_per_capita_growth_rate": gdp_pc_growth,
            "data_source": "default",
            "note": "near-zero GDP per capita growth",
        }

    raw_elasticity = energy_growth / gdp_pc_growth
    clamped = float(np.clip(raw_elasticity, elasticity_min, elasticity_max))
    was_clamped = not np.isclose(raw_elasticity, clamped)
    if was_clamped:
        log.warning(
            "Passenger income elasticity clamped from %.4f to %.4f; flag for review",
            raw_elasticity,
            clamped,
        )

    return {
        "elasticity": clamped,
        "raw_elasticity": float(raw_elasticity),
        "elasticity_clamped": bool(was_clamped),
        "energy_growth_rate": float(energy_growth),
        "gdp_per_capita_growth_rate": float(gdp_pc_growth),
        "data_source": "estimated",
        "note": "clamped" if was_clamped else "estimated",
    }


def project_passenger_motorisation_envelope_from_gdp_per_capita(
    base_year: int,
    projection_years: list[int],
    population: pd.Series,
    gdp: pd.Series,
    M_base: float,
    M_sat: float,
    income_elasticity: float,
) -> pd.Series:
    """
    Project passenger vehicle-equivalent ownership from GDP per capita.

    The year-to-year GDP-per-capita growth effect is damped by the remaining
    distance to saturation, so growth fades as M approaches M_sat.
    """
    years = sorted(projection_years)
    common_years = gdp.index.intersection(population.index)
    gdp_pc = (gdp.loc[common_years] / population.loc[common_years].replace(0.0, np.nan)).dropna()
    gdp_pc = gdp_pc.reindex(years).interpolate(method="index").ffill().bfill()

    values: dict[int, float] = {}
    previous_year = base_year
    values[base_year] = min(float(M_base), float(M_sat)) if M_sat > 0 else float(M_base)

    for year in years:
        if year == base_year:
            continue
        previous_m = float(values[previous_year])
        previous_gdp_pc = float(gdp_pc.loc[previous_year]) if previous_year in gdp_pc.index else np.nan
        current_gdp_pc = float(gdp_pc.loc[year]) if year in gdp_pc.index else np.nan
        if not np.isfinite(previous_gdp_pc) or not np.isfinite(current_gdp_pc) or previous_gdp_pc <= 0:
            values[year] = previous_m
            previous_year = year
            continue

        income_growth_factor = (current_gdp_pc / previous_gdp_pc) ** float(income_elasticity)
        income_growth_rate = income_growth_factor - 1.0
        remaining_fraction = max(0.0, 1.0 - previous_m / M_sat) if M_sat > 0 else 0.0
        damped_growth_rate = income_growth_rate * remaining_fraction
        next_m = previous_m * (1.0 + damped_growth_rate)
        if M_sat > 0:
            next_m = min(next_m, M_sat)
        values[year] = max(0.0, float(next_m))
        previous_year = year

    return pd.Series(values, index=years)


def resolve_saturation(
    M_base: float,
    saturation_overrides: dict[str, float],
    fallback_multiplier: float = 3.0,
) -> tuple[float, str]:
    """
    Resolve the saturation motorisation level.

    Priority:
    1. Researcher-provided saturation (passed in saturation_overrides).
    2. Default fallback: M_base x fallback_multiplier.

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
    vehicle_type_shares: dict[str, pd.Series] | None = None,
    elasticity_overrides: dict[str, float] | None = None,
    elasticity_adjustments: dict[str, float] | None = None,
    cfg: dict | None = None,
) -> dict:
    """
    Project freight target stocks using GDP elasticity.

    target_stock(y) = base_stock x (GDP(y) / GDP_base) ^ elasticity

    Args:
        years: List of years to project.
        gdp: pd.Series indexed by year.
        energy_series: pd.Series indexed by year (PJ), freight road energy.
        base_stocks: Dict mapping vehicle_type -> base-year count.
        elasticity_overrides: Optional dict mapping vehicle_type -> override elasticity.
        elasticity_adjustments: Optional dict mapping vehicle_type -> elasticity multiplier.
        cfg: Config dict.

    Returns:
        Dict with keys: elasticities, target_stocks.
    """
    cfg = cfg or _DEFAULTS
    overrides = elasticity_overrides or {}
    adjustments = elasticity_adjustments or {}
    base_year = years[0]
    gdp_base = float(gdp[base_year])

    elasticity_diag = estimate_freight_elasticity(
        energy_series,
        gdp,
        lookback_years=cfg["lookback_window_years"],
        base_year=base_year,
        exclude_years=cfg["covid_exclude_years"],
        elasticity_min=cfg["elasticity_min"],
        elasticity_max=cfg["elasticity_max"],
        default_elasticity=cfg["default_elasticity"],
    )
    elasticity = float(elasticity_diag["elasticity"])
    log.info("Estimated freight GDP elasticity: %.4f", elasticity)

    adjustment = float(adjustments.get("freight_total", 1.0))
    adjusted_elasticity = float(np.clip(
        elasticity * adjustment,
        cfg["elasticity_min"],
        cfg["elasticity_max"],
    ))
    e = overrides.get("freight_total", adjusted_elasticity)
    if "freight_total" in adjustments and "freight_total" not in overrides:
        elasticity_diag = {
            **elasticity_diag,
            "elasticity": float(e),
            "elasticity_adjustment": adjustment,
            "elasticity_clamped": bool(
                elasticity_diag.get("elasticity_clamped", False)
                or not np.isclose(elasticity * adjustment, adjusted_elasticity)
            ),
            "data_source": "estimated_adjusted",
            "note": f"estimated elasticity multiplied by {adjustment:.4g}",
        }
    if "freight_total" in overrides:
        elasticity_diag = {
            **elasticity_diag,
            "elasticity": float(e),
            "elasticity_adjustment": adjustment,
            "data_source": "override",
            "note": "freight_total override used",
        }
    else:
        elasticity_diag = {
            **elasticity_diag,
            "elasticity_adjustment": adjustment,
        }
    gdp_ratio = gdp / gdp_base
    total_base_stock = sum(float(value) for value in base_stocks.values())
    total_target_stock = pd.Series(
        total_base_stock * (gdp_ratio ** e),
        index=gdp_ratio.index,
    ).reindex(years)

    freight_types = list(base_stocks)
    if vehicle_type_shares is None or not any(vt in vehicle_type_shares for vt in freight_types):
        total = total_base_stock or 1.0
        vehicle_type_shares = {
            vt: pd.Series(float(base_stocks.get(vt, 0.0)) / total, index=years)
            for vt in freight_types
        }

    target_stocks = {}
    elasticities = {}
    for vt in freight_types:
        shares = vehicle_type_shares.get(vt)
        if shares is None:
            shares = pd.Series(0.0, index=years)
        shares = shares.reindex(years).interpolate(method="index").ffill().bfill().fillna(0.0)
        target_stocks[vt] = total_target_stock * shares
        elasticities[vt] = e

    return {
        "elasticities": elasticities,
        "target_stocks": target_stocks,
        "elasticity_diagnostics": elasticity_diag,
    }


def estimate_freight_elasticity(
    energy_series: pd.Series,
    gdp: pd.Series,
    lookback_years: int,
    base_year: int,
    exclude_years: Collection[int] | None = None,
    elasticity_min: float = 0.0,
    elasticity_max: float = 2.0,
    default_elasticity: float = 0.8,
) -> dict[str, float | bool | str | None]:
    """
    Estimate freight stock elasticity from historical energy and GDP growth.

    Returns diagnostics for dashboard/review use, including raw elasticity,
    clamping status, growth rates, and fallback reason when estimation is not possible.
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
        log.warning("Insufficient data for freight elasticity estimation; using default %.2f", default_elasticity)
        return {
            "elasticity": float(default_elasticity),
            "raw_elasticity": None,
            "elasticity_clamped": False,
            "energy_growth_rate": energy_growth,
            "gdp_growth_rate": gdp_growth,
            "data_source": "default",
            "note": "insufficient data",
        }

    if abs(gdp_growth) < 1e-6:
        log.warning("Near-zero GDP growth; using default freight elasticity %.2f", default_elasticity)
        return {
            "elasticity": float(default_elasticity),
            "raw_elasticity": None,
            "elasticity_clamped": False,
            "energy_growth_rate": energy_growth,
            "gdp_growth_rate": gdp_growth,
            "data_source": "default",
            "note": "near-zero GDP growth",
        }

    raw_elasticity = energy_growth / gdp_growth
    clamped = float(np.clip(raw_elasticity, elasticity_min, elasticity_max))
    was_clamped = not np.isclose(raw_elasticity, clamped)
    if was_clamped:
        log.warning("Freight elasticity clamped from %.4f to %.4f; flag for review", raw_elasticity, clamped)

    return {
        "elasticity": clamped,
        "raw_elasticity": float(raw_elasticity),
        "elasticity_clamped": bool(was_clamped),
        "energy_growth_rate": float(energy_growth),
        "gdp_growth_rate": float(gdp_growth),
        "data_source": "estimated",
        "note": "clamped" if was_clamped else "estimated",
    }


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
        log.warning("No 'stock' column in base_year_branches - returning zero stocks")
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
