"""
Module 4 — Sales, survival, vintage, and turnover policy.

Converts projected stock targets (T5) into annual sales, retirements,
surviving stock, and vintage profiles.

Ported from:
    leap_transport/codebase/sales_workflow.py
    leap_transport/codebase/functions/sales_curve_estimate.py
    leap_transport/codebase/functions/lifecycle_profile_editor.py

LEAP-specific I/O has been stripped. Core maths are preserved exactly.

Outputs: T6_sales_turnover and T6v_vintage_profiles DataFrames.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from diagnostics.module_charts import write_module4_charts
from schemas.validation import validate_table

log = logging.getLogger(__name__)


# ===========================================================================
# Public API
# ===========================================================================

_PASSENGER_VEHICLE_TYPES = {"LPVs", "Motorcycles", "Buses"}

def run_module4(
    stock_targets: pd.DataFrame,
    survival_curves: dict[str, pd.Series],
    vintage_profiles: dict[str, pd.Series],
    lifecycle_factors: pd.DataFrame | None = None,
    turnover_policies: dict[str, dict[str, Any]] | None = None,
    fleet_age_shift_years: float | dict[str, float] | None = None,
    scrappage_years: dict[str, dict[int, float]] | None = None,
    config: dict | None = None,
    diagnostics_dir: str | Path | None = None,
    economy: str = "",
    scenario: str = "",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Run Module 4: compute annual sales, retirements, and stock by vintage.

    Args:
        stock_targets: T5_stock_targets DataFrame from Module 3.
        survival_curves: Dict mapping vehicle_type → pd.Series indexed by age
            (annual survival probabilities, values 0–1 or 0–100).
        vintage_profiles: Dict mapping vehicle_type → pd.Series indexed by age
            (base-year fleet age distribution, normalised to sum 1).
        lifecycle_factors: Optional DataFrame from load_lifecycle_profile_factors()
            with columns transport_type, turnover_rate_lower, turnover_rate_upper,
            fit_mode, scale_age_band_age_min, scale_age_band_age_max,
            scale_age_band_factor, smoothing_window. When provided, survival curves
            are calibrated to meet turnover rate bounds before stock-flow accounting,
            and vintage profiles are re-derived from calibrated survival curves.
        turnover_policies: Optional dict mapping vehicle_type →
            {additional_retirement_rate, survival_multiplier, ...}.
        fleet_age_shift_years: Optional shift to apply to base-year vintage.
            Can be a single float or a dict mapping vehicle_type → shift.
        scrappage_years: Optional explicit scrappage by vehicle_type and year.
            {vehicle_type: {year: scrappage_count}}.
        config: Optional config dict.
        diagnostics_dir: Optional directory root for Module 4 PNG diagnostic
            charts. When provided, charts are written to
            diagnostics_dir/module4/.

    Returns:
        Tuple of (T6_sales_turnover DataFrame, T6v_vintage_profiles DataFrame).
    """
    cfg = config or {}

    # Calibrate survival curves and re-derive vintage profiles if factors provided
    if lifecycle_factors is not None and not lifecycle_factors.empty:
        survival_curves, vintage_profiles, calib_diag = calibrate_survival_and_vintage(
            survival_curves, vintage_profiles, lifecycle_factors
        )
        for row in calib_diag.to_dict(orient="records"):
            log.info(
                "Lifecycle calibration [%s]: turnover_rate=%.4f fit_mode=%s "
                "scale_factor=%.4f (bounds: %.3f–%.3f)",
                row["vehicle_type"], row["turnover_rate"], row["fit_mode"],
                row["scale_factor_used"], row["turnover_rate_lower"], row["turnover_rate_upper"],
            )

    if fleet_age_shift_years is not None:
        shifted, shift_diag = shift_vintage_profiles(vintage_profiles, fleet_age_shift_years)
        vintage_profiles = {**vintage_profiles, **shifted}
        log.info("Applied fleet age shift. Diagnostics:\n%s", shift_diag)

    t6_rows = []
    t6v_rows = []

    vehicle_types = stock_targets["vehicle_type"].unique()

    for vt in vehicle_types:
        vt_mask = stock_targets["vehicle_type"] == vt
        vt_targets = stock_targets[vt_mask].sort_values("year")

        survival = survival_curves.get(vt)
        vintage = vintage_profiles.get(vt)

        if survival is None or vintage is None:
            log.warning("Missing survival or vintage profile for %s — skipping", vt)
            continue

        survival = _normalise_survival(survival)
        vintage = _normalise_vintage(vintage)

        policy = (turnover_policies or {}).get(vt)
        scrappage = (scrappage_years or {}).get(vt, {})

        years = sorted(vt_targets["year"].unique())
        target_stock_series = vt_targets.set_index("year")["target_stock"]

        sales, cohorts, retirements = compute_sales_from_stock_targets(
            target_stock=target_stock_series,
            survival_curve=survival,
            vintage_profile=vintage,
            turnover_policy=policy,
            return_retirements=True,
        )

        for yr in years:
            nat_ret = float(retirements["natural"].get(yr, 0.0))
            add_ret = float(retirements["additional"].get(yr, 0.0))
            stock_above_target = bool(retirements["stock_above_target"].get(yr, False))
            scale_factor_applied = float(retirements["scale_factor_applied"].get(yr, 1.0))
            scrp = float(scrappage.get(yr, 0.0))
            _stock = float(target_stock_series.get(yr, 0))
            _sales = float(sales.get(yr, 0))
            t6_rows.append({
                "economy": economy,
                "scenario": scenario,
                "year": yr,
                "transport_type": "passenger" if vt in _PASSENGER_VEHICLE_TYPES else "freight",
                "vehicle_type": vt,
                "target_stock": _stock,
                "new_sales": _sales,
                "natural_retirements": nat_ret,
                "additional_retirements": add_ret,
                "total_retirements": nat_ret + add_ret,
                "stock": _stock,
                "stock_above_target": stock_above_target,
                "scale_factor_applied": scale_factor_applied,
                "scrappage_for_leap": scrp,
            })

        for age, share in vintage.items():
            surv_val = float(survival.get(age, 0.0))
            t6v_rows.append({
                "vehicle_type": vt,
                "age": int(age),
                "vintage_share": float(share),
                "survival_probability": surv_val,
                "age_shift_applied_years": (
                    fleet_age_shift_years
                    if isinstance(fleet_age_shift_years, (int, float))
                    else (fleet_age_shift_years or {}).get(vt, 0.0)
                ),
            })

    t6 = pd.DataFrame(t6_rows)
    t6v = pd.DataFrame(t6v_rows)

    errors = validate_table(t6, "T6_sales_turnover")
    for err in errors:
        log.warning("Validation: %s", err)

    if diagnostics_dir is not None:
        try:
            written = write_module4_charts(t6, t6v, diagnostics_dir)
            log.info("Module 4 diagnostics: wrote %d chart(s)", len(written))
        except Exception as exc:
            log.warning("Module 4 diagnostics chart generation failed: %s", exc)

    return t6, t6v


