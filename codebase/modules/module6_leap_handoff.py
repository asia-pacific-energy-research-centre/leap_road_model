"""
Module 6 — Road LEAP input package, base-year reconciliation, and Device Shares.

Creates the final Python-side road transport input package to pass into LEAP.

Workflow (per the design document):
    Step 1: Calculate initial branch energy
    Step 2: Reconcile BEV/PHEV electricity (before normal fuel reconciliation)
    Step 3: Calculate remaining ESTO fuel totals (after PHEV liquid subtraction)
    Step 4: Allocate remaining ESTO fuel to eligible branches
    Step 5: Derive energy correction factor per branch
    Step 6: Adjust stock, mileage, and efficiency simultaneously
    Step 7: Recalculate final branch fuel energy
    Step 8: Calculate implied vehicles and Device Shares
    Step 9: Validate

Outputs: T8–T12 DataFrames + T11_leap_ready.
"""

from __future__ import annotations

import logging
import pathlib
from typing import Any

import numpy as np
import pandas as pd
import yaml

from diagnostics.module_charts import write_module6_charts
from schemas.validation import validate_table

log = logging.getLogger(__name__)

_CONFIG_DIR = pathlib.Path(__file__).parent.parent / "config"

# Default reconciliation weights (see model_defaults.yaml)
_DEFAULT_WEIGHTS = {"stock": 0.50, "mileage": 0.25, "efficiency": 0.25}

_DEFAULT_SCALAR_BOUNDS: dict[str, tuple[float, float]] = {
    "stock": (0.0, np.inf),
    "mileage": (0.85, 1.15),
    "efficiency": (0.90, 1.10),
}

# Single-fuel drive types: device_share is always 1.0
_SINGLE_FUEL_DRIVES = {"BEV", "FCEV"}

# PHEV liquid fuels (separate from PHEV electric)
_PHEV_LIQUID_FUELS = {"Motor gasoline", "Gas and diesel oil", "Biodiesel", "Biogasoline", "Efuel"}

_FUEL_ELIGIBILITY: dict[str, list[str]] | None = None


def _get_fuel_eligibility() -> dict[str, list[str]]:
    """Return drive_type → [eligible fuels] from fuel_mappings.yaml (cached)."""
    global _FUEL_ELIGIBILITY
    if _FUEL_ELIGIBILITY is None:
        with open(_CONFIG_DIR / "fuel_mappings.yaml") as fh:
            cfg = yaml.safe_load(fh)
        result: dict[str, list[str]] = {}
        for drive, groups in cfg["drive_fuel_eligibility"].items():
            fuels: list[str] = []
            for group_fuels in groups.values():
                fuels.extend(group_fuels)
            result[drive] = fuels
        _FUEL_ELIGIBILITY = result
    return _FUEL_ELIGIBILITY


def _tech_path(fuel_branch_path: str) -> str:
    """Strip the fuel component from a fuel-level LEAP branch path."""
    parts = fuel_branch_path.rsplit("\\", 1)
    return parts[0] if len(parts) > 1 else fuel_branch_path


# ===========================================================================
# Public entry point
# ===========================================================================

