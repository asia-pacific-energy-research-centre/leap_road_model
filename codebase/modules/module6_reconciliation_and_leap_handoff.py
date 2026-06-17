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

--- Step 4 fuel allocation design ---

Fuel eligibility (coarse gate):
    drive_fuel_eligibility in fuel_mappings.yaml controls which fuels each drive
    type (ICE, HEV, BEV, PHEV, EREV, FCEV) can receive. HEV is NOT eligible for
    LPG, LNG, or Natural gas — those are ICE-only fuels.

Priority fuels (_FUEL_ALLOCATION_PRIORITY):
    Fuels listed here are allocated in _PRIORITY_FUEL_ALLOCATION_ORDER before
    any stock-share fuels. Each fuel has one or more tiers: a list of
    [transport_type, vehicle_type, drive_type] filters applied in order. None
    matches all values for that dimension.

    Tier logic:
      - Each tier receives fuel up to its initial_energy_pj capacity.
      - Any fuel not absorbed by a tier spills to the next tier.
      - After the last tier, any remainder stays within the last tier (fallback).
      - Within a tier, fuel is distributed proportionally by initial_energy_pj
        (branch energy = stock × mileage / efficiency). This gives high-intensity
        vehicles like Trucks their correct share without being overwhelmed by raw
        vehicle counts.

    Why initial_energy_pj weights (not stock):
      Trucks have small vehicle counts but high energy demand per vehicle. Stock-
      based shares would give Trucks far less fuel than they need; energy-based
      shares give each branch its proportional claim on the fuel pool.

    Why diesel uses a single freight tier (not Trucks→LCVs):
      A strict Trucks-first→LCVs-second tier fails when Trucks' initial_energy_pj
      exceeds the diesel ESTO total — Trucks absorb everything and LCVs receive
      zero. A single [freight, None, ICE] tier distributes diesel across Trucks
      and LCVs proportionally (Trucks still get more because they are more energy-
      intensive), with passenger as overflow for economies where freight ICE
      initial energy is less than the diesel ESTO total.

    Current tier assignments:
      LNG          → [freight, Trucks, ICE]            (Trucks ICE only)
      LPG          → [None, None, ICE]                 (all ICE, energy-share)
      Natural gas  → [None, None, ICE]                 (all ICE, energy-share)
      Diesel       → [freight, None, ICE] → [passenger](freight ICE first, passenger overflow)
      Biodiesel    → [freight, None, ICE] → [passenger](same as diesel)
      Gasoline     → [passenger] → [freight, LCVs]     (passenger first, LCV overflow)
      Biogasoline  → [passenger] → [freight, LCVs]     (same as gasoline)

    Trucks do not receive gasoline: neither gasoline tier includes Trucks, and
    the fallback (last_tier_mask) points to LCVs, so Trucks rows in the gasoline
    group are permanently zeroed out.

Non-priority fuels (Biogas, Efuel, Electricity, Hydrogen):
    Allocated by straight energy-share across all eligible branches. No tier
    ordering — branch receives fuel proportional to its initial_energy_pj.
"""

from __future__ import annotations

import logging
import pathlib
from typing import Any

import numpy as np
import pandas as pd
import yaml

from diagnostics.module_charts import write_module6_charts
from modules.reconciliation_aggregation import build_reconciled_technology_assumptions
from schemas.validation import validate_table

log = logging.getLogger(__name__)

_CONFIG_DIR = pathlib.Path(__file__).parent.parent / "config"


# Single-fuel drive types: device_share is always 1.0
_SINGLE_FUEL_DRIVES = {"BEV", "FCEV"}

# Plug-in hybrid drive types share the PHEV electric-utilisation workflow.
_PLUGIN_HYBRID_DRIVES = {"PHEV", "EREV"}
PHEVUtilisationRate = float | dict[str, float]

# Plug-in hybrid liquid fuels used for the transport-sector liquid blend.
# PHEVs and EREVs use the gasoline family: motor gasoline, biogasoline, and efuel.
_PLUGIN_LIQUID_FUELS_BY_DRIVE = {
    "PHEV": {"Motor gasoline", "Biogasoline", "Efuel"},
    "EREV": {"Motor gasoline", "Biogasoline", "Efuel"},
}
_DEFAULT_PLUGIN_LIQUID_FUELS = {"Motor gasoline", "Biogasoline", "Efuel"}


def _resolve_phev_utilisation_rate(
    phev_utilisation_rate: PHEVUtilisationRate,
    row_or_group: pd.Series | pd.DataFrame,
) -> float:
    """Return the electric driving share for a PHEV row/group."""
    if isinstance(phev_utilisation_rate, dict):
        transport_type = None
        if "transport_type" in row_or_group:
            value = row_or_group["transport_type"]
            if isinstance(value, pd.Series):
                non_null = value.dropna()
                transport_type = str(non_null.iloc[0]) if not non_null.empty else None
            elif pd.notna(value):
                transport_type = str(value)
        for key in (transport_type, "default", "economy"):
            if key in phev_utilisation_rate:
                return min(1.0, max(0.0, float(phev_utilisation_rate[key])))
        if phev_utilisation_rate:
            return min(1.0, max(0.0, float(next(iter(phev_utilisation_rate.values())))))
        return 0.50
    return min(1.0, max(0.0, float(phev_utilisation_rate)))

_FUEL_ALLOCATION_PRIORITY = {
    # Gaseous fuels: LNG to Trucks ICE only; LPG and Natural gas to all ICE (not HEV).
    "LNG":                [["freight", "Trucks", "ICE"]],
    "LPG":                [[None, None, "ICE"]],
    "Natural gas":        [[None, None, "ICE"]],
    # Diesel family: freight ICE first (Trucks + LCVs share proportionally by
    # initial_energy_pj — see module docstring), with passenger as overflow for
    # economies where freight ICE initial energy is less than the diesel ESTO total.
    "Gas and diesel oil": [["freight", None, "ICE"], ["passenger", None]],
    "Biodiesel":          [["freight", None, "ICE"], ["passenger", None]],
    # Gasoline family: passenger first, LCVs receive any surplus.
    "Motor gasoline":     [["passenger", None], ["freight", "LCVs"]],
    "Biogasoline":        [["passenger", None], ["freight", "LCVs"]],
}

_PRIORITY_FUEL_ALLOCATION_ORDER = {
    "LNG": 0,
    "LPG": 1,
    "Natural gas": 2,
    "Gas and diesel oil": 3,
    "Biodiesel": 4,
    "Motor gasoline": 5,
    "Biogasoline": 6,
}

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


def _vehicle_path(branch_path: str) -> str:
    """Return Demand\\{road}\\{vehicle type} from a road LEAP branch path."""
    return "\\".join(str(branch_path).split("\\")[:3])


def _transport_path(branch_path: str) -> str:
    """Return Demand\\{road} from a road LEAP branch path."""
    return "\\".join(str(branch_path).split("\\")[:2])


def _priority_tier_mask(df: pd.DataFrame, tier: list[str | None]) -> pd.Series:
    """Return rows matching a [transport_type, vehicle_type, drive_type] allocation tier.

    Any element that is None matches all values for that dimension.
    """
    transport_type = tier[0] if len(tier) > 0 else None
    vehicle_type   = tier[1] if len(tier) > 1 else None
    drive_type     = tier[2] if len(tier) > 2 else None
    mask = pd.Series(True, index=df.index)
    if transport_type is not None:
        mask &= df["transport_type"] == transport_type
    if vehicle_type is not None:
        mask &= df["vehicle_type"] == vehicle_type
    if drive_type is not None:
        mask &= df["drive_type"] == drive_type
    return mask


def _priority_tier_key(tier: list[str | None]) -> tuple[str | None, str | None, str | None]:
    """Return a hashable priority-tier key."""
    return (
        tier[0] if len(tier) > 0 else None,
        tier[1] if len(tier) > 1 else None,
        tier[2] if len(tier) > 2 else None,
    )


def _build_priority_tier_capacity(priority_rows: pd.DataFrame) -> dict[tuple[str | None, str | None, str | None], float]:
    """
    Return liquid-energy capacity for each priority tier.

    Capacity is based on all priority liquid-fuel rows in the tier, not only the
    single fuel currently being allocated. This prevents diesel from spilling to
    passenger vehicles while LCVs still have gasoline liquid demand that diesel
    should displace first.
    """
    capacities: dict[tuple[str, str | None], float] = {}
    all_tiers = [
        tier
        for tiers in _FUEL_ALLOCATION_PRIORITY.values()
        for tier in tiers
    ]
    for tier in all_tiers:
        key = _priority_tier_key(tier)
        if key in capacities:
            continue
        mask = _priority_tier_mask(priority_rows, tier)
        capacities[key] = max(0.0, float(priority_rows.loc[mask, "initial_energy_pj"].sum()))
    return capacities


def _allocate_priority_fuel_group(
    group: pd.DataFrame,
    remaining_tier_capacity: dict[tuple[str, str | None], float] | None = None,
) -> pd.DataFrame:
    """
    Allocate one fuel group through its priority tiers, then distribute any remainder
    within the last tier — all proportional to initial_energy_pj.

    initial_energy_pj = stock × mileage / efficiency for each branch. Using this as
    the share weight (not raw vehicle count) ensures high-intensity vehicles like
    Trucks receive their proportional share of liquid fuels even when their stock
    count is small relative to passenger vehicles.

    Tiers come from _FUEL_ALLOCATION_PRIORITY. Each tier is a
    [transport_type, vehicle_type, drive_type] filter; None matches all. Fuel fills
    each tier up to that tier's total initial_energy_pj capacity, then spills to the
    next tier. After all tiers, any remaining fuel is re-distributed within the last
    tier (not spilled further).

    For fuels not in _FUEL_ALLOCATION_PRIORITY (tiers=None), all fuel is distributed
    across all eligible rows in one pass using the fallback path.
    """
    out = group.copy()
    if "fuel" in out.columns:
        fuel = str(out["fuel"].iloc[0])
    else:
        group_name = group.name if isinstance(group.name, tuple) else ("", "", group.name)
        fuel = str(group_name[-1])
        out["fuel"] = fuel
    tiers = _FUEL_ALLOCATION_PRIORITY.get(fuel)
    remaining = max(0.0, float(out["remaining_esto_fuel_pj"].iloc[0]))
    allocated = pd.Series(0.0, index=out.index)
    last_tier_mask: pd.Series | None = None

    def _energy_shares(mask: pd.Series) -> pd.Series:
        total = float(out.loc[mask, "initial_energy_pj"].sum())
        if total > 0:
            return out.loc[mask, "initial_energy_pj"] / total
        return pd.Series(0.0, index=out.loc[mask].index)

    if tiers:
        for tier in tiers:
            tier_mask = _priority_tier_mask(out, tier)
            if not tier_mask.any():
                continue
            last_tier_mask = tier_mask
            tier_key = _priority_tier_key(tier)
            if remaining <= 0:
                continue

            if remaining_tier_capacity is None:
                tier_capacity = max(0.0, float(out.loc[tier_mask, "initial_energy_pj"].sum()))
            else:
                tier_capacity = max(0.0, float(remaining_tier_capacity.get(tier_key, 0.0)))
            tier_allocation = min(remaining, tier_capacity)
            if tier_allocation <= 0:
                continue

            allocated.loc[tier_mask] = allocated.loc[tier_mask] + (_energy_shares(tier_mask) * tier_allocation)
            remaining -= tier_allocation
            if remaining_tier_capacity is not None:
                remaining_tier_capacity[tier_key] = max(0.0, tier_capacity - tier_allocation)

    if remaining > 0:
        fallback_mask = last_tier_mask if last_tier_mask is not None else pd.Series(True, index=out.index)
        allocated.loc[fallback_mask] = allocated.loc[fallback_mask] + (_energy_shares(fallback_mask) * remaining)

    total_allocated = float(allocated.sum())
    out["allocated_branch_fuel_pj"] = allocated
    out["branch_allocation_share"] = (
        allocated / total_allocated if total_allocated > 0 else 0.0
    )
    out["allocation_rule"] = "priority_spillover_stock_share" if tiers else "stock_share"
    return out


# ===========================================================================
# Public entry point
# ===========================================================================

def run_module6(
    base_year_branches: pd.DataFrame,
    sales_turnover: pd.DataFrame,
    sales_shares: pd.DataFrame,
    esto_fuel_totals: pd.DataFrame,
    projection_years: list[int],
    mileage_correction_factors: pd.DataFrame | None = None,
    fuel_economy_correction_factors: pd.DataFrame | None = None,
    reconciliation_weights: dict[str, float] | None = None,
    phev_electric_utilisation_rate: PHEVUtilisationRate = 0.50,
    scalar_bounds: tuple[float, float] | dict[str, tuple[float, float]] | None = None,
    match_tolerance: float = 0.01,
    phev_utilisation_tolerance: float = 0.10,
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
        reconciliation_weights: Required weights for {stock, mileage, efficiency} — must sum to 1.0.
        phev_electric_utilisation_rate: PHEV fraction driven on electricity.
            Supports either a single float or a dict keyed by transport_type.
                scalar_bounds: Reconciliation scalar bounds. Supports either:
                        - tuple(min_scalar, max_scalar) applied to all scalars (legacy), or
                        - dict with keys {'stock','mileage','efficiency'} each mapping to
                            (min_scalar, max_scalar).
        match_tolerance: Acceptable fractional gap between model and ESTO.
        phev_utilisation_tolerance: Absolute tolerance band around the supplied
            PHEV electric utilisation rate for the back-calculated diagnostic.
                diagnostics_dir: Optional directory root for Module 6 PNG diagnostic
                    charts. When provided, charts are written to
                    diagnostics_dir/module6/.

    Returns:
        Dict with keys: T8, T9, T10, T11, T12 — each a DataFrame.
    """
    if reconciliation_weights is None:
        raise ValueError(
            "reconciliation_weights is required. Supply {stock, mileage, efficiency} weights "
            "summing to 1.0 — they should come from Module 1 defaults."
        )
    if scalar_bounds is None:
        raise ValueError(
            "scalar_bounds is required. Supply per-scalar bounds from Module 1 defaults."
        )
    weights = reconciliation_weights
    assert abs(sum(weights.values()) - 1.0) < 1e-6, "Reconciliation weights must sum to 1.0"

    # Step 1
    branch_energy = calculate_initial_branch_energy(
        base_year_branches,
        phev_electric_utilisation_rate,
    )
    branch_energy = bootstrap_zero_stock_fuel_branches(branch_energy, esto_fuel_totals)

    # Step 2: BEV/PHEV electricity reconciliation
    electricity_esto = _get_esto_fuel(esto_fuel_totals, "Electricity")
    branch_energy, phev_liquid = reconcile_electricity(
        branch_energy, electricity_esto, phev_electric_utilisation_rate, weights, scalar_bounds
    )
    phev_liquid = distribute_phev_liquid_by_esto_mix(phev_liquid, esto_fuel_totals)

    # Step 3: Remaining ESTO after PHEV liquid subtraction
    remaining_esto = calculate_remaining_esto(esto_fuel_totals, phev_liquid)

    # Step 4: Fuel allocation
    t8 = allocate_esto_fuel_to_branches(branch_energy, remaining_esto, base_year_branches, phev_liquid)

    # Steps 5–7: Simultaneous reconciliation
    t9 = reconcile_stock_mileage_efficiency(t8, branch_energy, weights, scalar_bounds)

    # Step 8: Device Shares
    t10 = calculate_device_shares(t9)

    # Step 9: Validate
    t12 = build_reconciliation_diagnostics(t9, esto_fuel_totals, phev_liquid, match_tolerance)
    t12_phev = build_phev_utilisation_diagnostics(
        t9,
        phev_electric_utilisation_rate,
        phev_utilisation_tolerance,
    )

    # Build LEAP-ready output
    t11 = build_leap_ready_table(
        t9,
        t10,
        sales_turnover,
        sales_shares,
        projection_years,
        mileage_correction_factors=mileage_correction_factors,
        fuel_economy_correction_factors=fuel_economy_correction_factors,
    )

    errors = validate_table(t11, "T11_leap_ready")
    for err in errors:
        log.warning("Validation: %s", err)
    outputs = {"T8": t8, "T9": t9, "T10": t10, "T11": t11, "T12": t12, "T12_phev": t12_phev}

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