# ===========================================================================
# Core stock-flow calculation
# ===========================================================================

def compute_sales_from_stock_targets(
    target_stock: pd.Series,
    survival_curve: pd.Series,
    vintage_profile: pd.Series,
    *,
    turnover_policy: Mapping[str, Any] | None = None,
    return_retirements: bool = False,
) -> tuple:
    """
    Compute annual new vehicle sales from a target stock series.

    Uses cohort-based stock-flow accounting:
        surviving_stock(y) = sum of prior cohorts aged forward by survival
        required_sales(y) = max(0, target_stock(y) - surviving_stock(y))

    When target > survivors: new sales fill the gap.
    When survivors > target: cohorts are scaled down proportionally (no sales).

    Ported from:
        sales_curve_estimate.py::compute_sales_from_stock_targets (base logic)
        sales_workflow.py::compute_sales_from_stock_targets (policy extension)

    Supported turnover_policy keys:
        additional_retirement_rate: scalar/Series/dict by year in [0, 1].
        age_multipliers: scalar/Series/dict by age (>=0).
        survival_multiplier: scalar/Series/dict by year (>=0).
        survival_multipliers_by_age: scalar/Series/dict by age (>=0).

    Args:
        target_stock: pd.Series indexed by year.
        survival_curve: pd.Series indexed by age (annual survival, 0–1).
        vintage_profile: pd.Series indexed by age (normalised to sum 1).
        turnover_policy: Optional policy dict.
        return_retirements: If True, return retirements as third element.

    Returns:
        (sales, cohorts) or (sales, cohorts, {"natural": pd.Series, "additional": pd.Series})
    """
    survival_curve, vintage_profile = _validate_and_align_age_profiles(
        survival_curve, vintage_profile
    )
    max_age = len(vintage_profile)
    years = pd.Index(target_stock.index)

    cohorts = initialise_cohorts(target_stock, vintage_profile)
    sales = pd.Series(0.0, index=years, dtype=float)
    natural_ret = pd.Series(0.0, index=years, dtype=float)
    additional_ret = pd.Series(0.0, index=years, dtype=float)
    stock_above_target = pd.Series(False, index=years, dtype=bool)
    scale_factor_applied = pd.Series(1.0, index=years, dtype=float)

    survival_probs = survival_curve.to_numpy(dtype=float)
    ages = pd.Index(vintage_profile.index, dtype=int)

    policy = turnover_policy or {}
    extra_ret_rate = _coerce_year_schedule(
        policy.get("additional_retirement_rate"), years, default=0.0
    ).clip(lower=0.0, upper=1.0)
    extra_ret_age_mult = _coerce_age_profile(
        policy.get("age_multipliers"), ages, default=1.0
    ).clip(lower=0.0)
    survival_year_mult = _coerce_year_schedule(
        policy.get("survival_multiplier"), years, default=1.0
    ).clip(lower=0.0)
    survival_age_mult = _coerce_age_profile(
        policy.get("survival_multipliers_by_age"), ages, default=1.0
    ).clip(lower=0.0)

    extra_ret_age_mult_arr = extra_ret_age_mult.to_numpy(dtype=float)
    survival_age_mult_arr = survival_age_mult.to_numpy(dtype=float)

    for i in range(1, len(years)):
        year_prev = years[i - 1]
        year = years[i]

        prev_cohorts = cohorts.loc[year_prev].to_numpy(dtype=float)
        new_cohorts = np.zeros_like(prev_cohorts, dtype=float)

        year_surv_mult = float(survival_year_mult.loc[year])
        for age in range(1, max_age):
            base_prob = float(survival_probs[age - 1])
            age_surv_mult = float(survival_age_mult_arr[age - 1])
            survive_prob = np.clip(base_prob * year_surv_mult * age_surv_mult, 0.0, 1.0)
            new_cohorts[age] = prev_cohorts[age - 1] * survive_prob

        natural_survivors = float(new_cohorts.sum())
        nat_retired = max(0.0, float(prev_cohorts.sum()) - natural_survivors)

        extra_retired = 0.0
        extra_rate_year = float(extra_ret_rate.loc[year])
        if extra_rate_year > 0.0:
            extra_rate_by_age = np.clip(extra_rate_year * extra_ret_age_mult_arr, 0.0, 1.0)
            retired_by_policy = new_cohorts * extra_rate_by_age
            new_cohorts = np.clip(new_cohorts - retired_by_policy, 0.0, None)
            extra_retired = float(retired_by_policy.sum())

        survivors_total = float(new_cohorts.sum())
        target_total = float(target_stock.loc[year])

        if survivors_total <= target_total:
            required_sales = target_total - survivors_total
            new_cohorts[0] = required_sales
        else:
            scale = target_total / survivors_total if survivors_total > 0 else 0.0
            new_cohorts *= scale
            required_sales = 0.0
            stock_above_target.loc[year] = True
            scale_factor_applied.loc[year] = scale

        natural_ret.loc[year] = nat_retired
        additional_ret.loc[year] = extra_retired
        cohorts.loc[year, :] = new_cohorts
        sales.loc[year] = required_sales

    if return_retirements:
        return sales, cohorts, {
            "natural": natural_ret,
            "additional": additional_ret,
            "stock_above_target": stock_above_target,
            "scale_factor_applied": scale_factor_applied,
        }
    return sales, cohorts


def initialise_cohorts(
    target_stock: pd.Series,
    vintage_profile: pd.Series,
) -> pd.DataFrame:
    """
    Create base-year cohort matrix from vintage profile.

    Returns a DataFrame indexed by year with columns = ages.
    Values are vehicle counts per age cohort in the base year; all other
    year-rows start at zero and are filled by compute_sales_from_stock_targets.

    Ported from sales_curve_estimate.py::initialise_cohorts.

    Args:
        target_stock: pd.Series indexed by year.
        vintage_profile: pd.Series indexed by age (normalised to sum 1).

    Returns:
        pd.DataFrame (years × ages), zero-filled except base year.
    """
    years = target_stock.index
    vintage_profile = pd.Series(vintage_profile, dtype=float).sort_index()
    max_age = len(vintage_profile)

    cohorts = pd.DataFrame(
        data=0.0,
        index=years,
        columns=range(max_age),
        dtype=float,
    )

    base_year = years[0]
    base_stock = float(target_stock.loc[base_year])

    total_vintage = float(vintage_profile.sum())
    if total_vintage <= 0:
        raise ValueError("vintage_profile must sum to a positive value.")
    vp = vintage_profile / total_vintage
    cohorts.loc[base_year, :] = base_stock * vp.values

    return cohorts