def run_module6(
    base_year_branches: pd.DataFrame,
    sales_turnover: pd.DataFrame,
    sales_shares: pd.DataFrame,
    esto_fuel_totals: pd.DataFrame,
    projection_years: list[int],
    reconciliation_weights: dict[str, float] | None = None,
    phev_electric_utilisation_rate: float | dict[str, float] = 0.50,
    scalar_bounds: tuple[float, float] | dict[str, tuple[float, float]] | None = None,
    match_tolerance: float = 0.01,
    diagnostics_dir: str | pathlib.Path | None = None,
) -> dict[str, pd.DataFrame]:
    """
    Run Module 6: build LEAP input package with reconciled base-year values.

    Args:
        base_year_branches: T4_base_year_branches from Module 2.
        sales_turnover: T6_sales_turnover from Module 4.
        sales_shares: T7_sales_shares from Module 5.
        esto_fuel_totals: DataFrame with columns [fuel, energy_pj] —
            ESTO road fuel totals for the base year.
        projection_years: Full year range (e.g. range(2022, 2061)).
        reconciliation_weights: Optional override for {stock, mileage, efficiency}.
        phev_electric_utilisation_rate: PHEV fraction driven on electricity.
            Can be a scalar or dict mapping vehicle_type → rate.
                scalar_bounds: Reconciliation scalar bounds. Supports either:
                        - tuple(min_scalar, max_scalar) applied to all scalars (legacy), or
                        - dict with keys {'stock','mileage','efficiency'} each mapping to
                            (min_scalar, max_scalar).
        match_tolerance: Acceptable fractional gap between model and ESTO.
                diagnostics_dir: Optional directory root for Module 6 PNG diagnostic
                    charts. When provided, charts are written to
                    diagnostics_dir/module6/.

    Returns:
        Dict with keys: T8, T9, T10, T11, T12 — each a DataFrame.
    """
    weights = reconciliation_weights or _DEFAULT_WEIGHTS
    scalar_bounds = scalar_bounds or _DEFAULT_SCALAR_BOUNDS
    assert abs(sum(weights.values()) - 1.0) < 1e-6, "Reconciliation weights must sum to 1.0"

    # Step 1
    branch_energy = calculate_initial_branch_energy(base_year_branches)

    # Step 2: BEV/PHEV electricity reconciliation
    electricity_esto = _get_esto_fuel(esto_fuel_totals, "Electricity")
    branch_energy, phev_liquid = reconcile_electricity(
        branch_energy, electricity_esto, phev_electric_utilisation_rate, weights, scalar_bounds
    )

    # Step 3: Remaining ESTO after PHEV liquid subtraction
    remaining_esto = calculate_remaining_esto(esto_fuel_totals, phev_liquid)

    # Step 4: Fuel allocation
    t8 = allocate_esto_fuel_to_branches(branch_energy, remaining_esto, base_year_branches)

    # Steps 5–7: Simultaneous reconciliation
    t9 = reconcile_stock_mileage_efficiency(t8, base_year_branches, weights, scalar_bounds)

    # Step 8: Device Shares
    t10 = calculate_device_shares(t9)

    # Step 9: Validate
    t12 = build_reconciliation_diagnostics(t9, esto_fuel_totals, phev_liquid, match_tolerance)

    # Build LEAP-ready output
    t11 = build_leap_ready_table(t9, t10, sales_turnover, sales_shares, projection_years)

    errors = validate_table(t11, "T11_leap_ready")
    for err in errors:
        log.warning("Validation: %s", err)
    outputs = {"T8": t8, "T9": t9, "T10": t10, "T11": t11, "T12": t12}

    if diagnostics_dir is not None:
        try:
            written = write_module6_charts(outputs, diagnostics_dir)
            log.info("Module 6 diagnostics: wrote %d chart(s)", len(written))
        except Exception as exc:
            log.warning("Module 6 diagnostics chart generation failed: %s", exc)

    return outputs


# ===========================================================================
# Step 1 — Initial branch energy
# ===========================================================================