def calculate_initial_branch_energy(
    base_year_branches: pd.DataFrame,
    phev_utilisation_rate: PHEVUtilisationRate | None = None,
) -> pd.DataFrame:
    """
    Calculate initial branch energy from base-year stock, mileage, and efficiency.

    initial_energy_pj = stock × mileage / efficiency_km_per_gj / 1_000_000

    Args:
        base_year_branches: T4_base_year_branches DataFrame.

    Returns:
        DataFrame with all T4 columns plus 'initial_energy_pj'.
    """
    df = base_year_branches.copy()
    if phev_utilisation_rate is not None:
        df = apply_phev_mileage_split(df, phev_utilisation_rate)
    df["initial_energy_pj"] = (
        df["stock"] * df["mileage_km_per_year"] / df["efficiency_km_per_gj"] / 1_000_000
    )
    return df


def bootstrap_zero_stock_fuel_branches(
    branch_energy: pd.DataFrame,
    esto_fuel_totals: pd.DataFrame,
    seed_stock: float = 1.0,
) -> pd.DataFrame:
    """
    Seed eligible zero-stock branches when a fuel has a positive ESTO target.

    Reconciliation can scale positive stock, mileage, and efficiency, but a
    branch with zero stock has zero initial energy and receives no allocation.
    This bootstrap gives Module 6 a small positive starting point only for fuels
    where every eligible branch has zero initial energy.
    """
    if branch_energy.empty or esto_fuel_totals.empty:
        return branch_energy

    required = {"drive_type", "fuel", "stock", "mileage_km_per_year", "efficiency_km_per_gj", "initial_energy_pj"}
    if not required.issubset(branch_energy.columns) or {"fuel", "energy_pj"}.difference(esto_fuel_totals.columns):
        return branch_energy

    out = branch_energy.copy()
    eligibility = _get_fuel_eligibility()
    out["_module6_fuel_eligible"] = out.apply(
        lambda row: row["fuel"] in eligibility.get(row["drive_type"], []),
        axis=1,
    )
    if "stock_bootstrapped_for_reconciliation" not in out.columns:
        out["stock_bootstrapped_for_reconciliation"] = False

    positive_esto = esto_fuel_totals.copy()
    positive_esto["energy_pj"] = pd.to_numeric(positive_esto["energy_pj"], errors="coerce").fillna(0.0)
    positive_fuels = positive_esto.loc[positive_esto["energy_pj"] > 0, "fuel"].dropna().astype(str).unique()

    for fuel in positive_fuels:
        fuel_mask = out["_module6_fuel_eligible"] & out["fuel"].astype(str).eq(fuel)
        if not fuel_mask.any():
            continue
        initial_total = pd.to_numeric(out.loc[fuel_mask, "initial_energy_pj"], errors="coerce").fillna(0.0).sum()
        if initial_total > 0:
            continue

        seed_mask = (
            fuel_mask
            & pd.to_numeric(out["stock"], errors="coerce").fillna(0.0).le(0)
            & pd.to_numeric(out["mileage_km_per_year"], errors="coerce").fillna(0.0).gt(0)
            & pd.to_numeric(out["efficiency_km_per_gj"], errors="coerce").fillna(0.0).gt(0)
        )
        if not seed_mask.any():
            continue

        out.loc[seed_mask, "stock"] = float(seed_stock)
        out.loc[seed_mask, "stock_bootstrapped_for_reconciliation"] = True
        out.loc[seed_mask, "initial_energy_pj"] = (
            out.loc[seed_mask, "stock"]
            * out.loc[seed_mask, "mileage_km_per_year"]
            / out.loc[seed_mask, "efficiency_km_per_gj"]
            / 1_000_000
        )
        log.info(
            "Module 6 bootstrapped %d zero-stock branch(es) for positive %s ESTO target.",
            int(seed_mask.sum()),
            fuel,
        )

    return out.drop(columns=["_module6_fuel_eligible"])