# ===========================================================================
# Survival ↔ vintage conversion
# ===========================================================================

def survival_to_vintage(survival_curve: pd.Series) -> pd.Series:
    """
    Derive steady-state vintage profile from a survival curve.

    Under constant annual sales and stationary survival, the fraction of
    the fleet at age a is proportional to the cumulative survival S(a).
    The normalised result sums to 1.

    Accepts cumulative (S(0)=100 or 1.0) or annual (p(age)) survival.
    The function detects which format by checking whether S(0) ≈ max value.

    Ported from lifecycle_profile_editor.py::survival_profile_to_vintage_profile.

    Args:
        survival_curve: pd.Series indexed by age.

    Returns:
        pd.Series indexed by age (vintage shares, sum to 1).
    """
    surv = pd.Series(survival_curve, dtype=float).sort_index()
    if surv.empty:
        raise ValueError("survival_curve must not be empty.")

    vals = surv.to_numpy(dtype=float)
    s0 = vals[0]
    if s0 <= 0:
        raise ValueError("First survival value must be positive.")

    surv_frac = vals / s0
    surv_sum = float(surv_frac.sum())
    if surv_sum <= 0:
        raise ValueError("Sum of normalised survival must be positive.")

    stock_share = surv_frac / surv_sum
    return pd.Series(stock_share, index=surv.index, dtype=float)


def cumulative_to_annual_survival(survival: pd.Series) -> pd.Series:
    """
    Convert cumulative survival S(age) to annual survival probabilities p(age).

    p(age) = S(age+1) / S(age), with p(max_age) = 0.

    Ported from sales_curve_estimate.py::_convert_cumulative_survival_to_annual.

    Args:
        survival: pd.Series indexed by age (cumulative, 0–1 or 0–100).

    Returns:
        pd.Series indexed by age (annual probabilities, 0–1).
    """
    surv = pd.Series(survival, dtype=float).sort_index()
    scale = 100.0 if surv.max() > 1.0 else 1.0
    surv = (surv / scale).clip(lower=1e-9, upper=1.0)
    annual = surv.shift(-1) / surv
    annual.iloc[-1] = 0.0
    return annual.clip(lower=0.0, upper=1.0)


# ===========================================================================
# Policy derivation
# ===========================================================================