def calculate_initial_branch_energy(base_year_branches: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate initial branch energy from base-year stock, mileage, and efficiency.

    initial_energy_pj = stock × mileage / efficiency_km_per_gj / 1_000_000

    Args:
        base_year_branches: T4_base_year_branches DataFrame.

    Returns:
        DataFrame with all T4 columns plus 'initial_energy_pj'.
    """
    df = base_year_branches.copy()
    df["initial_energy_pj"] = (
        df["stock"] * df["mileage_km_per_year"] / df["efficiency_km_per_gj"] / 1_000_000
    )
    return df


# ===========================================================================
# Step 2 — BEV/PHEV electricity reconciliation
# ===========================================================================

def reconcile_electricity(
    branch_energy: pd.DataFrame,
    electricity_esto_pj: float,
    phev_utilisation_rate: float | dict[str, float],
    weights: dict[str, float],
    scalar_bounds: tuple[float, float] | dict[str, tuple[float, float]],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Reconcile BEV and PHEV electricity use to ESTO road electricity.

    Uses the same iterative bounded stock/mileage/efficiency adjustment as Steps 5–6.
    After reconciliation, derives PHEV liquid fuel consumption from adjusted stock.

    Returns:
        (updated_branch_energy, phev_liquid_table)
        phev_liquid_table has columns [vehicle_type, drive_type, fuel, phev_liquid_pj]
    """
    df = branch_energy.copy()
    elec_mask = df["fuel"] == "Electricity"

    # Build phev_liquid_table from unadjusted data if reconciliation cannot run
    def _build_phev_liquid(source_df: pd.DataFrame) -> pd.DataFrame:
        return _compute_phev_liquid(source_df, phev_utilisation_rate)

    if electricity_esto_pj <= 0 or not elec_mask.any():
        return df, _build_phev_liquid(df)

    total_initial_elec = df.loc[elec_mask, "initial_energy_pj"].sum()
    if total_initial_elec <= 0:
        return df, _build_phev_liquid(df)

    ecf = electricity_esto_pj / total_initial_elec

    # Apply scalars to all electricity branches
    for idx in df[elec_mask].index:
        s = df.at[idx, "stock"]
        m = df.at[idx, "mileage_km_per_year"]
        e = df.at[idx, "efficiency_km_per_gj"]
        _, _, _, adj_s, adj_m, adj_e, within = apply_scalars(s, m, e, ecf, weights, scalar_bounds)
        df.at[idx, "stock"] = adj_s
        df.at[idx, "mileage_km_per_year"] = adj_m
        df.at[idx, "efficiency_km_per_gj"] = adj_e
        df.at[idx, "initial_energy_pj"] = adj_s * adj_m / adj_e / 1_000_000
        if not within:
            path = df.at[idx, "leap_branch_path"] if "leap_branch_path" in df.columns else "?"
            log.warning("Electricity reconciliation: scalar out of bounds for %s (ECF=%.3f)", path, ecf)

    # Propagate adjusted stock to PHEV liquid branches (same fleet, shared stock).
    # Index must include size to avoid duplicate entries when vehicle types have
    # multiple size variants (e.g. LPVs medium + LPVs large).
    _idx_cols = ["economy", "scenario", "transport_type", "vehicle_type"]
    _has_size = "size" in df.columns and df["size"].notna().any()
    if _has_size:
        _idx_cols.append("size")
    phev_elec_stock = (
        df[(df["drive_type"] == "PHEV") & elec_mask]
        .set_index(_idx_cols)["stock"]
        if all(c in df.columns for c in _idx_cols)
        else pd.Series(dtype=float)
    )
    if not phev_elec_stock.empty:
        phev_liq_mask = (df["drive_type"] == "PHEV") & (~elec_mask)
        for idx in df[phev_liq_mask].index:
            key = tuple(df.at[idx, c] for c in _idx_cols)
            if key in phev_elec_stock.index:
                df.at[idx, "stock"] = phev_elec_stock[key]

    phev_liquid = _build_phev_liquid(df)
    return df, phev_liquid


def _compute_phev_liquid(
    branch_energy: pd.DataFrame,
    phev_utilisation_rate: float | dict[str, float],
) -> pd.DataFrame:
    """
    Compute PHEV liquid fuel consumption from adjusted PHEV liquid branches.

    For each PHEV liquid branch: phev_liquid_pj = stock × mileage / efficiency / 1e6.
    The mileage in PHEV liquid rows already represents the liquid-mode km fraction
    (= total_mileage × (1 - utilisation_rate)).
    """
    phev_liq = branch_energy[
        (branch_energy["drive_type"] == "PHEV")
        & (~branch_energy["fuel"].isin(["Electricity"]))
    ].copy()

    if phev_liq.empty:
        return pd.DataFrame(columns=["vehicle_type", "drive_type", "fuel", "phev_liquid_pj"])

    phev_liq["phev_liquid_pj"] = (
        phev_liq["stock"] * phev_liq["mileage_km_per_year"] / phev_liq["efficiency_km_per_gj"] / 1_000_000
    )

    keep = ["vehicle_type", "drive_type", "fuel", "phev_liquid_pj"]
    for extra in ["economy", "scenario", "transport_type"]:
        if extra in phev_liq.columns:
            keep.insert(0, extra)

    return phev_liq[[c for c in keep if c in phev_liq.columns]].reset_index(drop=True)


# ===========================================================================
# Step 3 — Remaining ESTO fuel totals
# ===========================================================================

def calculate_remaining_esto(
    esto_fuel_totals: pd.DataFrame,
    phev_liquid_table: pd.DataFrame,
) -> pd.DataFrame:
    """
    Subtract PHEV liquid fuel from ESTO gasoline/diesel before normal reconciliation.

    remaining_gasoline = ESTO_gasoline - PHEV_gasoline
    remaining_diesel   = ESTO_diesel   - PHEV_diesel

    Returns:
        DataFrame with columns:
        [fuel, esto_fuel_total_pj, phev_liquid_subtracted_pj, remaining_esto_fuel_pj]
    """
    if phev_liquid_table.empty:
        phev_by_fuel: dict[str, float] = {}
    else:
        phev_by_fuel = phev_liquid_table.groupby("fuel")["phev_liquid_pj"].sum().to_dict()

    rows = []
    for _, row in esto_fuel_totals.iterrows():
        fuel = row["fuel"]
        esto_total = float(row["energy_pj"])
        phev_liquid = float(phev_by_fuel.get(fuel, 0.0))
        remaining = max(0.0, esto_total - phev_liquid)
        rows.append({
            "fuel": fuel,
            "esto_fuel_total_pj": esto_total,
            "phev_liquid_subtracted_pj": phev_liquid,
            "remaining_esto_fuel_pj": remaining,
        })

    return pd.DataFrame(rows)


# ===========================================================================
# Step 4 — Fuel allocation
# ===========================================================================

def allocate_esto_fuel_to_branches(
    branch_energy: pd.DataFrame,
    remaining_esto: pd.DataFrame,
    base_year_branches: pd.DataFrame,
) -> pd.DataFrame:
    """
    Allocate remaining ESTO fuel totals across eligible vehicle-drive branches.

    For each fuel type, eligible branches are identified via fuel_mappings.yaml
    drive_fuel_eligibility. Allocation is proportional to branch stock
    (allocation_rule = "stock_share").

    Returns T8_fuel_allocation DataFrame.
    """
    eligibility = _get_fuel_eligibility()

    # Filter to only (drive_type, fuel) combinations that are eligible
    def _is_eligible(row: pd.Series) -> bool:
        return row["fuel"] in eligibility.get(row["drive_type"], [])

    eligible_mask = branch_energy.apply(_is_eligible, axis=1)
    n_ineligible = (~eligible_mask).sum()
    if n_ineligible > 0:
        log.warning(
            "%d branch rows have ineligible (drive_type, fuel) combinations — excluded from T8",
            n_ineligible,
        )

    df = branch_energy[eligible_mask].copy()

    # Join with remaining_esto on fuel
    df = df.merge(remaining_esto, on="fuel", how="left")
    df["esto_fuel_total_pj"] = df["esto_fuel_total_pj"].fillna(0.0)
    df["phev_liquid_subtracted_pj"] = df["phev_liquid_subtracted_pj"].fillna(0.0)
    df["remaining_esto_fuel_pj"] = df["remaining_esto_fuel_pj"].fillna(0.0)

    # Stock shares per (economy, scenario, fuel) group
    # Use post-electricity-reconciliation stock for accurate shares
    group_keys = ["economy", "scenario", "fuel"]
    total_stock = df.groupby(group_keys)["stock"].transform("sum")
    df["branch_allocation_share"] = (df["stock"] / total_stock.replace(0.0, np.nan)).fillna(0.0)
    df["allocated_branch_fuel_pj"] = df["branch_allocation_share"] * df["remaining_esto_fuel_pj"]
    df["allocation_rule"] = "stock_share"

    t8_cols = [
        "economy", "scenario", "transport_type", "vehicle_type", "drive_type", "fuel",
        "esto_fuel_total_pj", "phev_liquid_subtracted_pj", "remaining_esto_fuel_pj",
        "branch_allocation_share", "allocated_branch_fuel_pj", "allocation_rule",
    ]
    # Carry optional dimension columns through
    for extra in ["size", "leap_branch_path"]:
        if extra in df.columns:
            t8_cols.insert(t8_cols.index("fuel") + 1, extra)

    return df[[c for c in t8_cols if c in df.columns]].reset_index(drop=True)


# ===========================================================================
# Steps 5–7 — Simultaneous reconciliation
# ===========================================================================

def reconcile_stock_mileage_efficiency(
    fuel_allocation: pd.DataFrame,
    base_year_branches: pd.DataFrame,
    weights: dict[str, float],
    scalar_bounds: tuple[float, float] | dict[str, tuple[float, float]],
) -> pd.DataFrame:
    """
    Apply iterative simultaneous stock, mileage, and efficiency adjustment.

    energy_correction_factor = allocated_fuel / initial_energy

    stock_scalar     = ecf ^ stock_weight
    mileage_scalar   = ecf ^ mileage_weight
    efficiency_scalar = ecf ^ (-efficiency_weight)  ← inverse because higher efficiency = less energy

    Bounded scalars are reapplied iteratively against the residual energy gap so
    branches can continue moving after a clamp on mileage or efficiency.

    Returns T9_reconciliation_scalars DataFrame.
    """
    join_keys = ["economy", "scenario", "transport_type", "vehicle_type", "drive_type", "fuel"]
    if "size" in fuel_allocation.columns and "size" in base_year_branches.columns:
        join_keys.append("size")

    base_cols = join_keys + ["stock", "mileage_km_per_year", "efficiency_km_per_gj"]
    if "leap_branch_path" in base_year_branches.columns:
        base_cols.append("leap_branch_path")
    if "base_year" in base_year_branches.columns:
        base_cols.append("base_year")

    base_cols = [c for c in base_cols if c in base_year_branches.columns]

    # Drop leap_branch_path from fuel_allocation before merge to avoid duplicate cols
    t8 = fuel_allocation.drop(columns=["leap_branch_path"], errors="ignore")

    merged = t8.merge(base_year_branches[base_cols], on=join_keys, how="left")

    # Initial energy from ORIGINAL base_year_branches (pre-electricity-reconciliation)
    merged["initial_branch_energy_pj"] = (
        merged["stock"] * merged["mileage_km_per_year"] / merged["efficiency_km_per_gj"] / 1_000_000
    )

    ecf_vals = (
        merged["allocated_branch_fuel_pj"] / merged["initial_branch_energy_pj"].replace(0.0, np.nan)
    ).fillna(1.0)
    merged["energy_correction_factor"] = ecf_vals

    max_iterations = 12
    energy_tolerance = 1e-9

    scalar_rows: list[dict] = []
    for i, (_, row) in enumerate(merged.iterrows()):
        s = row["stock"]
        m = row["mileage_km_per_year"]
        e = row["efficiency_km_per_gj"]
        ecf = row["energy_correction_factor"]

        allocated_branch_fuel_pj = float(row.get("allocated_branch_fuel_pj", 0.0))

        ss = ms = es = 1.0
        adj_s = s
        adj_m = m
        adj_e = e
        within = True
        iterations_used = 0

        if allocated_branch_fuel_pj <= 0 or ecf <= 0:
            ss, ms, es, adj_s, adj_m, adj_e, within = apply_scalars(s, m, e, ecf, weights, scalar_bounds)
            final_branch_fuel_pj = 0.0
            iterations_used = 1
        elif row["initial_branch_energy_pj"] <= 0:
            ss, ms, es, adj_s, adj_m, adj_e, within = apply_scalars(s, m, e, ecf, weights, scalar_bounds)
            final_branch_fuel_pj = adj_s * adj_m / adj_e / 1_000_000 if adj_e > 0 else 0.0
            iterations_used = 1
        else:
            prev_final_branch_fuel_pj = row["initial_branch_energy_pj"]
            for iteration in range(1, max_iterations + 1):
                current_branch_fuel_pj = adj_s * adj_m / adj_e / 1_000_000 if adj_e > 0 else 0.0
                if current_branch_fuel_pj <= 0:
                    within = False
                    final_branch_fuel_pj = 0.0
                    iterations_used = iteration - 1
                    break

                ecf_iter = allocated_branch_fuel_pj / current_branch_fuel_pj
                ss_step, ms_step, es_step, adj_s_new, adj_m_new, adj_e_new, within_step = apply_scalars(
                    adj_s, adj_m, adj_e, ecf_iter, weights, scalar_bounds
                )

                ss *= ss_step
                ms *= ms_step
                es *= es_step
                adj_s, adj_m, adj_e = adj_s_new, adj_m_new, adj_e_new
                final_branch_fuel_pj = adj_s * adj_m / adj_e / 1_000_000 if adj_e > 0 else 0.0
                iterations_used = iteration
                within = within and within_step

                if abs(final_branch_fuel_pj - allocated_branch_fuel_pj) <= max(
                    allocated_branch_fuel_pj * energy_tolerance,
                    energy_tolerance,
                ):
                    break

                if abs(final_branch_fuel_pj - prev_final_branch_fuel_pj) <= max(
                    prev_final_branch_fuel_pj * energy_tolerance,
                    energy_tolerance,
                ):
                    break

                prev_final_branch_fuel_pj = final_branch_fuel_pj

            else:
                log.warning(
                    "Iterative reconciliation reached max iterations: %s / %s / %s / %s (target=%.6f, final=%.6f)",
                    row.get("economy", "?"), row.get("vehicle_type", "?"),
                    row.get("drive_type", "?"), row.get("fuel", "?"),
                    allocated_branch_fuel_pj, final_branch_fuel_pj,
                )

            if not within:
                log.warning(
                    "Reconciliation scalar out of bounds: %s / %s / %s / %s (ECF=%.3f, iterations=%d)",
                    row.get("economy", "?"), row.get("vehicle_type", "?"),
                    row.get("drive_type", "?"), row.get("fuel", "?"), ecf, iterations_used,
                )

        scalar_rows.append({
            "stock_scalar": ss,
            "mileage_scalar": ms,
            "efficiency_scalar": es,
            "stock_weight": weights.get("stock", _DEFAULT_WEIGHTS["stock"]),
            "mileage_weight": weights.get("mileage", _DEFAULT_WEIGHTS["mileage"]),
            "efficiency_weight": weights.get("efficiency", _DEFAULT_WEIGHTS["efficiency"]),
            "adjusted_stock": adj_s,
            "adjusted_mileage_km_per_year": adj_m,
            "adjusted_efficiency_km_per_gj": adj_e,
            "final_branch_fuel_pj": final_branch_fuel_pj,
            "scalars_within_bounds": within,
        })

    scalar_df = pd.DataFrame(scalar_rows)
    t9 = pd.concat([merged.reset_index(drop=True), scalar_df], axis=1)
    return t9


def apply_scalars(
    stock: float,
    mileage: float,
    efficiency: float,
    ecf: float,
    weights: dict[str, float],
    scalar_bounds: tuple[float, float] | dict[str, tuple[float, float]],
) -> tuple[float, float, float, float, float, float, bool]:
    """
    Apply scalars to a single branch.

    Returns: (stock_scalar, mileage_scalar, efficiency_scalar,
               adjusted_stock, adjusted_mileage, adjusted_efficiency, within_bounds)
    """
    w_s, w_m, w_e = weights["stock"], weights["mileage"], weights["efficiency"]
    bounds = _normalise_scalar_bounds(scalar_bounds)
    lo_s, hi_s = bounds["stock"]
    lo_m, hi_m = bounds["mileage"]
    lo_e, hi_e = bounds["efficiency"]

    # ecf=0 means no energy was allocated to this branch (e.g. Hydrogen/FCEV
    # branches in economies with no observed hydrogen use). Clamp to lower bound
    # rather than raising ZeroDivisionError from 0**(-w_e).
    if ecf <= 0:
        return lo_s, lo_m, hi_e, stock * lo_s, mileage * lo_m, efficiency * hi_e, False

    stock_scalar = float(np.clip(ecf ** w_s, lo_s, hi_s))
    mileage_scalar = float(np.clip(ecf ** w_m, lo_m, hi_m))
    efficiency_scalar = float(np.clip(ecf ** (-w_e), lo_e, hi_e))

    raw_stock_scalar = ecf ** w_s
    raw_mileage_scalar = ecf ** w_m
    raw_efficiency_scalar = ecf ** (-w_e)

    within_bounds = all(
        [
            lo_s <= raw_stock_scalar <= hi_s,
            lo_m <= raw_mileage_scalar <= hi_m,
            lo_e <= raw_efficiency_scalar <= hi_e,
        ]
    )

    return (
        stock_scalar, mileage_scalar, efficiency_scalar,
        stock * stock_scalar,
        mileage * mileage_scalar,
        efficiency * efficiency_scalar,
        within_bounds,
    )


def _normalise_scalar_bounds(
    scalar_bounds: tuple[float, float] | dict[str, tuple[float, float]] | None,
) -> dict[str, tuple[float, float]]:
    """
    Normalise scalar-bounds input into per-scalar bounds.

    Accepts:
      - tuple(min, max): applied to stock/mileage/efficiency (legacy mode)
      - dict with optional keys {'stock','mileage','efficiency'}
    """
    if scalar_bounds is None:
        return dict(_DEFAULT_SCALAR_BOUNDS)

    if isinstance(scalar_bounds, tuple):
        lo, hi = scalar_bounds
        return {
            "stock": (float(lo), float(hi)),
            "mileage": (float(lo), float(hi)),
            "efficiency": (float(lo), float(hi)),
        }

    out: dict[str, tuple[float, float]] = {}
    for key in ("stock", "mileage", "efficiency"):
        if key in scalar_bounds and scalar_bounds[key] is not None:
            lo, hi = scalar_bounds[key]
            out[key] = (float(lo), float(hi))
        else:
            out[key] = _DEFAULT_SCALAR_BOUNDS[key]
    return out


# ===========================================================================
# Step 8 — Device Shares
# ===========================================================================

def calculate_device_shares(reconciliation_scalars: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate Device Shares from reconciled stock, mileage, efficiency, and fuel energy.

    For single-fuel branches (BEV → Electricity, FCEV → Hydrogen): device_share = 1.0
    For multi-fuel branches (ICE, PHEV):
        implied_vehicles = final_branch_fuel_pj / (mileage / efficiency / 1_000_000)
        device_share = implied_vehicles / sum(implied_vehicles within drive-type branch)

    Device shares are normalised to sum to 1.0 within each drive-type branch.

    Returns T10_device_shares DataFrame.
    """
    df = reconciliation_scalars.copy()

    # Compute energy per vehicle per branch
    df["_energy_per_vehicle_pj"] = np.where(
        df["adjusted_efficiency_km_per_gj"] > 0,
        df["adjusted_mileage_km_per_year"] / df["adjusted_efficiency_km_per_gj"] / 1_000_000,
        np.nan,
    )

    # Implied vehicles from branch fuel energy
    df["implied_vehicles_using_fuel"] = np.where(
        df["drive_type"].isin(_SINGLE_FUEL_DRIVES),
        df["adjusted_stock"],
        np.where(
            df["_energy_per_vehicle_pj"] > 0,
            df["final_branch_fuel_pj"] / df["_energy_per_vehicle_pj"],
            0.0,
        ),
    )
    df["implied_vehicles_using_fuel"] = df["implied_vehicles_using_fuel"].clip(lower=0.0)

    # Group for normalisation
    group_keys = ["economy", "scenario", "transport_type", "vehicle_type", "drive_type"]
    if "size" in df.columns:
        group_keys.append("size")

    total_implied = df.groupby(group_keys)["implied_vehicles_using_fuel"].transform("sum")

    df["device_share"] = np.where(
        df["drive_type"].isin(_SINGLE_FUEL_DRIVES),
        1.0,
        (df["implied_vehicles_using_fuel"] / total_implied.replace(0.0, np.nan)).fillna(0.0),
    )

    df["adjusted_total_vehicles"] = df["adjusted_stock"]

    t10_cols = [
        "economy", "scenario", "transport_type", "vehicle_type", "drive_type", "fuel",
        "implied_vehicles_using_fuel", "adjusted_total_vehicles", "device_share",
    ]
    for extra in ["size", "leap_branch_path"]:
        if extra in df.columns:
            idx = t10_cols.index("fuel") + 1
            t10_cols.insert(idx, extra)

    df = df.drop(columns=["_energy_per_vehicle_pj"], errors="ignore")
    return df[[c for c in t10_cols if c in df.columns]].reset_index(drop=True)


# ===========================================================================
# Validation and diagnostics
# ===========================================================================

def build_reconciliation_diagnostics(
    reconciliation_scalars: pd.DataFrame,
    esto_fuel_totals: pd.DataFrame,
    phev_liquid_table: pd.DataFrame,
    match_tolerance: float,
) -> pd.DataFrame:
    """Build T12_reconciliation_diagnostics table."""
    economy = reconciliation_scalars["economy"].iloc[0] if not reconciliation_scalars.empty else "unknown"
    scenario = reconciliation_scalars["scenario"].iloc[0] if not reconciliation_scalars.empty else "unknown"

    phev_by_fuel: dict[str, float] = (
        phev_liquid_table.groupby("fuel")["phev_liquid_pj"].sum().to_dict()
        if not phev_liquid_table.empty
        else {}
    )

    pre_by_fuel = reconciliation_scalars.groupby("fuel")["initial_branch_energy_pj"].sum().to_dict()
    post_by_fuel = reconciliation_scalars.groupby("fuel")["final_branch_fuel_pj"].sum().to_dict()

    rows = []
    for _, esto_row in esto_fuel_totals.iterrows():
        fuel = esto_row["fuel"]
        esto_total = float(esto_row["energy_pj"])
        phev_liquid = float(phev_by_fuel.get(fuel, 0.0))
        remaining = max(0.0, esto_total - phev_liquid)
        pre = float(pre_by_fuel.get(fuel, 0.0))
        post = float(post_by_fuel.get(fuel, 0.0))
        gap_pj = post - remaining
        gap_pct = abs(gap_pj) / esto_total * 100.0 if esto_total > 0 else 0.0

        if gap_pct < 2.0:
            status = "ok"
        elif gap_pct < 10.0:
            status = "large_adjustment"
        else:
            status = "failed"

        rows.append({
            "economy": economy,
            "scenario": scenario,
            "fuel": fuel,
            "esto_total_pj": esto_total,
            "phev_liquid_pj": phev_liquid,
            "remaining_esto_pj": remaining,
            "pre_reconciliation_model_pj": pre,
            "post_reconciliation_model_pj": post,
            "gap_pj": gap_pj,
            "gap_pct": gap_pct,
            "reconciliation_status": status,
        })

    return pd.DataFrame(rows)


# ===========================================================================
# LEAP-ready output
# ===========================================================================

def build_leap_ready_table(
    reconciliation_scalars: pd.DataFrame,
    device_shares: pd.DataFrame,
    sales_turnover: pd.DataFrame,
    sales_shares: pd.DataFrame,
    projection_years: list[int],
) -> pd.DataFrame:
    """
    Combine all Module 6 outputs into the T11_leap_ready tidy table.

    Variables included:
      Base year (from T9/T10):  Stock, Mileage, Fuel Economy, Device Share, Activity Level
      All years (from T6/T7):   Sales, Sales Share

    Fuel Economy is converted from km/GJ → MJ/100km (= 10_000 / km_per_gj).
    Activity Level = adjusted_stock × adjusted_mileage_km_per_year.
    """
    if "leap_branch_path" not in reconciliation_scalars.columns:
        raise ValueError("reconciliation_scalars must contain leap_branch_path")

    t9 = reconciliation_scalars.copy()
    t9["_tech_path"] = t9["leap_branch_path"].apply(_tech_path)

    base_year: int = int(t9["base_year"].iloc[0]) if "base_year" in t9.columns else min(projection_years)
    economy_col = t9["economy"].iloc[0]
    scenario_col = t9["scenario"].iloc[0]

    rows: list[dict] = []

    # ── Deduplicate to one row per technology branch ──────────────────────
    # All fuel rows of the same drive type share the same stock/mileage.
    # Priority for deduplication: prefer the primary fuel row for each drive type.
    _primary_fuel_map = {"BEV": "Electricity", "FCEV": "Hydrogen", "PHEV": "Electricity"}
    tech_dedup_keys = ["economy", "scenario", "transport_type", "vehicle_type", "drive_type"]
    if "size" in t9.columns:
        tech_dedup_keys.append("size")

    # Sort so primary-fuel rows sort first, then drop_duplicates to keep first per tech branch
    def _primary_sort_key(row: pd.Series) -> int:
        pf = _primary_fuel_map.get(row["drive_type"])
        return 0 if row["fuel"] == pf else 1

    t9["_sort"] = t9.apply(_primary_sort_key, axis=1)
    tech_rows = (
        t9.sort_values("_sort")
        .drop_duplicates(subset=tech_dedup_keys)
        .drop(columns=["_sort"])
        .reset_index(drop=True)
    )
    t9 = t9.drop(columns=["_sort"])

    # ── Stock (base year, technology-level path) ──────────────────────────
    for _, row in tech_rows.iterrows():
        rows.append({
            "economy": row["economy"], "scenario": row["scenario"],
            "year": base_year, "leap_branch_path": row["_tech_path"],
            "variable": "Stock", "value": row["adjusted_stock"], "unit": "Device",
        })

    # ── Mileage (base year, technology-level path) ────────────────────────
    for _, row in tech_rows.iterrows():
        rows.append({
            "economy": row["economy"], "scenario": row["scenario"],
            "year": base_year, "leap_branch_path": row["_tech_path"],
            "variable": "Mileage", "value": row["adjusted_mileage_km_per_year"], "unit": "Kilometer",
        })

    # ── Activity Level (base year, technology-level path) ─────────────────
    for _, row in tech_rows.iterrows():
        activity = row["adjusted_stock"] * row["adjusted_mileage_km_per_year"]
        rows.append({
            "economy": row["economy"], "scenario": row["scenario"],
            "year": base_year, "leap_branch_path": row["_tech_path"],
            "variable": "Activity Level", "value": activity, "unit": "Kilometer",
        })

    # ── Fuel Economy (base year, fuel-level path) ─────────────────────────
    for _, row in t9.iterrows():
        eff = row["adjusted_efficiency_km_per_gj"]
        fe = 10_000.0 / eff if eff > 0 else np.nan
        rows.append({
            "economy": row["economy"], "scenario": row["scenario"],
            "year": base_year, "leap_branch_path": row["leap_branch_path"],
            "variable": "Fuel Economy", "value": fe, "unit": "MJ/100 km",
        })

    # ── Device Share (base year, fuel-level path) ─────────────────────────
    if "leap_branch_path" in device_shares.columns:
        for _, row in device_shares.iterrows():
            rows.append({
                "economy": row["economy"], "scenario": row["scenario"],
                "year": base_year, "leap_branch_path": row["leap_branch_path"],
                "variable": "Device Share", "value": row["device_share"], "unit": "Share",
            })

    # ── Build (vehicle_type, drive_type) → tech_path lookup from T9 ───────
    vt_dt_path = (
        t9.groupby(tech_dedup_keys)["_tech_path"]
        .first()
        .reset_index()
        .rename(columns={"_tech_path": "_tech_path_lookup"})
    )
    # Lookup keys: use whatever dimension columns are available in both sides
    lookup_keys = [k for k in tech_dedup_keys if k in vt_dt_path.columns]

    # ── Sales (all projection years, technology-level path) ───────────────
    if not sales_turnover.empty and "new_sales" in sales_turnover.columns:
        t6_keys = [k for k in lookup_keys if k in sales_turnover.columns]
        t6_path = sales_turnover.merge(vt_dt_path, on=t6_keys, how="left")
        for _, row in t6_path.iterrows():
            if pd.isna(row.get("_tech_path_lookup")) or int(row["year"]) not in projection_years:
                continue
            rows.append({
                "economy": row["economy"], "scenario": row["scenario"],
                "year": int(row["year"]), "leap_branch_path": row["_tech_path_lookup"],
                "variable": "Sales", "value": row["new_sales"], "unit": "Device",
            })

    # ── Sales Share (all projection years, technology-level path) ─────────
    if not sales_shares.empty and "sales_share" in sales_shares.columns:
        ss_keys = [k for k in lookup_keys if k in sales_shares.columns]
        ss_path = sales_shares.merge(vt_dt_path, on=ss_keys, how="left")
        if "year" in ss_path.columns:
            # Multi-year sales shares (Module 5 produces future-year shares)
            for _, row in ss_path.iterrows():
                if pd.isna(row.get("_tech_path_lookup")) or int(row["year"]) not in projection_years:
                    continue
                rows.append({
                    "economy": row["economy"], "scenario": row["scenario"],
                    "year": int(row["year"]), "leap_branch_path": row["_tech_path_lookup"],
                    "variable": "Sales Share", "value": row["sales_share"], "unit": "Share",
                })
        else:
            # Base-year only — replicate across all projection years
            for yr in projection_years:
                for _, row in ss_path.iterrows():
                    if pd.isna(row.get("_tech_path_lookup")):
                        continue
                    rows.append({
                        "economy": row["economy"], "scenario": row["scenario"],
                        "year": yr, "leap_branch_path": row["_tech_path_lookup"],
                        "variable": "Sales Share", "value": row["sales_share"], "unit": "Share",
                    })

    t11 = pd.DataFrame(rows)
    # Drop rows with NaN values (e.g., Fuel Economy when efficiency is 0)
    t11 = t11.dropna(subset=["value"]).reset_index(drop=True)
    return t11


# ===========================================================================
# Helpers
# ===========================================================================

def _get_esto_fuel(esto_fuel_totals: pd.DataFrame, fuel: str) -> float:
    """Extract ESTO total for a single fuel (PJ)."""
    mask = esto_fuel_totals["fuel"] == fuel
    if not mask.any():
        return 0.0
    return float(esto_fuel_totals[mask]["energy_pj"].sum())