def apply_phev_mileage_split(
    base_year_branches: pd.DataFrame,
    phev_utilisation_rate: PHEVUtilisationRate,
) -> pd.DataFrame:
    """
    Split PHEV annual mileage into electric-mode and liquid-mode mileage.

    Module 1 supplies the PHEV electric utilisation rate as a km share. The
    branch skeleton has separate PHEV Electricity and liquid-fuel rows, so each
    row should carry only its relevant mode mileage before energy is calculated.
    """
    df = base_year_branches.copy()
    if df.empty or "mileage_km_per_year" not in df.columns:
        return df

    group_keys = ["economy", "scenario", "transport_type", "vehicle_type", "drive_type"]
    if "size" in df.columns:
        group_keys.append("size")

    phev_mask = df["drive_type"].isin(_PLUGIN_HYBRID_DRIVES)
    for key, group in df[phev_mask].groupby(group_keys, dropna=False):
        idx = group.index
        electric_idx = group[group["fuel"] == "Electricity"].index
        liquid_idx = group[group["fuel"] != "Electricity"].index
        if electric_idx.empty or liquid_idx.empty:
            continue

        rate = _resolve_phev_utilisation_rate(phev_utilisation_rate, group)

        electric_mileage = pd.to_numeric(df.loc[electric_idx, "mileage_km_per_year"], errors="coerce").dropna()
        liquid_mileage = pd.to_numeric(df.loc[liquid_idx, "mileage_km_per_year"], errors="coerce").dropna()
        if electric_mileage.empty or liquid_mileage.empty:
            continue

        electric_median = float(electric_mileage.median())
        liquid_median = float(liquid_mileage.median())
        if electric_median <= 0 and liquid_median <= 0:
            continue

        current_share = (
            electric_median / (electric_median + liquid_median)
            if (electric_median + liquid_median) > 0
            else np.nan
        )
        if np.isfinite(current_share) and abs(current_share - rate) <= 0.02:
            continue

        if max(electric_median, liquid_median) > 0 and (
            abs(electric_median - liquid_median) / max(electric_median, liquid_median) <= 0.10
        ):
            total_mileage = max(electric_median, liquid_median)
        else:
            total_mileage = electric_median + liquid_median

        df.loc[electric_idx, "mileage_km_per_year"] = total_mileage * rate
        df.loc[liquid_idx, "mileage_km_per_year"] = total_mileage * (1.0 - rate)
        if "mileage_granularity" in df.columns:
            df.loc[idx, "mileage_granularity"] = "phev_utilisation_split"

    return df


# ===========================================================================
# Step 2 — BEV/PHEV electricity reconciliation
# ===========================================================================