def derive_vehicle_turnover_policies_from_drive_policy(
    df: pd.DataFrame,
    years: pd.Index,
    *,
    drive_turnover_policy: Mapping[str, Any],
    vehicle_type_map: Mapping[str, str] | None = None,
    transport_type: str = "passenger",
    medium: str = "road",
    economy: str | None = None,
    scenario: str | None = None,
    stocks_col: str = "Stocks",
) -> tuple[dict[str, dict[str, pd.Series]], dict[str, Any]]:
    """
    Convert drive-level policy definitions to vehicle-bucket turnover policies.

    Effective vehicle rate = weighted sum of drive rates by drive stock share:
        effective_rate(bucket, year) = sum_drive(share_drive * rate_drive)

    Ported from sales_workflow.py::derive_vehicle_turnover_policies_from_drive_policy.

    Args:
        df: DataFrame with columns [Date, Vehicle Type, Drive, <stocks_col>].
        years: pd.Index of integer years.
        drive_turnover_policy: Drive policy spec, e.g.:
            {"ICE": {2030: 0.02, 2040: 0.04}}
        vehicle_type_map: Source vehicle type → model bucket (e.g. {"car": "LPVs"}).
        transport_type: 'passenger' or 'freight'.
        medium: Passed as filter if 'Medium' column exists.
        economy: Optional filter on 'Economy' column.
        scenario: Optional filter on 'Scenario' column.
        stocks_col: Column name for stock values.

    Returns:
        (turnover_policies_dict, diagnostics_dict)
        where diagnostics contains effective_rates, drive_rates, contributions_long,
        all_drive_stock_shares_long, unused_policy_drives.
    """
    _DEFAULT_DRIVE_GROUPS: dict[str, tuple[str, ...]] = {
        "ice": ("ice_d", "ice_g"),
        "hybrid": ("hev", "hev_d", "hev_g"),
        "phev": ("phev_d", "phev_g"),
        "ev": ("bev", "fcev", "erev_d", "erev_g", "phev_d", "phev_g"),
    }

    years = pd.Index(years, dtype=int)
    empty_diag = {
        "effective_rates": pd.DataFrame(index=years),
        "drive_rates": pd.DataFrame(index=years),
        "contributions_long": pd.DataFrame(),
        "all_drive_stock_shares_long": pd.DataFrame(),
        "unused_policy_drives": [],
    }
    if years.empty:
        return {}, {**empty_diag, "effective_rates": pd.DataFrame(), "drive_rates": pd.DataFrame()}

    if vehicle_type_map is None:
        if str(transport_type).lower() == "freight":
            vehicle_type_map = {"ht": "Trucks", "mt": "Trucks", "truck": "Trucks",
                                "trucks": "Trucks", "lcv": "LCVs", "van": "LCVs"}
        else:
            vehicle_type_map = {"car": "LPVs", "suv": "LPVs", "lt": "LPVs",
                                "lpv": "LPVs", "2w": "Motorcycles", "mc": "Motorcycles",
                                "bus": "Buses"}
    vt_map_norm = {str(k).lower().strip(): str(v) for k, v in vehicle_type_map.items()}

    required = {"Date", "Vehicle Type", "Drive", stocks_col}
    missing = sorted(required - set(df.columns))
    if missing:
        raise KeyError(f"Missing columns for drive policy derivation: {missing}")

    df_use = df.copy()
    if economy is not None and "Economy" in df_use.columns:
        df_use = df_use[df_use["Economy"].astype(str) == str(economy)]
    if scenario is not None and "Scenario" in df_use.columns:
        df_use = df_use[df_use["Scenario"].astype(str) == str(scenario)]
    if "Transport Type" in df_use.columns:
        df_use = df_use[df_use["Transport Type"].astype(str).str.lower() == str(transport_type).lower()]
    if "Medium" in df_use.columns:
        df_use = df_use[df_use["Medium"].astype(str).str.lower() == str(medium).lower()]

    drive_rates = _resolve_drive_policy_rates(drive_turnover_policy, years, _DEFAULT_DRIVE_GROUPS)
    drive_rates_df = (
        pd.DataFrame({k: v.reindex(years).astype(float) for k, v in drive_rates.items()}, index=years)
        if drive_rates else pd.DataFrame(index=years)
    )

    if df_use.empty:
        return {}, {**empty_diag,
                    "drive_rates": drive_rates_df,
                    "unused_policy_drives": sorted(drive_rates.keys())}

    df_use = df_use.copy()
    df_use["_year"] = pd.to_numeric(df_use["Date"], errors="coerce")
    df_use = df_use[df_use["_year"].notna()].copy()
    df_use["_year"] = df_use["_year"].astype(int)
    df_use = df_use[df_use["_year"].isin(set(years))].copy()
    df_use["_vehicle_bucket"] = (
        df_use["Vehicle Type"].astype(str).str.lower().str.strip().map(vt_map_norm)
    )
    df_use["_drive_key"] = df_use["Drive"].astype(str).str.lower().str.strip()
    df_use["_stocks"] = pd.to_numeric(df_use[stocks_col], errors="coerce").fillna(0.0).clip(lower=0.0)
    df_use = df_use.dropna(subset=["_vehicle_bucket"])

    if df_use.empty:
        return {}, {**empty_diag, "drive_rates": drive_rates_df,
                    "unused_policy_drives": sorted(drive_rates.keys())}

    grouped = (
        df_use.groupby(["_year", "_vehicle_bucket", "_drive_key"], as_index=False)["_stocks"].sum()
    )
    all_drive_shares = grouped.rename(columns={
        "_year": "Date", "_vehicle_bucket": "vehicle_bucket",
        "_drive_key": "drive", "_stocks": "drive_stock",
    }).copy()
    vehicle_totals = (
        all_drive_shares.groupby(["Date", "vehicle_bucket"], as_index=False)["drive_stock"]
        .sum().rename(columns={"drive_stock": "vehicle_type_total_stock"})
    )
    all_drive_shares = all_drive_shares.merge(vehicle_totals, on=["Date", "vehicle_bucket"], how="left")
    denom = all_drive_shares["vehicle_type_total_stock"].replace(0.0, np.nan)
    all_drive_shares["drive_stock_share"] = (all_drive_shares["drive_stock"] / denom).fillna(0.0)

    buckets = sorted(grouped["_vehicle_bucket"].dropna().astype(str).unique().tolist())
    full_index = pd.MultiIndex.from_product([years, buckets], names=["Date", "vehicle_bucket"])
    stocks_panel = grouped.pivot_table(
        index=["_year", "_vehicle_bucket"], columns="_drive_key",
        values="_stocks", aggfunc="sum", fill_value=0.0,
    ).reindex(full_index, fill_value=0.0)

    effective_rates_df = pd.DataFrame(0.0, index=years, columns=buckets, dtype=float)
    contribution_frames: list[pd.DataFrame] = []

    for bucket in buckets:
        bucket_panel = stocks_panel.xs(bucket, level="vehicle_bucket")
        total_stock = bucket_panel.sum(axis=1).astype(float)
        total_safe = total_stock.replace(0.0, np.nan)
        effective = pd.Series(0.0, index=years, dtype=float)

        for drive_key, rate_series in drive_rates.items():
            drive_stock = (
                bucket_panel[drive_key].astype(float) if drive_key in bucket_panel.columns
                else pd.Series(0.0, index=years, dtype=float)
            )
            stock_share = (drive_stock / total_safe).fillna(0.0)
            contribution = (stock_share * rate_series.reindex(years).fillna(0.0)).astype(float)
            effective = effective.add(contribution, fill_value=0.0)
            contribution_frames.append(pd.DataFrame({
                "Date": years, "vehicle_bucket": bucket, "drive": drive_key,
                "drive_stock": drive_stock.to_numpy(dtype=float),
                "bucket_total_stock": total_stock.to_numpy(dtype=float),
                "drive_stock_share": stock_share.to_numpy(dtype=float),
                "drive_policy_rate": rate_series.reindex(years).to_numpy(dtype=float),
                "rate_contribution": contribution.to_numpy(dtype=float),
            }))

        effective_rates_df[bucket] = effective.clip(lower=0.0, upper=1.0)

    turnover_policies: dict[str, dict[str, pd.Series]] = {}
    for bucket in effective_rates_df.columns:
        rate = effective_rates_df[bucket].astype(float)
        if float(rate.max()) > 0.0:
            turnover_policies[str(bucket)] = {"additional_retirement_rate": rate}

    contributions_long = (
        pd.concat(contribution_frames, ignore_index=True) if contribution_frames
        else pd.DataFrame(columns=[
            "Date", "vehicle_bucket", "drive", "drive_stock",
            "bucket_total_stock", "drive_stock_share", "drive_policy_rate", "rate_contribution",
        ])
    )

    diagnostics = {
        "effective_rates": effective_rates_df,
        "drive_rates": drive_rates_df,
        "contributions_long": contributions_long,
        "all_drive_stock_shares_long": all_drive_shares,
        "unused_policy_drives": sorted(set(drive_rates.keys()) - set(stocks_panel.columns.astype(str))),
    }
    return turnover_policies, diagnostics


def shift_vintage_profiles(
    vintage_profiles: Mapping[str, pd.Series],
    age_shift_years: float | Mapping[str, float],
) -> tuple[dict[str, pd.Series], pd.DataFrame]:
    """
    Apply age shifts to base-year vintage profiles.

    A positive shift models an older starting fleet; negative models younger.
    Total stock is preserved after shifting.

    Ported from sales_workflow.py::derive_initial_fleet_age_shift_vintage_profiles.

    Args:
        vintage_profiles: Dict mapping vehicle_type → pd.Series (age → share).
        age_shift_years: Scalar or dict of shifts per vehicle type.

    Returns:
        (shifted_profiles_dict, diagnostics_DataFrame)
    """
    diagnostics_cols = [
        "vehicle_type", "requested_shift_years",
        "baseline_average_age_years", "shifted_average_age_years",
        "implied_average_age_delta_years",
    ]
    if age_shift_years is None:
        return {}, pd.DataFrame(columns=diagnostics_cols)

    shifted_profiles: dict[str, pd.Series] = {}
    diag_rows: list[dict] = []

    for vt, profile in vintage_profiles.items():
        requested = _resolve_vehicle_scalar(age_shift_years, vt, default=0.0)
        base_profile = pd.Series(profile, dtype=float).sort_index()
        if base_profile.empty:
            continue
        shifted = _shift_vintage_by_age(base_profile, age_shift_years=requested)
        baseline_avg = _average_age(base_profile)
        shifted_avg = _average_age(shifted)

        if abs(float(requested)) > 1e-12:
            shifted_profiles[str(vt)] = shifted

        diag_rows.append({
            "vehicle_type": str(vt),
            "requested_shift_years": float(requested),
            "baseline_average_age_years": float(baseline_avg),
            "shifted_average_age_years": float(shifted_avg),
            "implied_average_age_delta_years": float(shifted_avg - baseline_avg),
        })

    return shifted_profiles, pd.DataFrame(diag_rows, columns=diagnostics_cols)


def merge_turnover_policies(
    policy_a: dict[str, Any] | None,
    policy_b: dict[str, Any] | None,
    years: pd.Index,
) -> dict[str, Any]:
    """
    Merge two turnover-policy dicts.

    additional_retirement_rate is additive (capped [0, 1]).
    survival_multiplier is multiplicative (>=0).
    age_multipliers and survival_multipliers_by_age are multiplied element-wise.

    Ported from sales_workflow.py::_merge_turnover_policies.
    """
    years = pd.Index(years, dtype=int)
    base = {str(k): dict(v) for k, v in (policy_a or {}).items()}
    extra = {str(k): dict(v) for k, v in (policy_b or {}).items()}

    merged: dict[str, dict[str, Any]] = {k: dict(v) for k, v in base.items()}
    for vk, extra_policy in extra.items():
        current = dict(merged.get(vk, {}))

        base_rate = current.get("additional_retirement_rate")
        extra_rate = extra_policy.get("additional_retirement_rate")
        if base_rate is not None or extra_rate is not None:
            current["additional_retirement_rate"] = (
                _coerce_year_schedule(base_rate, years, default=0.0)
                + _coerce_year_schedule(extra_rate, years, default=0.0)
            ).clip(lower=0.0, upper=1.0)

        base_sm = current.get("survival_multiplier")
        extra_sm = extra_policy.get("survival_multiplier")
        if base_sm is not None or extra_sm is not None:
            current["survival_multiplier"] = (
                _coerce_year_schedule(base_sm, years, default=1.0)
                * _coerce_year_schedule(extra_sm, years, default=1.0)
            ).clip(lower=0.0)

        for key in ("age_multipliers", "survival_multipliers_by_age"):
            bv = current.get(key)
            ev = extra_policy.get(key)
            if bv is None and ev is None:
                continue
            current[key] = _multiply_age_profiles(bv, ev)

        for key, value in extra_policy.items():
            if key not in {"additional_retirement_rate", "survival_multiplier",
                           "age_multipliers", "survival_multipliers_by_age"}:
                if key not in current:
                    current[key] = value

        merged[vk] = current

    return merged


def subtract_turnover_policies(
    base_policy: dict[str, Any] | None,
    policy_to_remove: dict[str, Any] | None,
    years: pd.Index,
) -> dict[str, Any]:
    """
    Subtract one turnover policy from another (for counterfactual analysis).

    Currently only additional_retirement_rate is subtracted; other keys are kept.

    Ported from sales_workflow.py::_subtract_turnover_policies.
    """
    years = pd.Index(years, dtype=int)
    out: dict[str, dict[str, Any]] = {str(k): dict(v) for k, v in (base_policy or {}).items()}
    sub = {str(k): dict(v) for k, v in (policy_to_remove or {}).items()}

    for vk, sub_policy in sub.items():
        current = dict(out.get(vk, {}))
        total_rate = current.get("additional_retirement_rate")
        sub_rate = sub_policy.get("additional_retirement_rate")
        if total_rate is not None or sub_rate is not None:
            remaining = (
                _coerce_year_schedule(total_rate, years, default=0.0)
                - _coerce_year_schedule(sub_rate, years, default=0.0)
            ).clip(lower=0.0, upper=1.0)
            if float(remaining.max()) > 1e-12:
                current["additional_retirement_rate"] = remaining
            else:
                current.pop("additional_retirement_rate", None)

        if current:
            out[vk] = current
        elif vk in out:
            out.pop(vk, None)

    return out


# ===========================================================================
# Lifecycle calibration
# ===========================================================================

# Maps LEAP vehicle type labels to transport type, used to look up the right
# row in lifecycle_factors (which is keyed by transport_type).
_VEHICLE_TYPE_TO_TRANSPORT: dict[str, str] = {
    "LPVs":        "passenger",
    "Motorcycles": "passenger",
    "Buses":       "passenger",
    "Trucks":      "freight",
    "LCVs":        "freight",
}


def _annual_to_cumulative(annual: pd.Series) -> pd.Series:
    """Convert annual survival probabilities to cumulative survival S(age), S(0)=1."""
    s = pd.Series(annual, dtype=float).sort_index().clip(0.0, 1.0)
    vals = s.to_numpy()
    cumul = np.concatenate([[1.0], np.cumprod(vals[:-1])])
    return pd.Series(cumul, index=s.index, dtype=float)


def _implied_turnover_rate(annual: pd.Series) -> float:
    """
    Implied steady-state annual turnover rate from an annual survival curve.

    In steady state: total_stock = sales/year × Σ S(a)/S(0)
    So: turnover = sales/total_stock = 1 / Σ S(a)/S(0)
    """
    cumul = _annual_to_cumulative(annual)
    return float(1.0 / cumul.sum()) if cumul.sum() > 0 else float("nan")


def _scale_age_band(
    cumul: pd.Series,
    age_min: int,
    age_max: int,
    factor: float,
) -> pd.Series:
    """Scale cumulative survival values in age_min..age_max by factor."""
    c = cumul.copy()
    mask = (c.index >= age_min) & (c.index <= age_max)
    c.loc[mask] = (c.loc[mask] * factor).clip(upper=1.0)
    return c


def _smooth_survival(cumul: pd.Series, window: int) -> pd.Series:
    """Apply a single moving-average pass (half-width = window) to cumulative survival."""
    if window < 1:
        return cumul.copy()
    c = cumul.copy()
    ages = c.index.tolist()
    vals = c.to_numpy(dtype=float)
    n = len(vals)
    smoothed = np.empty(n, dtype=float)
    for i in range(n):
        lo = max(0, i - window)
        hi = min(n - 1, i + window)
        smoothed[i] = vals[lo: hi + 1].mean()
    return pd.Series(smoothed, index=ages, dtype=float)


def _enforce_survival_rules(cumul: pd.Series) -> pd.Series:
    """
    Enforce survival curve constraints:
    - S(0) = 1.0
    - Strictly non-increasing (running minimum across ages)
    - All values clipped to [0, 1]
    """
    c = cumul.clip(0.0, 1.0).copy()
    ages = sorted(c.index)
    c.loc[ages[0]] = 1.0
    running_min = 1.0
    for age in ages[1:]:
        running_min = min(running_min, float(c.loc[age]))
        c.loc[age] = running_min
    return c