def reconcile_electricity(
    branch_energy: pd.DataFrame,
    electricity_esto_pj: float,
    phev_utilisation_rate: PHEVUtilisationRate,
    weights: dict[str, float],
    scalar_bounds: tuple[float, float] | dict[str, tuple[float, float]],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Reconcile BEV and PHEV electricity use to ESTO road electricity, per scenario.

    Base-year data carries a row per scenario (the base year itself is
    scenario-agnostic, just replicated for each requested scenario). The ESTO
    electricity target is a single, non-scenario value, so the ECF must be
    computed from one scenario's initial electricity energy at a time —
    summing initial energy across scenarios before dividing into the target
    would shrink the ECF by the scenario count and under-reconcile every
    scenario.
    """
    if branch_energy.empty or "scenario" not in branch_energy.columns:
        return _reconcile_electricity_one_scenario(
            branch_energy, electricity_esto_pj, phev_utilisation_rate, weights, scalar_bounds
        )

    energy_parts = []
    phev_liquid_parts = []
    for _, group in branch_energy.groupby("scenario", dropna=False, sort=False):
        energy_part, phev_liquid_part = _reconcile_electricity_one_scenario(
            group, electricity_esto_pj, phev_utilisation_rate, weights, scalar_bounds
        )
        energy_parts.append(energy_part)
        phev_liquid_parts.append(phev_liquid_part)

    energy = pd.concat(energy_parts).sort_index() if energy_parts else branch_energy.copy()
    phev_liquid = (
        pd.concat(phev_liquid_parts, ignore_index=True) if phev_liquid_parts else pd.DataFrame()
    )
    return energy, phev_liquid


def _reconcile_electricity_one_scenario(
    branch_energy: pd.DataFrame,
    electricity_esto_pj: float,
    phev_utilisation_rate: PHEVUtilisationRate,
    weights: dict[str, float],
    scalar_bounds: tuple[float, float] | dict[str, tuple[float, float]],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Reconcile BEV and PHEV electricity use to ESTO road electricity for a single scenario's rows.

    Uses the same iterative bounded stock/mileage/efficiency adjustment as Steps 5–6.
    After reconciliation, derives PHEV liquid fuel consumption from adjusted stock.

    Returns:
        (updated_branch_energy, phev_liquid_table)
        phev_liquid_table has columns [vehicle_type, drive_type, fuel, phev_liquid_pj]
    """
    df = branch_energy.copy()
    elec_mask = df["fuel"] == "Electricity"
    phev_elec_mask = elec_mask & df["drive_type"].isin(_PLUGIN_HYBRID_DRIVES)
    non_phev_elec_mask = elec_mask & (~df["drive_type"].isin(_PLUGIN_HYBRID_DRIVES))

    # Build phev_liquid_table from unadjusted data if reconciliation cannot run
    def _build_phev_liquid(source_df: pd.DataFrame) -> pd.DataFrame:
        return _compute_phev_liquid(source_df, phev_utilisation_rate)

    if electricity_esto_pj <= 0 or not elec_mask.any():
        return df, _build_phev_liquid(df)

    phev_electric_pj = float(df.loc[phev_elec_mask, "initial_energy_pj"].sum())
    total_initial_elec = df.loc[non_phev_elec_mask, "initial_energy_pj"].sum()
    bootstrapped_electric = (
        "stock_bootstrapped_for_reconciliation" in df.columns
        and df.loc[elec_mask, "stock_bootstrapped_for_reconciliation"].fillna(False).astype(bool).any()
    )

    if bootstrapped_electric:
        total_all_elec = phev_electric_pj + total_initial_elec
        if total_all_elec <= 0:
            return df, _build_phev_liquid(df)
        ecf = electricity_esto_pj / total_all_elec
        adjust_mask = elec_mask
    elif phev_electric_pj > electricity_esto_pj:
        # PHEV stock alone implies more electricity than ESTO records — scale all
        # electricity branches (PHEV + BEV) together so the fleet size lands at a
        # value consistent with ESTO, rather than clamping BEVs to zero.
        log.info(
            "PHEV electricity implied by utilisation (%.3f PJ) exceeds ESTO road electricity (%.3f PJ); applying electricity reconciliation.",
            phev_electric_pj,
            electricity_esto_pj,
        )
        total_all_elec = phev_electric_pj + total_initial_elec
        if total_all_elec <= 0:
            return df, _build_phev_liquid(df)
        ecf = electricity_esto_pj / total_all_elec
        adjust_mask = elec_mask
    else:
        residual_electricity_pj = electricity_esto_pj - phev_electric_pj
        if total_initial_elec <= 0:
            return df, _build_phev_liquid(df)
        ecf = residual_electricity_pj / total_initial_elec
        # PHEV electricity is within ESTO budget; only adjust non-PHEV branches.
        adjust_mask = non_phev_elec_mask

    out_of_bounds_adjustments: list[dict[str, float]] = []
    for idx in df[adjust_mask].index:
        s = df.at[idx, "stock"]
        m = df.at[idx, "mileage_km_per_year"]
        e = df.at[idx, "efficiency_km_per_gj"]
        target_energy_pj = float(df.at[idx, "initial_energy_pj"]) * ecf
        adj_s, adj_m, adj_e, final_energy_pj, within = _adjust_branch_to_energy_target(
            stock=s,
            mileage=m,
            efficiency=e,
            target_energy_pj=target_energy_pj,
            weights=weights,
            scalar_bounds=scalar_bounds,
        )
        df.at[idx, "stock"] = adj_s
        df.at[idx, "mileage_km_per_year"] = adj_m
        df.at[idx, "efficiency_km_per_gj"] = adj_e
        df.at[idx, "initial_energy_pj"] = final_energy_pj
        if not within:
            out_of_bounds_adjustments.append(
                {
                    "stock_scalar": adj_s / s if s else 0.0,
                    "mileage_scalar": adj_m / m if m else 0.0,
                    "efficiency_scalar": adj_e / e if e else 0.0,
                }
            )

    if out_of_bounds_adjustments:
        summary = pd.DataFrame(out_of_bounds_adjustments)
        log.info(
            "Electricity reconciliation summary: %d branch(es) reached scalar bounds; "
            "ECF=%.3f, average scalars stock=%.3f mileage=%.3f efficiency=%.3f.",
            len(summary),
            ecf,
            float(summary["stock_scalar"].mean()),
            float(summary["mileage_scalar"].mean()),
            float(summary["efficiency_scalar"].mean()),
        )

    # Propagate adjusted stock to PHEV liquid branches (same fleet, shared stock).
    # Index must include size to avoid duplicate entries when vehicle types have
    # multiple size variants (e.g. LPVs medium + LPVs large).
    _idx_cols = ["economy", "scenario", "transport_type", "vehicle_type", "drive_type"]
    _has_size = "size" in df.columns and df["size"].notna().any()
    if _has_size:
        _idx_cols.append("size")
    phev_elec_stock = (
        df[df["drive_type"].isin(_PLUGIN_HYBRID_DRIVES) & elec_mask]
        .set_index(_idx_cols)["stock"]
        if all(c in df.columns for c in _idx_cols)
        else pd.Series(dtype=float)
    )
    if not phev_elec_stock.empty:
        phev_liq_mask = df["drive_type"].isin(_PLUGIN_HYBRID_DRIVES) & (~elec_mask)
        for idx in df[phev_liq_mask].index:
            key = tuple(df.at[idx, c] for c in _idx_cols)
            if key in phev_elec_stock.index:
                df.at[idx, "stock"] = phev_elec_stock[key]

    phev_liquid = _build_phev_liquid(df)
    return df, phev_liquid


def _compute_phev_liquid(
    branch_energy: pd.DataFrame,
    phev_utilisation_rate: PHEVUtilisationRate,
) -> pd.DataFrame:
    """
    Compute PHEV liquid fuel consumption from adjusted PHEV liquid branches.

    For each PHEV liquid branch: phev_liquid_pj = stock × mileage / efficiency / 1e6.
    The mileage in PHEV liquid rows already represents the liquid-mode km fraction
    (= total_mileage × (1 - utilisation_rate)).
    """
    phev_liq = branch_energy[
        branch_energy["drive_type"].isin(_PLUGIN_HYBRID_DRIVES)
        & (~branch_energy["fuel"].isin(["Electricity"]))
    ].copy()

    if phev_liq.empty:
        return pd.DataFrame(columns=["vehicle_type", "drive_type", "fuel", "phev_liquid_pj"])

    phev_liq["phev_liquid_pj"] = (
        phev_liq["stock"] * phev_liq["mileage_km_per_year"] / phev_liq["efficiency_km_per_gj"] / 1_000_000
    )

    keep = ["vehicle_type", "drive_type", "fuel", "phev_liquid_pj"]
    for extra in ["economy", "scenario", "transport_type", "size"]:
        if extra in phev_liq.columns:
            keep.insert(0, extra)

    return phev_liq[[c for c in keep if c in phev_liq.columns]].reset_index(drop=True)


def distribute_phev_liquid_by_esto_mix(
    phev_liquid_table: pd.DataFrame,
    esto_fuel_totals: pd.DataFrame,
) -> pd.DataFrame:
    """
    Distribute each PHEV fleet's liquid-mode demand across liquid fuels.

    The branch table has one row per eligible liquid fuel. Those rows are fuel
    alternatives, so summing their raw liquid-mode energy would count the same
    PHEV fleet multiple times. Use the transport-sector liquid-fuel mix as the
    best available split across eligible fuels, but only for the preferred
    plug-in liquid fuels. PHEV and EREV liquid demand is assigned only to the
    gasoline family: motor gasoline, biogasoline, and efuel. LPG, CNG, diesel,
    and biodiesel are intentionally ignored for plug-in hybrids.
    """
    if phev_liquid_table.empty:
        return phev_liquid_table.copy()

    df = phev_liquid_table.copy()
    if "size" not in df.columns:
        df["size"] = pd.NA

    esto = esto_fuel_totals.copy()
    esto["energy_pj"] = pd.to_numeric(esto["energy_pj"], errors="coerce").fillna(0.0)
    esto_mix = esto.set_index("fuel")["energy_pj"].to_dict()

    group_keys = ["economy", "scenario", "transport_type", "vehicle_type", "drive_type", "size"]
    group_keys = [c for c in group_keys if c in df.columns]
    rows: list[pd.DataFrame] = []
    for _key, group in df.groupby(group_keys, dropna=False):
        group = group.copy()
        group["phev_liquid_pj"] = pd.to_numeric(group["phev_liquid_pj"], errors="coerce").fillna(0.0)

        drive_type = str(group["drive_type"].iloc[0]) if "drive_type" in group.columns else "PHEV"
        liquid_fuels = _PLUGIN_LIQUID_FUELS_BY_DRIVE.get(drive_type, _DEFAULT_PLUGIN_LIQUID_FUELS)
        preferred_mask = group["fuel"].isin(liquid_fuels)
        if not preferred_mask.any():
            log.warning(
                "Module 6 PHEV liquid allocation skipped group with no preferred liquid fuels: %s",
                {k: group.iloc[0][k] for k in group_keys if k in group.columns},
            )
            group["phev_liquid_pj"] = 0.0
            rows.append(group)
            continue

        preferred = group.loc[preferred_mask].copy()
        weights = pd.Series(
            [max(0.0, float(esto_mix.get(fuel, 0.0))) for fuel in preferred["fuel"]],
            index=preferred.index,
        )
        if weights.sum() <= 0:
            weights = pd.Series(1.0, index=preferred.index)

        shares = weights / weights.sum()
        total_liquid = float((preferred["phev_liquid_pj"] * shares).sum())
        group["phev_liquid_pj"] = 0.0
        group.loc[preferred.index, "phev_liquid_pj"] = total_liquid * shares
        rows.append(group)

    if not rows:
        return df
    return pd.concat(rows, ignore_index=True)


# ===========================================================================
# Step 3 — Remaining ESTO fuel totals
# ===========================================================================

def calculate_remaining_esto(
    esto_fuel_totals: pd.DataFrame,
    phev_liquid_table: pd.DataFrame,
) -> pd.DataFrame:
    """
    Subtract PHEV/EREV gasoline-family liquid fuel before normal reconciliation.

    remaining_gasoline = ESTO_gasoline - PHEV_gasoline
    remaining_biogasoline = ESTO_biogasoline - PHEV_biogasoline
    remaining_efuel = ESTO_efuel - PHEV_efuel

    Base-year data carries a row per scenario (scenario is replicated, not
    distinct, in the base year) — summing phev_liquid_table across scenarios
    before subtracting from a single-scenario ESTO total would over-subtract
    by a factor of the scenario count. Group by scenario (when present) so the
    subtraction stays scoped to one scenario's PHEV demand at a time.

    Returns:
        DataFrame with columns:
        [scenario, fuel, esto_fuel_total_pj, phev_liquid_subtracted_pj, remaining_esto_fuel_pj]
        ("scenario" is only included if phev_liquid_table has a scenario column.)
    """
    has_scenario = "scenario" in phev_liquid_table.columns and not phev_liquid_table.empty

    if phev_liquid_table.empty:
        phev_by_key: dict[Any, float] = {}
    elif has_scenario:
        phev_by_key = phev_liquid_table.groupby(["scenario", "fuel"])["phev_liquid_pj"].sum().to_dict()
    else:
        phev_by_key = phev_liquid_table.groupby("fuel")["phev_liquid_pj"].sum().to_dict()

    scenarios = (
        phev_liquid_table["scenario"].dropna().unique().tolist()
        if has_scenario
        else [None]
    )

    rows = []
    for scenario in scenarios:
        for _, row in esto_fuel_totals.iterrows():
            fuel = row["fuel"]
            esto_total = float(row["energy_pj"])
            key = (scenario, fuel) if has_scenario else fuel
            phev_liquid = float(phev_by_key.get(key, 0.0))
            remaining = max(0.0, esto_total - phev_liquid)
            out_row = {
                "fuel": fuel,
                "esto_fuel_total_pj": esto_total,
                "phev_liquid_subtracted_pj": phev_liquid,
                "remaining_esto_fuel_pj": remaining,
            }
            if has_scenario:
                out_row = {"scenario": scenario, **out_row}
            rows.append(out_row)

    return pd.DataFrame(rows)


# ===========================================================================
# Step 4 — Fuel allocation
# ===========================================================================

def allocate_esto_fuel_to_branches(
    branch_energy: pd.DataFrame,
    remaining_esto: pd.DataFrame,
    base_year_branches: pd.DataFrame,
    phev_liquid_table: pd.DataFrame | None = None,
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

    # Join with remaining_esto on fuel (and scenario, when remaining_esto is scenario-scoped)
    merge_on = ["scenario", "fuel"] if "scenario" in remaining_esto.columns else ["fuel"]
    df = df.merge(remaining_esto, on=merge_on, how="left")
    df["esto_fuel_total_pj"] = df["esto_fuel_total_pj"].fillna(0.0)
    df["phev_liquid_subtracted_pj"] = df["phev_liquid_subtracted_pj"].fillna(0.0)
    df["remaining_esto_fuel_pj"] = df["remaining_esto_fuel_pj"].fillna(0.0)

    df["branch_allocation_share"] = 0.0
    df["allocated_branch_fuel_pj"] = 0.0
    df["allocation_rule"] = "stock_share"

    # Electricity has already been reconciled before this step. Preserve the
    # BEV/PHEV split implied by reconciled electric branch energy.
    electricity_mask = df["fuel"] == "Electricity"
    if electricity_mask.any():
        phev_electric_mask = electricity_mask & df["drive_type"].isin(_PLUGIN_HYBRID_DRIVES)
        non_phev_electric_mask = electricity_mask & (~df["drive_type"].isin(_PLUGIN_HYBRID_DRIVES))
        df.loc[phev_electric_mask, "branch_allocation_share"] = np.where(
            df.loc[phev_electric_mask, "remaining_esto_fuel_pj"] > 0,
            df.loc[phev_electric_mask, "initial_energy_pj"] / df.loc[phev_electric_mask, "remaining_esto_fuel_pj"],
            0.0,
        )
        df.loc[phev_electric_mask, "allocated_branch_fuel_pj"] = df.loc[phev_electric_mask, "initial_energy_pj"]
        df.loc[phev_electric_mask, "allocation_rule"] = "phev_utilisation_electric"

        group_keys = ["economy", "scenario", "fuel"]
        phev_electric_by_group = (
            df.loc[phev_electric_mask]
            .groupby(group_keys, dropna=False)["allocated_branch_fuel_pj"]
            .sum()
            .to_dict()
        )
        if non_phev_electric_mask.any():
            total_non_phev_electric = (
                df.loc[non_phev_electric_mask]
                .groupby(group_keys)["initial_energy_pj"]
                .transform("sum")
            )
            residual_electric = []
            for _, row in df.loc[non_phev_electric_mask, group_keys + ["remaining_esto_fuel_pj"]].iterrows():
                key = tuple(row[c] for c in group_keys)
                residual_electric.append(
                    max(0.0, float(row["remaining_esto_fuel_pj"]) - float(phev_electric_by_group.get(key, 0.0)))
                )
            residual_electric = pd.Series(residual_electric, index=df.loc[non_phev_electric_mask].index)
            electric_share = (
                df.loc[non_phev_electric_mask, "initial_energy_pj"] / total_non_phev_electric.replace(0.0, np.nan)
            ).fillna(0.0)
            df.loc[non_phev_electric_mask, "branch_allocation_share"] = electric_share
            df.loc[non_phev_electric_mask, "allocated_branch_fuel_pj"] = (
                electric_share * residual_electric
            )
            df.loc[non_phev_electric_mask, "allocation_rule"] = "residual_electric_energy_share"

    # PHEV liquid demand is separately derived from the utilisation factor.
    phev_liquid_mask = df["drive_type"].isin(_PLUGIN_HYBRID_DRIVES) & (df["fuel"] != "Electricity")
    if phev_liquid_mask.any():
        if phev_liquid_table is not None and not phev_liquid_table.empty:
            liq = phev_liquid_table.copy()
            if "size" not in liq.columns:
                liq["size"] = pd.NA
            merge_keys = ["economy", "scenario", "transport_type", "vehicle_type", "drive_type", "fuel"]
            if "size" in df.columns:
                merge_keys.append("size")
            liq = (
                liq.groupby(merge_keys, dropna=False, as_index=False)["phev_liquid_pj"]
                .sum()
            )
            df = df.merge(liq, on=merge_keys, how="left")
            df["phev_liquid_pj"] = df["phev_liquid_pj"].fillna(0.0)
        else:
            df["phev_liquid_pj"] = 0.0

        phev_liquid_mask = df["drive_type"].isin(_PLUGIN_HYBRID_DRIVES) & (df["fuel"] != "Electricity")
        liquid_total = df.loc[phev_liquid_mask].groupby(["economy", "scenario", "fuel"])["phev_liquid_pj"].transform("sum")
        liquid_share = (
            df.loc[phev_liquid_mask, "phev_liquid_pj"] / liquid_total.replace(0.0, np.nan)
        ).fillna(0.0)
        df.loc[phev_liquid_mask, "branch_allocation_share"] = liquid_share
        df.loc[phev_liquid_mask, "allocated_branch_fuel_pj"] = df.loc[phev_liquid_mask, "phev_liquid_pj"]
        df.loc[phev_liquid_mask, "allocation_rule"] = "phev_utilisation_liquid"

    # All remaining non-electric, non-PHEV-liquid fuel is allocated to the
    # ordinary eligible branches. Conventional gasoline/diesel fuels use the
    # documented vehicle priority tiers before falling back to stock shares.
    normal_mask = ~(electricity_mask | phev_liquid_mask)
    if normal_mask.any():
        group_keys = ["economy", "scenario", "fuel"]
        priority_mask = normal_mask & df["fuel"].isin(_FUEL_ALLOCATION_PRIORITY)
        allocated_groups = []

        if priority_mask.any():
            for _, scenario_rows in df.loc[priority_mask].groupby(["economy", "scenario"], dropna=False):
                base_tier_capacity = _build_priority_tier_capacity(scenario_rows)
                fuel_names = sorted(
                    scenario_rows["fuel"].dropna().unique(),
                    key=lambda fuel: _PRIORITY_FUEL_ALLOCATION_ORDER.get(str(fuel), 99),
                )
                for fuel in fuel_names:
                    fuel_group = scenario_rows[scenario_rows["fuel"] == fuel]
                    allocated_groups.append(
                        _allocate_priority_fuel_group(
                            fuel_group,
                            remaining_tier_capacity=dict(base_tier_capacity),
                        )
                    )

        stock_share_mask = normal_mask & ~df["fuel"].isin(_FUEL_ALLOCATION_PRIORITY)
        allocated_groups.extend(
            _allocate_priority_fuel_group(group)
            for _, group in df.loc[stock_share_mask].groupby(group_keys, dropna=False)
        )
        allocated_normal = pd.concat(allocated_groups, axis=0) if allocated_groups else pd.DataFrame()
        for col in ["branch_allocation_share", "allocated_branch_fuel_pj", "allocation_rule"]:
            df.loc[allocated_normal.index, col] = allocated_normal[col]

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


def _apply_peer_scalars_to_zero_stock_branches(t9: pd.DataFrame) -> pd.DataFrame:
    """
    For branches with zero base-year stock, replace their mileage/efficiency scalars
    with the mean from reconciled peer branches.

    Peer lookup hierarchy (first match wins):
      1. same (economy, scenario, drive_type)           — all fuels, same drive technology
      2. same (economy, scenario, vehicle_type, size)   — all drives, same vehicle size
      3. same (economy, scenario, vehicle_type)         — all drives, same vehicle type
    """
    zero_mask = t9["stock"].fillna(0).le(0)
    if not zero_mask.any():
        return t9

    t9 = t9.copy()
    peer_rows = t9[~zero_mask]

    peer_ms = pd.Series(np.nan, index=t9.index)
    peer_es = pd.Series(np.nan, index=t9.index)

    grouping_levels: list[list[str]] = [
        [k for k in ["economy", "scenario", "drive_type"] if k in t9.columns],
        [k for k in ["economy", "scenario", "vehicle_type", "size"] if k in t9.columns],
        [k for k in ["economy", "scenario", "vehicle_type"] if k in t9.columns],
    ]
    # Remove degenerate levels (e.g. if "size" absent, level 2 collapses to level 3)
    seen: set[tuple[str, ...]] = set()
    unique_levels = []
    for lk in grouping_levels:
        key = tuple(lk)
        if key not in seen:
            seen.add(key)
            unique_levels.append(lk)

    remaining = t9[zero_mask].index.tolist()

    for level_keys in unique_levels:
        if not remaining:
            break
        if peer_rows.empty:
            break

        mean_scalars = (
            peer_rows.groupby(level_keys)[["mileage_scalar", "efficiency_scalar"]]
            .mean()
            .reset_index()
            .rename(columns={"mileage_scalar": "_peer_ms", "efficiency_scalar": "_peer_es"})
        )

        zero_df = t9.loc[remaining, level_keys].copy()
        zero_df["_orig_idx"] = remaining
        merged = zero_df.merge(mean_scalars, on=level_keys, how="left")

        got = merged["_peer_ms"].notna() & merged["_peer_es"].notna()
        if got.any():
            orig_idxs = merged.loc[got, "_orig_idx"].values
            peer_ms.loc[orig_idxs] = merged.loc[got, "_peer_ms"].values
            peer_es.loc[orig_idxs] = merged.loc[got, "_peer_es"].values
            remaining = [i for i in remaining if i not in set(orig_idxs)]

    filled = peer_ms.notna() & zero_mask
    if filled.any():
        t9.loc[filled, "mileage_scalar"] = peer_ms[filled]
        t9.loc[filled, "efficiency_scalar"] = peer_es[filled]
        t9.loc[filled, "adjusted_mileage_km_per_year"] = (
            t9.loc[filled, "mileage_km_per_year"] * peer_ms[filled]
        )
        t9.loc[filled, "adjusted_efficiency_km_per_gj"] = (
            t9.loc[filled, "efficiency_km_per_gj"] * peer_es[filled]
        )
        log.info(
            "Applied peer-group mileage/efficiency scalars to %d zero-stock branch row(s)",
            int(filled.sum()),
        )

    return t9


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

    Bounded scalars are reapplied iteratively against the residual energy gap,
    but bounds apply to the cumulative change from the original branch values.

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
    if "stock_bootstrapped_for_reconciliation" in base_year_branches.columns:
        base_cols.append("stock_bootstrapped_for_reconciliation")

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
    max_iteration_count = 0
    out_of_bounds_count = 0
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
        hit_max_iterations = False

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
                ss, ms, es, adj_s_new, adj_m_new, adj_e_new, within_step = apply_scalars_with_cumulative_bounds(
                    original_stock=s,
                    original_mileage=m,
                    original_efficiency=e,
                    ecf=ecf_iter,
                    weights=weights,
                    scalar_bounds=scalar_bounds,
                    current_stock_scalar=ss,
                    current_mileage_scalar=ms,
                    current_efficiency_scalar=es,
                )
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
                hit_max_iterations = True
                max_iteration_count += 1

            if not within:
                out_of_bounds_count += 1

        scalar_rows.append({
            "stock_scalar": ss,
            "mileage_scalar": ms,
            "efficiency_scalar": es,
            "stock_weight": weights["stock"],
            "mileage_weight": weights["mileage"],
            "efficiency_weight": weights["efficiency"],
            "adjusted_stock": adj_s,
            "adjusted_mileage_km_per_year": adj_m,
            "adjusted_efficiency_km_per_gj": adj_e,
            "final_branch_fuel_pj": final_branch_fuel_pj,
            "scalars_within_bounds": within,
            "reconciliation_iterations": iterations_used,
            "reconciliation_hit_max_iterations": hit_max_iterations,
        })

    scalar_df = pd.DataFrame(scalar_rows)
    t9 = pd.concat([merged.reset_index(drop=True), scalar_df], axis=1)
    if max_iteration_count or out_of_bounds_count:
        log.info(
            "Module 6 reconciliation summary: %d branch(es) hit max iterations; %d branch(es) used scalars outside configured bounds. See T9/T12 diagnostics for details.",
            max_iteration_count,
            out_of_bounds_count,
        )
    t9 = _apply_peer_scalars_to_zero_stock_branches(t9)
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

    raw_stock_scalar = ecf ** w_s
    raw_mileage_scalar = ecf ** w_m
    raw_efficiency_scalar = ecf ** (-w_e)

    stock_scalar = float(np.clip(raw_stock_scalar, lo_s, hi_s))
    mileage_scalar = float(np.clip(raw_mileage_scalar, lo_m, hi_m))
    efficiency_scalar = float(np.clip(raw_efficiency_scalar, lo_e, hi_e))
    mileage_scalar, efficiency_scalar = _align_mileage_efficiency_scalars(
        mileage_scalar=mileage_scalar,
        efficiency_scalar=efficiency_scalar,
        mileage_weight=w_m,
        efficiency_weight=w_e,
        scalar_bounds=bounds,
    )

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


def _adjust_branch_to_energy_target(
    stock: float,
    mileage: float,
    efficiency: float,
    target_energy_pj: float,
    weights: dict[str, float],
    scalar_bounds: tuple[float, float] | dict[str, tuple[float, float]],
    max_iterations: int = 24,
    energy_tolerance: float = 1e-9,
) -> tuple[float, float, float, float, bool]:
    """
    Adjust one branch until its fuel energy reaches the requested target.

    This mirrors the residual iteration used in reconcile_stock_mileage_efficiency,
    but returns only the adjusted branch values needed by the electricity
    pre-reconciliation step.
    """
    initial_energy_pj = stock * mileage / efficiency / 1_000_000 if efficiency > 0 else 0.0
    if target_energy_pj <= 0 or initial_energy_pj <= 0:
        ecf = 0.0 if target_energy_pj <= 0 else 1.0
        _, _, _, adj_s, adj_m, adj_e, within = apply_scalars(
            stock, mileage, efficiency, ecf, weights, scalar_bounds
        )
        final_energy_pj = adj_s * adj_m / adj_e / 1_000_000 if adj_e > 0 and target_energy_pj > 0 else 0.0
        return adj_s, adj_m, adj_e, final_energy_pj, within

    stock_scalar = mileage_scalar = efficiency_scalar = 1.0
    adj_s = stock
    adj_m = mileage
    adj_e = efficiency
    within = True
    previous_energy_pj = initial_energy_pj
    final_energy_pj = initial_energy_pj

    for _iteration in range(1, max_iterations + 1):
        current_energy_pj = adj_s * adj_m / adj_e / 1_000_000 if adj_e > 0 else 0.0
        if current_energy_pj <= 0:
            return adj_s, adj_m, adj_e, 0.0, False

        ecf_iter = target_energy_pj / current_energy_pj
        stock_scalar, mileage_scalar, efficiency_scalar, adj_s, adj_m, adj_e, within_step = (
            apply_scalars_with_cumulative_bounds(
                original_stock=stock,
                original_mileage=mileage,
                original_efficiency=efficiency,
                ecf=ecf_iter,
                weights=weights,
                scalar_bounds=scalar_bounds,
                current_stock_scalar=stock_scalar,
                current_mileage_scalar=mileage_scalar,
                current_efficiency_scalar=efficiency_scalar,
            )
        )
        within = within and within_step
        final_energy_pj = adj_s * adj_m / adj_e / 1_000_000 if adj_e > 0 else 0.0

        if abs(final_energy_pj - target_energy_pj) <= max(target_energy_pj * energy_tolerance, energy_tolerance):
            break
        if abs(final_energy_pj - previous_energy_pj) <= max(previous_energy_pj * energy_tolerance, energy_tolerance):
            break
        previous_energy_pj = final_energy_pj

    return adj_s, adj_m, adj_e, final_energy_pj, within


def apply_scalars_with_cumulative_bounds(
    original_stock: float,
    original_mileage: float,
    original_efficiency: float,
    ecf: float,
    weights: dict[str, float],
    scalar_bounds: tuple[float, float] | dict[str, tuple[float, float]],
    current_stock_scalar: float,
    current_mileage_scalar: float,
    current_efficiency_scalar: float,
) -> tuple[float, float, float, float, float, float, bool]:
    """
    Apply one residual reconciliation step while bounding total branch change.

    Returns cumulative scalars and adjusted values, where each adjusted value is
    based on the original branch value rather than the prior iteration value.
    """
    w_s, w_m, w_e = weights["stock"], weights["mileage"], weights["efficiency"]
    bounds = _normalise_scalar_bounds(scalar_bounds)
    lo_s, hi_s = bounds["stock"]
    lo_m, hi_m = bounds["mileage"]
    lo_e, hi_e = bounds["efficiency"]

    if ecf <= 0:
        stock_scalar = lo_s
        mileage_scalar = lo_m
        efficiency_scalar = hi_e
        return (
            stock_scalar,
            mileage_scalar,
            efficiency_scalar,
            original_stock * stock_scalar,
            original_mileage * mileage_scalar,
            original_efficiency * efficiency_scalar,
            False,
        )

    raw_stock_scalar = current_stock_scalar * (ecf ** w_s)
    raw_mileage_scalar = current_mileage_scalar * (ecf ** w_m)
    raw_efficiency_scalar = current_efficiency_scalar * (ecf ** (-w_e))

    stock_scalar = float(np.clip(raw_stock_scalar, lo_s, hi_s))
    mileage_scalar = float(np.clip(raw_mileage_scalar, lo_m, hi_m))
    efficiency_scalar = float(np.clip(raw_efficiency_scalar, lo_e, hi_e))
    mileage_scalar, efficiency_scalar = _align_mileage_efficiency_scalars(
        mileage_scalar=mileage_scalar,
        efficiency_scalar=efficiency_scalar,
        mileage_weight=w_m,
        efficiency_weight=w_e,
        scalar_bounds=bounds,
    )

    within_bounds = all(
        [
            lo_s <= raw_stock_scalar <= hi_s,
            lo_m <= raw_mileage_scalar <= hi_m,
            lo_e <= raw_efficiency_scalar <= hi_e,
        ]
    )

    return (
        stock_scalar,
        mileage_scalar,
        efficiency_scalar,
        original_stock * stock_scalar,
        original_mileage * mileage_scalar,
        original_efficiency * efficiency_scalar,
        within_bounds,
    )


def _align_mileage_efficiency_scalars(
    mileage_scalar: float,
    efficiency_scalar: float,
    mileage_weight: float,
    efficiency_weight: float,
    scalar_bounds: dict[str, tuple[float, float]],
) -> tuple[float, float]:
    """
    Remove cancelling mileage/efficiency movement while preserving net energy effect.

    Energy is proportional to mileage / efficiency, so higher efficiency has the
    same energy effect as lower mileage. If both cumulative scalars move above
    or below 1.0 together, part of the pair is cancelling itself out. Re-express
    the same mileage/efficiency energy ratio with opposite-direction scalars.
    """
    if not _mileage_efficiency_scalars_conflict(mileage_scalar, efficiency_scalar):
        return mileage_scalar, efficiency_scalar

    if mileage_scalar <= 0 or efficiency_scalar <= 0:
        return mileage_scalar, efficiency_scalar

    energy_ratio = mileage_scalar / efficiency_scalar
    if not np.isfinite(energy_ratio) or energy_ratio <= 0:
        return mileage_scalar, efficiency_scalar

    lo_m, hi_m = scalar_bounds["mileage"]
    lo_e, hi_e = scalar_bounds["efficiency"]
    total_weight = mileage_weight + efficiency_weight
    if total_weight <= 0:
        mileage_share = efficiency_share = 0.5
    else:
        mileage_share = mileage_weight / total_weight
        efficiency_share = efficiency_weight / total_weight

    aligned_mileage = float(np.clip(energy_ratio ** mileage_share, lo_m, hi_m))
    aligned_efficiency = float(np.clip(energy_ratio ** (-efficiency_share), lo_e, hi_e))

    if not _mileage_efficiency_scalars_conflict(aligned_mileage, aligned_efficiency):
        return aligned_mileage, aligned_efficiency

    # Fallback for unusual bounds: keep the net energy direction and neutralise
    # the opposing scalar as much as the configured bounds allow.
    neutral_mileage = float(np.clip(1.0, lo_m, hi_m))
    neutral_efficiency = float(np.clip(1.0, lo_e, hi_e))
    if energy_ratio >= 1.0:
        aligned_efficiency = neutral_efficiency
        aligned_mileage = float(np.clip(energy_ratio * aligned_efficiency, lo_m, hi_m))
    else:
        aligned_mileage = neutral_mileage
        aligned_efficiency = float(np.clip(aligned_mileage / energy_ratio, lo_e, hi_e))

    return aligned_mileage, aligned_efficiency


def _mileage_efficiency_scalars_conflict(
    mileage_scalar: float,
    efficiency_scalar: float,
    tolerance: float = 1e-12,
) -> bool:
    """Return True when mileage and efficiency changes cancel each other."""
    if not (np.isfinite(mileage_scalar) and np.isfinite(efficiency_scalar)):
        return False
    mileage_delta = mileage_scalar - 1.0
    efficiency_delta = efficiency_scalar - 1.0
    return abs(mileage_delta) > tolerance and abs(efficiency_delta) > tolerance and (
        mileage_delta * efficiency_delta > 0
    )


def _normalise_scalar_bounds(
    scalar_bounds: tuple[float, float] | dict[str, tuple[float, float]],
) -> dict[str, tuple[float, float]]:
    """
    Normalise scalar-bounds input into per-scalar bounds.

    Accepts:
      - tuple(min, max): applied to stock/mileage/efficiency
      - dict with all keys {'stock','mileage','efficiency'} — all three are required
    """
    if isinstance(scalar_bounds, tuple):
        lo, hi = scalar_bounds
        return {
            "stock": (float(lo), float(hi)),
            "mileage": (float(lo), float(hi)),
            "efficiency": (float(lo), float(hi)),
        }

    out: dict[str, tuple[float, float]] = {}
    missing = []
    for key in ("stock", "mileage", "efficiency"):
        if key in scalar_bounds and scalar_bounds[key] is not None:
            lo, hi = scalar_bounds[key]
            out[key] = (float(lo), float(hi))
        else:
            missing.append(key)
    if missing:
        raise ValueError(
            f"scalar_bounds is missing required keys: {missing}. "
            "Supply bounds for all of stock, mileage, and efficiency."
        )
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

    total_implied = df.groupby(group_keys, dropna=False)["implied_vehicles_using_fuel"].transform("sum")

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
    """Build T12_reconciliation_diagnostics table.

    reconciliation_scalars (and phev_liquid_table) carry one row group per
    scenario — the ESTO target is scenario-agnostic (base year only), so each
    scenario's pre/post energy must be compared against the target on its own.
    Summing across scenarios before comparing would inflate the model side by
    the scenario count and falsely report reconciliation failures.
    """
    if reconciliation_scalars.empty:
        return pd.DataFrame()

    group_keys = ["economy", "scenario"]
    rows = []
    for (economy, scenario), scenario_scalars in reconciliation_scalars.groupby(group_keys, dropna=False):
        scenario_phev = (
            phev_liquid_table[phev_liquid_table["scenario"].eq(scenario)]
            if not phev_liquid_table.empty and "scenario" in phev_liquid_table.columns
            else phev_liquid_table
        )
        phev_by_fuel: dict[str, float] = (
            scenario_phev.groupby("fuel")["phev_liquid_pj"].sum().to_dict()
            if not scenario_phev.empty
            else {}
        )

        pre_by_fuel = scenario_scalars.groupby("fuel")["allocated_branch_fuel_pj"].sum().to_dict()
        post_by_fuel = scenario_scalars.groupby("fuel")["final_branch_fuel_pj"].sum().to_dict()

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


def build_phev_utilisation_diagnostics(
    reconciliation_scalars: pd.DataFrame,
    phev_utilisation_rate: PHEVUtilisationRate,
    tolerance: float = 0.10,
) -> pd.DataFrame:
    """
    Back-calculate PHEV electric-mode utilisation from reconciled fuel energy.

    The diagnostic converts final PHEV fuel energy back to a km proxy using the
    adjusted efficiency for each fuel branch:
        electric_km_proxy = electricity_pj * electricity_efficiency_km_per_gj
        liquid_km_proxy   = sum(liquid_pj * liquid_efficiency_km_per_gj)

    The common PJ-to-GJ multiplier cancels in the share calculation.
    """
    cols = [
        "economy", "scenario", "transport_type", "vehicle_type", "drive_type", "size",
        "provided_phev_utilisation_rate", "diagnostic_lower_rate", "diagnostic_upper_rate",
        "backcalculated_phev_utilisation_rate", "electric_energy_pj", "liquid_energy_pj",
        "electric_energy_share", "electric_km_proxy", "liquid_km_proxy",
        "absolute_difference", "utilisation_status",
    ]
    if reconciliation_scalars.empty:
        return pd.DataFrame(columns=cols)

    df = reconciliation_scalars[reconciliation_scalars["drive_type"].isin(_PLUGIN_HYBRID_DRIVES)].copy()
    if df.empty:
        return pd.DataFrame(columns=cols)

    df["final_branch_fuel_pj"] = pd.to_numeric(df["final_branch_fuel_pj"], errors="coerce").fillna(0.0)
    df["adjusted_efficiency_km_per_gj"] = pd.to_numeric(
        df["adjusted_efficiency_km_per_gj"], errors="coerce"
    ).fillna(0.0)
    df["km_proxy"] = df["final_branch_fuel_pj"] * df["adjusted_efficiency_km_per_gj"]

    group_keys = ["economy", "scenario", "transport_type", "vehicle_type", "drive_type"]
    if "size" in df.columns:
        group_keys.append("size")
    else:
        df["size"] = pd.NA
        group_keys.append("size")

    rows: list[dict[str, Any]] = []
    for key, group in df.groupby(group_keys, dropna=False):
        key_data = dict(zip(group_keys, key if isinstance(key, tuple) else (key,)))
        electric = group[group["fuel"] == "Electricity"]
        liquid = group[group["fuel"] != "Electricity"]

        electric_energy = float(electric["final_branch_fuel_pj"].sum())
        liquid_energy = float(liquid["final_branch_fuel_pj"].sum())
        total_energy = electric_energy + liquid_energy
        electric_km_proxy = float(electric["km_proxy"].sum())
        liquid_km_proxy = float(liquid["km_proxy"].sum())
        total_km_proxy = electric_km_proxy + liquid_km_proxy

        provided_rate = _resolve_phev_utilisation_rate(phev_utilisation_rate, group)
        lower_rate = max(0.0, provided_rate - float(tolerance))
        upper_rate = min(1.0, provided_rate + float(tolerance))
        backcalculated_rate = (
            electric_km_proxy / total_km_proxy
            if total_km_proxy > 0
            else np.nan
        )
        absolute_difference = (
            abs(backcalculated_rate - provided_rate)
            if np.isfinite(backcalculated_rate)
            else np.nan
        )
        if not np.isfinite(backcalculated_rate):
            status = "no_phev_energy"
        elif lower_rate <= backcalculated_rate <= upper_rate:
            status = "ok"
        elif backcalculated_rate < lower_rate:
            status = "below_range"
        else:
            status = "above_range"

        rows.append({
            **key_data,
            "provided_phev_utilisation_rate": provided_rate,
            "diagnostic_lower_rate": lower_rate,
            "diagnostic_upper_rate": upper_rate,
            "backcalculated_phev_utilisation_rate": backcalculated_rate,
            "electric_energy_pj": electric_energy,
            "liquid_energy_pj": liquid_energy,
            "electric_energy_share": electric_energy / total_energy if total_energy > 0 else np.nan,
            "electric_km_proxy": electric_km_proxy,
            "liquid_km_proxy": liquid_km_proxy,
            "absolute_difference": absolute_difference,
            "utilisation_status": status,
        })

    return pd.DataFrame(rows)[cols].reset_index(drop=True)



# ===========================================================================
# LEAP-ready output
# ===========================================================================

def build_leap_ready_table(
    reconciliation_scalars: pd.DataFrame,
    device_shares: pd.DataFrame,
    sales_turnover: pd.DataFrame,
    sales_shares: pd.DataFrame,
    projection_years: list[int],
    mileage_correction_factors: pd.DataFrame | None = None,
    fuel_economy_correction_factors: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Combine all Module 6 outputs into the T11_leap_ready tidy table.

    Variables included:
      Base year (from T9/T10):  Stock, Mileage, Fuel Economy, Device Share, Activity Level
      All years (from T6/T7):   Sales, Sales Share

    Fuel Economy is converted from km/GJ → MJ/100km (= 100_000 / km_per_gj).
    Activity Level = adjusted_stock × adjusted_mileage_km_per_year.
    """
    if "leap_branch_path" not in reconciliation_scalars.columns:
        raise ValueError("reconciliation_scalars must contain leap_branch_path")

    t9 = reconciliation_scalars.copy()
    t9["_tech_path"] = t9["leap_branch_path"].apply(_tech_path)
    t9["_vehicle_path"] = t9["leap_branch_path"].apply(_vehicle_path)
    t9["_transport_path"] = t9["leap_branch_path"].apply(_transport_path)

    base_year: int = int(t9["base_year"].iloc[0]) if "base_year" in t9.columns else min(projection_years)
    economy_col = t9["economy"].iloc[0]
    scenario_col = t9["scenario"].iloc[0]

    rows: list[dict] = []

    # ── Deduplicate to one row per technology branch ──────────────────────
    # Fuel-level scalars can diverge after reconciliation. Build technology-level
    # stock from fuel-implied vehicles instead of keeping one fuel row.
    tech_dedup_keys = ["economy", "scenario", "transport_type", "vehicle_type", "drive_type"]
    if "size" in t9.columns:
        tech_dedup_keys.append("size")

    tech_rows = build_reconciled_technology_assumptions(t9)
    tech_rows["_tech_path"] = tech_rows["leap_branch_path"].apply(_tech_path)
    tech_rows["_vehicle_path"] = tech_rows["leap_branch_path"].apply(_vehicle_path)
    tech_rows["_transport_path"] = tech_rows["leap_branch_path"].apply(_transport_path)

    # Stock: LEAP expects transport totals and vehicle-type totals.
    for _, row in tech_rows.groupby(
        ["economy", "scenario", "_transport_path"],
        dropna=False,
        as_index=False,
    )["adjusted_stock"].sum().iterrows():
        rows.append({
            "economy": row["economy"], "scenario": row["scenario"],
            "year": base_year, "leap_branch_path": row["_transport_path"],
            "variable": "Stock", "value": row["adjusted_stock"], "unit": "Device",
        })
    for _, row in tech_rows.groupby(
        ["economy", "scenario", "_vehicle_path"],
        dropna=False,
        as_index=False,
    )["adjusted_stock"].sum().iterrows():
        rows.append({
            "economy": row["economy"], "scenario": row["scenario"],
            "year": base_year, "leap_branch_path": row["_vehicle_path"],
            "variable": "Stock", "value": row["adjusted_stock"], "unit": "Device",
        })

    # Stock Share: vehicle-type split of transport total and tech split of vehicle total.
    transport_totals = tech_rows.groupby(
        ["economy", "scenario", "_transport_path"], dropna=False,
    )["adjusted_stock"].sum()
    vehicle_totals = tech_rows.groupby(
        ["economy", "scenario", "_vehicle_path"], dropna=False,
    )["adjusted_stock"].sum()
    vehicle_share_rows = tech_rows.groupby(
        ["economy", "scenario", "_transport_path", "_vehicle_path"],
        dropna=False,
        as_index=False,
    )["adjusted_stock"].sum()
    for _, row in vehicle_share_rows.iterrows():
        transport_total = float(transport_totals.get((row["economy"], row["scenario"], row["_transport_path"]), 0.0))
        vehicle_share = (float(row["adjusted_stock"]) / transport_total * 100.0) if transport_total > 0 else 0.0
        rows.append({
            "economy": row["economy"], "scenario": row["scenario"],
            "year": base_year, "leap_branch_path": row["_vehicle_path"],
            "variable": "Stock Share", "value": vehicle_share, "unit": "Share",
        })
        rows.append({
            "economy": row["economy"], "scenario": row["scenario"],
            "year": base_year, "leap_branch_path": row["_vehicle_path"],
            "variable": "Sales Share", "value": vehicle_share, "unit": "Share",
        })

    for _, row in tech_rows.iterrows():
        vehicle_total = float(vehicle_totals.get((row["economy"], row["scenario"], row["_vehicle_path"]), 0.0))
        tech_share = (float(row["adjusted_stock"]) / vehicle_total * 100.0) if vehicle_total > 0 else 0.0
        rows.append({
            "economy": row["economy"], "scenario": row["scenario"],
            "year": base_year, "leap_branch_path": row["_tech_path"],
            "variable": "Stock Share", "value": tech_share, "unit": "Share",
        })

    # Mileage: LEAP expects fuel-level paths.
    for _, row in t9.iterrows():
        rows.append({
            "economy": row["economy"], "scenario": row["scenario"],
            "year": base_year, "leap_branch_path": row["leap_branch_path"],
            "variable": "Mileage", "value": row["adjusted_mileage_km_per_year"], "unit": "Kilometer",
        })

    # ── Fuel Economy (base year, fuel-level path) ─────────────────────────
    for _, row in t9.iterrows():
        eff = row["adjusted_efficiency_km_per_gj"]
        fe = 100_000.0 / eff if eff > 0 else np.nan
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
                "variable": "Device Share", "value": row["device_share"] * 100.0, "unit": "Share",
            })

    # ── Build (vehicle_type, drive_type) → tech_path lookup from T9 ───────
    vt_dt_path = (
        t9.groupby(tech_dedup_keys, dropna=False)["_tech_path"]
        .first()
        .reset_index()
        .rename(columns={"_tech_path": "_tech_path_lookup"})
    )
    # Lookup keys: use whatever dimension columns are available in both sides
    lookup_keys = [k for k in tech_dedup_keys if k in vt_dt_path.columns]

    # Sales: LEAP expects transport-type totals.
    if not sales_turnover.empty and "new_sales" in sales_turnover.columns:
        t6 = sales_turnover.copy()
        t6["_transport_path"] = t6["transport_type"].map(
            lambda value: "Demand\\Passenger road" if str(value) == "passenger" else "Demand\\Freight road"
        )
        for _, row in t6.groupby(
            ["economy", "scenario", "year", "transport_type", "_transport_path"],
            dropna=False,
            as_index=False,
        )["new_sales"].sum().iterrows():
            if int(row["year"]) not in projection_years:
                continue
            rows.append({
                "economy": row["economy"], "scenario": row["scenario"],
                "year": int(row["year"]), "leap_branch_path": row["_transport_path"],
                "variable": "Sales", "value": row["new_sales"], "unit": "Device",
            })

        # Vehicle-type Sales Share as share of transport-type sales.
        t6["_vehicle_path"] = t6.apply(
            lambda row: (
                "Demand\\Passenger road\\" + str(row["vehicle_type"])
                if str(row["transport_type"]) == "passenger"
                else "Demand\\Freight road\\" + str(row["vehicle_type"])
            ),
            axis=1,
        )
        vehicle_sales = t6.groupby(
            ["economy", "scenario", "year", "transport_type", "_vehicle_path"],
            dropna=False,
            as_index=False,
        )["new_sales"].sum()
        transport_sales = t6.groupby(
            ["economy", "scenario", "year", "transport_type"],
            dropna=False,
            as_index=False,
        )["new_sales"].sum().rename(columns={"new_sales": "_transport_sales"})
        vehicle_sales = vehicle_sales.merge(
            transport_sales,
            on=["economy", "scenario", "year", "transport_type"],
            how="left",
        )
        for _, row in vehicle_sales.iterrows():
            if int(row["year"]) not in projection_years or int(row["year"]) == base_year:
                continue
            total = float(row.get("_transport_sales", 0.0))
            share = (float(row["new_sales"]) / total * 100.0) if total > 0 else 0.0
            rows.append({
                "economy": row["economy"], "scenario": row["scenario"],
                "year": int(row["year"]), "leap_branch_path": row["_vehicle_path"],
                "variable": "Sales Share", "value": share, "unit": "Share",
            })

    # ── Sales Share (all projection years, technology-level path) ─────────
    if not sales_shares.empty and "sales_share" in sales_shares.columns:
        ss_keys = [k for k in lookup_keys if k in sales_shares.columns]
        ss_path = sales_shares.merge(vt_dt_path, on=ss_keys, how="left")

        # When the branch structure has size variants (e.g. Trucks heavy / medium)
        # but Module 5 produces drive-level shares without a size dimension, the
        # merge fans each drive's single share out to every size row.  Each size
        # must receive a fraction of the drive share proportional to its stock so
        # all children still sum to 100 %.
        if "size" in vt_dt_path.columns and "size" not in sales_shares.columns and "size" in ss_path.columns:
            drive_keys = [k for k in ["economy", "scenario", "vehicle_type", "drive_type"] if k in tech_rows.columns]
            size_keys = drive_keys + (["size"] if "size" in tech_rows.columns else [])
            size_stock = tech_rows.groupby(size_keys, dropna=False)["adjusted_stock"].sum().reset_index()
            drive_total = (
                size_stock.groupby(drive_keys)["adjusted_stock"].sum()
                .reset_index().rename(columns={"adjusted_stock": "_drive_total"})
            )
            size_stock = size_stock.merge(drive_total, on=drive_keys, how="left")
            size_stock["_size_fraction"] = (
                size_stock["adjusted_stock"] / size_stock["_drive_total"].replace(0, np.nan)
            )  # NaN when drive has zero stock — filled below with equal split
            merge_keys = [k for k in size_keys if k in ss_path.columns]
            ss_path = ss_path.merge(size_stock[size_keys + ["_size_fraction"]], on=merge_keys, how="left")
            # For drive types absent from tech_rows (e.g. zero-stock EVs), fall back
            # to equal split across the number of size variants rather than 1.0 each.
            grp_keys = [k for k in ["economy", "scenario", "vehicle_type", "drive_type"] if k in ss_path.columns]
            n_sizes = ss_path.groupby(grp_keys, dropna=False)["size"].transform("count")
            ss_path["_size_fraction"] = ss_path["_size_fraction"].fillna(1.0 / n_sizes)
            ss_path["sales_share"] = ss_path["sales_share"] * ss_path["_size_fraction"]

        if "year" in ss_path.columns:
            # Multi-year sales shares (Module 5 produces future-year shares)
            for _, row in ss_path.iterrows():
                if pd.isna(row.get("_tech_path_lookup")) or int(row["year"]) not in projection_years:
                    continue
                rows.append({
                    "economy": row["economy"], "scenario": row["scenario"],
                    "year": int(row["year"]), "leap_branch_path": row["_tech_path_lookup"],
                    "variable": "Sales Share", "value": row["sales_share"] * 100.0, "unit": "Share",
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
                        "variable": "Sales Share", "value": row["sales_share"] * 100.0, "unit": "Share",
                    })

    factor_specs = [
        (mileage_correction_factors, "Mileage Correction Factor"),
        (fuel_economy_correction_factors, "Fuel Economy Correction Factor"),
    ]
    valid_factor_paths = set(t9["leap_branch_path"].dropna().astype(str))
    for factor_df, factor_variable in factor_specs:
        if factor_df is None or factor_df.empty:
            continue
        factor_rows = factor_df.copy()
        required_factor_cols = {"leap_branch_path", "year", "value"}
        if not required_factor_cols.issubset(factor_rows.columns):
            missing = sorted(required_factor_cols - set(factor_rows.columns))
            raise ValueError(f"{factor_variable} rows are missing columns: {missing}")

        factor_rows["year"] = pd.to_numeric(factor_rows["year"], errors="coerce")
        factor_rows["value"] = pd.to_numeric(factor_rows["value"], errors="coerce")
        factor_rows = factor_rows.dropna(subset=["year", "value", "leap_branch_path"])
        factor_rows["year"] = factor_rows["year"].astype(int)
        factor_rows = factor_rows[factor_rows["year"].isin(projection_years)].copy()
        factor_rows = factor_rows[factor_rows["leap_branch_path"].astype(str).isin(valid_factor_paths)].copy()
        if "scenario" not in factor_rows.columns:
            factor_rows["scenario"] = scenario_col
        if "economy" not in factor_rows.columns:
            factor_rows["economy"] = economy_col

        for _, row in factor_rows.iterrows():
            rows.append({
                "economy": row["economy"], "scenario": row["scenario"],
                "year": int(row["year"]), "leap_branch_path": row["leap_branch_path"],
                "variable": factor_variable, "value": row["value"], "unit": "Multiplier",
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