def survival_to_vintage_dynamic(
    annual: pd.Series,
    n_years: int = 400,
) -> pd.Series:
    """
    Derive steady-state vintage profile using dynamic cohort simulation.

    More accurate than the simple proportional method (survival_to_vintage)
    because it uses the same annual-survival cohort logic as the stock-flow model.

    Starting from all stock at age 0, runs the cohort model for n_years until
    the age distribution converges. Returns normalised shares summing to 1.

    Args:
        annual: pd.Series of annual survival probabilities indexed by age.
        n_years: Number of simulation years (default 400 is more than enough
            for convergence for any realistic survival curve).

    Returns:
        pd.Series of vintage shares indexed by age, summing to 1.
    """
    s = _normalise_survival(pd.Series(annual, dtype=float).sort_index())
    ages = s.index.tolist()
    max_age = ages[-1]
    surv_probs = s.to_numpy(dtype=float)

    stock = np.zeros(len(ages), dtype=float)
    stock[0] = 1.0

    for _ in range(n_years):
        new_stock = np.zeros_like(stock)
        retirements = 0.0
        for i, age in enumerate(ages):
            current = stock[i]
            if age == max_age:
                retirements += current
            else:
                survivors = current * surv_probs[i]
                retirements += current - survivors
                new_stock[i + 1] += survivors
        new_stock[0] += retirements
        stock = new_stock

    total = stock.sum() or 1.0
    return pd.Series(stock / total, index=ages, dtype=float)


def _calibrate_single(
    annual: pd.Series,
    factors_row: pd.Series,
) -> tuple[pd.Series, pd.Series, dict]:
    """
    Calibrate one survival curve according to a lifecycle_factors row.

    fit_mode values:
        "auto"        — binary-search scale_age_band_factor to hit turnover bounds
        "manual"      — apply provided scale_age_band_factor; warn if out of bounds
        "passthrough" — use curve as-is; warn if out of bounds

    Returns:
        (calibrated_annual, calibrated_vintage, diagnostics_dict)
    """
    fit_mode = str(factors_row.get("fit_mode", "auto") or "auto").strip().lower()
    lower = float(factors_row.get("turnover_rate_lower", 0.03) or 0.03)
    upper = float(factors_row.get("turnover_rate_upper", 0.07) or 0.07)
    age_min = int(factors_row.get("scale_age_band_age_min", 4) or 4)
    age_max = int(factors_row.get("scale_age_band_age_max", 15) or 15)
    window = int(factors_row.get("smoothing_window", 1) or 1)

    initial_rate = _implied_turnover_rate(annual)

    def _apply_factor(annual_in: pd.Series, factor: float) -> pd.Series:
        cumul = _annual_to_cumulative(annual_in)
        cumul = _scale_age_band(cumul, age_min, age_max, factor)
        if window >= 1:
            cumul = _smooth_survival(cumul, window)
        cumul = _enforce_survival_rules(cumul)
        return cumulative_to_annual_survival(cumul)

    scale_factor_used = 1.0

    if fit_mode == "passthrough":
        calibrated = annual.copy()
        if not (lower <= initial_rate <= upper):
            log.warning(
                "passthrough: implied turnover rate %.4f outside bounds [%.3f, %.3f]",
                initial_rate, lower, upper,
            )
    elif fit_mode == "manual":
        raw_factor = factors_row.get("scale_age_band_factor")
        scale_factor_used = float(raw_factor) if pd.notna(raw_factor) else 1.0
        calibrated = _apply_factor(annual, scale_factor_used)
        final_rate = _implied_turnover_rate(calibrated)
        if not (lower <= final_rate <= upper):
            log.warning(
                "manual: implied turnover rate %.4f outside bounds [%.3f, %.3f] "
                "after scale_factor=%.4f",
                final_rate, lower, upper, scale_factor_used,
            )
    else:
        # auto — binary search for scale factor
        rate_at_low = _implied_turnover_rate(_apply_factor(annual, 0.1))
        rate_at_high = _implied_turnover_rate(_apply_factor(annual, 10.0))

        if lower <= initial_rate <= upper:
            # Already in bounds — no adjustment needed
            calibrated = annual.copy()
            scale_factor_used = 1.0
        elif rate_at_low > upper:
            log.warning(
                "auto: cannot reach turnover rate <= %.3f (min achievable %.4f); "
                "using scale_factor=0.1",
                upper, rate_at_low,
            )
            calibrated = _apply_factor(annual, 0.1)
            scale_factor_used = 0.1
        elif rate_at_high < lower:
            log.warning(
                "auto: cannot reach turnover rate >= %.3f (max achievable %.4f); "
                "using scale_factor=10.0",
                lower, rate_at_high,
            )
            calibrated = _apply_factor(annual, 10.0)
            scale_factor_used = 10.0
        else:
            # Bisect: higher factor → lower turnover rate
            # We want lower <= rate <= upper
            # rate decreases as factor increases
            lo_f, hi_f = 0.1, 10.0
            target = (lower + upper) / 2.0
            for _ in range(50):
                mid_f = (lo_f + hi_f) / 2.0
                mid_rate = _implied_turnover_rate(_apply_factor(annual, mid_f))
                if mid_rate > target:
                    lo_f = mid_f  # rate too high → need larger factor
                else:
                    hi_f = mid_f
                if (hi_f - lo_f) < 1e-6:
                    break
            scale_factor_used = (lo_f + hi_f) / 2.0
            calibrated = _apply_factor(annual, scale_factor_used)

    vintage = survival_to_vintage_dynamic(calibrated)
    final_rate = _implied_turnover_rate(calibrated)

    diag = {
        "initial_turnover_rate": initial_rate,
        "turnover_rate": final_rate,
        "turnover_rate_lower": lower,
        "turnover_rate_upper": upper,
        "fit_mode": fit_mode,
        "scale_factor_used": scale_factor_used,
        "in_bounds": lower <= final_rate <= upper,
    }
    return calibrated, vintage, diag


def calibrate_survival_and_vintage(
    survival_curves: dict[str, pd.Series],
    vintage_profiles: dict[str, pd.Series],
    lifecycle_factors: pd.DataFrame,
    vehicle_type_to_transport: dict[str, str] | None = None,
) -> tuple[dict[str, pd.Series], dict[str, pd.Series], pd.DataFrame]:
    """
    Calibrate all survival curves to meet turnover rate bounds and re-derive vintages.

    Vehicle types not covered by lifecycle_factors are returned unchanged.

    Args:
        survival_curves: Dict of vehicle_type → annual survival probabilities.
        vintage_profiles: Dict of vehicle_type → vintage shares.
        lifecycle_factors: DataFrame from load_lifecycle_profile_factors() with
            columns transport_type, turnover_rate_lower, turnover_rate_upper,
            fit_mode, etc.
        vehicle_type_to_transport: Optional override mapping. Defaults to
            _VEHICLE_TYPE_TO_TRANSPORT.

    Returns:
        (calibrated_survival_curves, calibrated_vintage_profiles, diagnostics_df)
        where diagnostics_df has one row per vehicle type.
    """
    vt_map = vehicle_type_to_transport or _VEHICLE_TYPE_TO_TRANSPORT
    factors_by_transport: dict[str, pd.Series] = {}
    for _, row in lifecycle_factors.iterrows():
        tt = str(row.get("transport_type", "")).strip().lower()
        if tt:
            factors_by_transport[tt] = row

    calibrated_survival: dict[str, pd.Series] = {}
    calibrated_vintage: dict[str, pd.Series] = {}
    diag_rows: list[dict] = []

    for vt, annual in survival_curves.items():
        transport_type = vt_map.get(str(vt), "")
        factors_row = factors_by_transport.get(transport_type)

        if factors_row is None:
            calibrated_survival[vt] = annual
            calibrated_vintage[vt] = vintage_profiles.get(vt, survival_to_vintage_dynamic(annual))
            log.debug("No lifecycle factors for %s (transport_type=%s) — unchanged", vt, transport_type)
            continue

        cal_annual, cal_vintage, diag = _calibrate_single(annual, factors_row)
        calibrated_survival[vt] = cal_annual
        calibrated_vintage[vt] = cal_vintage
        diag_rows.append({"vehicle_type": vt, "transport_type": transport_type, **diag})

    for vt, vintage in vintage_profiles.items():
        if vt not in calibrated_vintage:
            calibrated_vintage[vt] = vintage

    diag_df = pd.DataFrame(diag_rows) if diag_rows else pd.DataFrame(
        columns=["vehicle_type", "transport_type", "initial_turnover_rate",
                 "turnover_rate", "turnover_rate_lower", "turnover_rate_upper",
                 "fit_mode", "scale_factor_used", "in_bounds"]
    )
    return calibrated_survival, calibrated_vintage, diag_df


# ===========================================================================
# File loaders
# ===========================================================================

def load_survival_curve(path: str, *, cumulative: bool = True) -> pd.Series:
    """
    Load a survival curve from the LEAP lifecycle profile Excel format.

    Expected Excel format:
        Sheet: 'Lifecycle Profiles'
        Rows 0–2: header block (skipped)
        Row 3: Year | Value headers
        Row 4+: <age> | <survival_value>

    Args:
        path: Path to Excel file.
        cumulative: If True (default), converts cumulative S(age) to annual p(age).

    Returns:
        pd.Series indexed by age (annual survival probabilities, 0–1).
    """
    df = _read_lifecycle_excel(path)
    series = pd.Series(df["Value"].values, index=pd.Index(df["Year"].values, dtype=int))
    if series.max() > 1.5:
        series = series / 100.0
    series = series.clip(0.0, 1.0)
    if cumulative:
        series = cumulative_to_annual_survival(series)
    return series.astype(float)


# ===========================================================================
# Survival and vintage helpers
# ===========================================================================

def _normalise_survival(s: pd.Series) -> pd.Series:
    """Ensure survival curve values are in [0, 1]. Accepts 0–100 input."""
    if s.max() > 1.5:
        s = s / 100.0
    return s.clip(0.0, 1.0)


def _normalise_vintage(v: pd.Series) -> pd.Series:
    """Ensure vintage profile sums to 1. Accepts 0–100 input."""
    if v.sum() > 1.5:
        v = v / 100.0
    total = v.sum()
    if total > 0:
        v = v / total
    return v


def _validate_and_align_age_profiles(
    survival_curve: pd.Series,
    vintage_profile: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """Ensure survival and vintage use the same contiguous integer age grid."""
    surv = pd.Series(survival_curve, dtype=float).sort_index()
    vint = pd.Series(vintage_profile, dtype=float).sort_index()

    if surv.empty or vint.empty:
        raise ValueError("survival_curve and vintage_profile must both be non-empty.")
    if not surv.index.is_unique or not vint.index.is_unique:
        raise ValueError("Age indices must not contain duplicates.")

    surv_ages = pd.to_numeric(pd.Index(surv.index), errors="coerce")
    vint_ages = pd.to_numeric(pd.Index(vint.index), errors="coerce")
    if surv_ages.isna().any() or vint_ages.isna().any():
        raise ValueError("Age indices must be numeric.")

    surv.index = pd.Index(np.round(surv_ages).astype(int), dtype=int)
    vint.index = pd.Index(np.round(vint_ages).astype(int), dtype=int)
    surv = surv.sort_index()
    vint = vint.sort_index()

    if not surv.index.equals(vint.index):
        raise ValueError("survival_curve and vintage_profile must use the same age index.")

    ages = surv.index.to_numpy(dtype=int)
    if len(ages) > 1 and not np.array_equal(np.diff(ages), np.ones(len(ages) - 1, dtype=int)):
        raise ValueError("Age indices must be contiguous with step 1.")

    return surv, vint


def _coerce_year_schedule(
    values: Any,
    years: pd.Index,
    *,
    default: float,
) -> pd.Series:
    """Convert scalar/Series/dict values into a year-indexed float Series."""
    if values is None:
        return pd.Series(float(default), index=years, dtype=float)
    if np.isscalar(values):
        return pd.Series(float(values), index=years, dtype=float)
    if isinstance(values, Mapping):
        schedule = pd.Series(dict(values), dtype=float)
    else:
        schedule = pd.Series(values, dtype=float)
    if schedule.empty:
        return pd.Series(float(default), index=years, dtype=float)
    idx = pd.to_numeric(pd.Index(schedule.index), errors="coerce")
    schedule = schedule.loc[~idx.isna()].copy()
    if schedule.empty:
        return pd.Series(float(default), index=years, dtype=float)
    schedule.index = pd.Index(idx[~idx.isna()].astype(int), dtype=int)
    schedule = schedule.groupby(level=0).mean().sort_index()
    return schedule.reindex(years).ffill().fillna(float(default)).astype(float)


def _coerce_age_profile(
    values: Any,
    ages: pd.Index,
    *,
    default: float,
) -> pd.Series:
    """Convert scalar/Series/dict values into an age-indexed float Series."""
    if values is None:
        return pd.Series(float(default), index=ages, dtype=float)
    if np.isscalar(values):
        return pd.Series(float(values), index=ages, dtype=float)
    if isinstance(values, Mapping):
        profile = pd.Series(dict(values), dtype=float)
    else:
        profile = pd.Series(values, dtype=float)
    if profile.empty:
        return pd.Series(float(default), index=ages, dtype=float)
    idx = pd.to_numeric(pd.Index(profile.index), errors="coerce")
    profile = profile.loc[~idx.isna()].copy()
    if profile.empty:
        return pd.Series(float(default), index=ages, dtype=float)
    profile.index = pd.Index(idx[~idx.isna()].astype(int), dtype=int)
    profile = profile.groupby(level=0).mean().sort_index()
    return profile.reindex(ages).fillna(float(default)).astype(float)


def _resolve_drive_policy_rates(
    drive_turnover_policy: Mapping[str, Any],
    years: pd.Index,
    drive_groups: dict[str, tuple[str, ...]],
) -> dict[str, pd.Series]:
    """Expand drive policy specs into per-drive additional-retirement schedules."""
    rates: dict[str, pd.Series] = {}
    for raw_key, spec in (drive_turnover_policy or {}).items():
        policy_key = str(raw_key).lower().strip()
        if spec is None:
            continue
        schedule_input: Any = None
        drive_list: list[str] = []

        if isinstance(spec, Mapping):
            drives_from_spec = spec.get("drives")
            schedule_input = spec.get("additional_retirement_rate", spec.get("rate"))
            if drives_from_spec is None:
                drive_list = list(drive_groups.get(policy_key, (policy_key,)))
            elif isinstance(drives_from_spec, str):
                drive_list = [drives_from_spec]
            else:
                drive_list = [str(d) for d in drives_from_spec]
            if schedule_input is None:
                cand = {k: v for k, v in spec.items() if str(k).strip().isdigit()}
                if cand:
                    schedule_input = cand
        else:
            drive_list = list(drive_groups.get(policy_key, (policy_key,)))
            schedule_input = spec

        if schedule_input is None:
            continue

        schedule = _coerce_year_schedule(schedule_input, years, default=0.0).clip(lower=0.0, upper=1.0)
        for drive in drive_list:
            dk = str(drive).lower().strip()
            if not dk:
                continue
            if dk in rates:
                rates[dk] = (rates[dk] + schedule).clip(lower=0.0, upper=1.0)
            else:
                rates[dk] = schedule.copy()

    return rates


def _resolve_vehicle_scalar(
    values: float | Mapping[str, Any] | None,
    vehicle_key: str,
    *,
    default: float,
) -> float:
    """Resolve scalar-or-mapping values to a specific vehicle key."""
    if values is None:
        return float(default)
    if np.isscalar(values):
        return float(values)
    if not isinstance(values, Mapping):
        raise TypeError("Expected scalar, mapping, or None.")
    norm = {str(k).lower().strip(): v for k, v in values.items()}
    for cand in (str(vehicle_key).lower().strip(), "all", "default", "*"):
        if cand in norm:
            return float(norm[cand])
    return float(default)


def _shift_vintage_by_age(vintage_profile: pd.Series, *, age_shift_years: float) -> pd.Series:
    """Shift vintage age distribution by interpolation, preserving normalisation."""
    profile = pd.Series(vintage_profile, dtype=float).sort_index()
    if profile.empty:
        return profile

    idx = pd.to_numeric(pd.Index(profile.index), errors="coerce")
    profile = profile.loc[~idx.isna()].copy()
    profile.index = pd.Index(idx[~idx.isna()].astype(int), dtype=int)
    profile = profile.groupby(level=0).mean().sort_index().clip(lower=0.0)
    total = float(profile.sum())
    if total <= 0.0:
        return profile
    profile = profile / total

    shift = float(age_shift_years)
    if abs(shift) < 1e-12:
        return profile.astype(float)

    ages = profile.index.to_numpy(dtype=float)
    vals = profile.to_numpy(dtype=float)
    shifted_vals = np.interp(ages - shift, ages, vals, left=0.0, right=0.0)
    shifted = pd.Series(np.clip(shifted_vals, 0.0, None), index=profile.index, dtype=float)
    shifted_total = float(shifted.sum())
    if shifted_total <= 0.0:
        return profile.astype(float)
    return (shifted / shifted_total).astype(float)


def _average_age(vintage_profile: pd.Series) -> float:
    """Compute average age from an age-share profile."""
    profile = pd.Series(vintage_profile, dtype=float).sort_index().clip(lower=0.0)
    if profile.empty:
        return 0.0
    total = float(profile.sum())
    if total <= 0.0:
        return 0.0
    ages = pd.to_numeric(pd.Index(profile.index), errors="coerce")
    valid = ~ages.isna()
    if not bool(valid.any()):
        return 0.0
    vals = profile.to_numpy(dtype=float)[valid]
    ages_arr = ages[valid].to_numpy(dtype=float)
    denom = float(vals.sum())
    if denom <= 0.0:
        return 0.0
    return float(np.dot(ages_arr, vals) / denom)


def _multiply_age_profiles(
    base_values: Any,
    extra_values: Any,
) -> float | pd.Series:
    """Multiply two age-based profile specs (scalar/Series/dict)."""
    if base_values is None and extra_values is None:
        return 1.0
    if np.isscalar(base_values) and np.isscalar(extra_values):
        return max(0.0, float(base_values) * float(extra_values))

    def _extract_ages(v: Any) -> pd.Index:
        if v is None or np.isscalar(v):
            return pd.Index([], dtype=int)
        if isinstance(v, Mapping):
            idx = pd.to_numeric(pd.Index(v.keys()), errors="coerce")
        else:
            idx = pd.to_numeric(pd.Index(pd.Series(v).index), errors="coerce")
        idx = idx[~idx.isna()]
        return pd.Index(np.unique(idx.astype(int)), dtype=int) if idx.size > 0 else pd.Index([], dtype=int)

    ages = _extract_ages(base_values).union(_extract_ages(extra_values))
    if ages.empty:
        bv = 1.0 if base_values is None else float(base_values)
        ev = 1.0 if extra_values is None else float(extra_values)
        return max(0.0, bv * ev)

    bp = _coerce_age_profile(base_values, ages, default=1.0)
    ep = _coerce_age_profile(extra_values, ages, default=1.0)
    return (bp * ep).clip(lower=0.0).astype(float)


def _read_lifecycle_excel(path: str) -> pd.DataFrame:
    """Read a lifecycle profile Excel file into a clean DataFrame."""
    df = pd.read_excel(path, sheet_name="Lifecycle Profiles", skiprows=3, names=["Year", "Value"])
    df = df.dropna(subset=["Year"])
    df["Year"] = pd.to_numeric(df["Year"], errors="coerce")
    df["Value"] = pd.to_numeric(df["Value"], errors="coerce")
    df = df.dropna(subset=["Year", "Value"])
    df = df[df["Year"].astype(int) == df["Year"]]
    df["Year"] = df["Year"].astype(int)
    return df
