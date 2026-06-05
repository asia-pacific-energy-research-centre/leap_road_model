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


# Single-fuel drive types: device_share is always 1.0
_SINGLE_FUEL_DRIVES = {"BEV", "FCEV"}

# Plug-in hybrid drive types share the PHEV electric-utilisation workflow.
_PLUGIN_HYBRID_DRIVES = {"PHEV", "EREV"}

# PHEV liquid fuels used for the transport-sector liquid blend.
# LPG and CNG are intentionally excluded from the PHEV liquid split policy.
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


def _vehicle_path(branch_path: str) -> str:
    """Return Demand\\{road}\\{vehicle type} from a road LEAP branch path."""
    return "\\".join(str(branch_path).split("\\")[:3])


def _transport_path(branch_path: str) -> str:
    """Return Demand\\{road} from a road LEAP branch path."""
    return "\\".join(str(branch_path).split("\\")[:2])


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
    phev_electric_utilisation_rate: float = 0.50,
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
        phev_electric_utilisation_rate: PHEV fraction driven on electricity (single float).
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
    t11 = build_leap_ready_table(t9, t10, sales_turnover, sales_shares, projection_years)

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
    phev_utilisation_rate: float | None = None,
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


def apply_phev_mileage_split(
    base_year_branches: pd.DataFrame,
    phev_utilisation_rate: float,
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

        rate = min(1.0, max(0.0, float(phev_utilisation_rate)))

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
    phev_utilisation_rate: float,
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
    phev_elec_mask = elec_mask & df["drive_type"].isin(_PLUGIN_HYBRID_DRIVES)
    non_phev_elec_mask = elec_mask & (~df["drive_type"].isin(_PLUGIN_HYBRID_DRIVES))

    # Build phev_liquid_table from unadjusted data if reconciliation cannot run
    def _build_phev_liquid(source_df: pd.DataFrame) -> pd.DataFrame:
        return _compute_phev_liquid(source_df, phev_utilisation_rate)

    if electricity_esto_pj <= 0 or not elec_mask.any():
        return df, _build_phev_liquid(df)

    phev_electric_pj = float(df.loc[phev_elec_mask, "initial_energy_pj"].sum())
    residual_electricity_pj = max(0.0, float(electricity_esto_pj) - phev_electric_pj)
    if phev_electric_pj > electricity_esto_pj:
        log.warning(
            "PHEV electricity implied by utilisation (%.3f PJ) exceeds ESTO road electricity (%.3f PJ)",
            phev_electric_pj,
            electricity_esto_pj,
        )

    total_initial_elec = df.loc[non_phev_elec_mask, "initial_energy_pj"].sum()
    if total_initial_elec <= 0:
        return df, _build_phev_liquid(df)

    ecf = residual_electricity_pj / total_initial_elec

    # Apply scalars to non-PHEV electricity branches only. PHEV electricity is
    # governed by the utilisation factor and reconciled as paired electric /
    # liquid demand.
    for idx in df[non_phev_elec_mask].index:
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
    phev_utilisation_rate: float,
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
    PHEV liquid fuels (motor gasoline, gas/diesel oil, biodiesel, biogasoline,
    and efuel). LPG and CNG are intentionally ignored for PHEVs in this first
    version.
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

        preferred_mask = group["fuel"].isin(_PHEV_LIQUID_FUELS)
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

    # Join with remaining_esto on fuel
    df = df.merge(remaining_esto, on="fuel", how="left")
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
        total_non_phev_electric = df.loc[non_phev_electric_mask].groupby(group_keys)["initial_energy_pj"].transform("sum")
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
    # ordinary eligible branches using stock shares.
    normal_mask = ~(electricity_mask | phev_liquid_mask)
    if normal_mask.any():
        group_keys = ["economy", "scenario", "fuel"]
        total_stock = df.loc[normal_mask].groupby(group_keys)["stock"].transform("sum")
        normal_share = (df.loc[normal_mask, "stock"] / total_stock.replace(0.0, np.nan)).fillna(0.0)
        df.loc[normal_mask, "branch_allocation_share"] = normal_share
        df.loc[normal_mask, "allocated_branch_fuel_pj"] = (
            normal_share * df.loc[normal_mask, "remaining_esto_fuel_pj"]
        )

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


def build_phev_utilisation_diagnostics(
    reconciliation_scalars: pd.DataFrame,
    phev_utilisation_rate: float,
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

        provided_rate = float(phev_utilisation_rate)
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
    t9["_vehicle_path"] = t9["leap_branch_path"].apply(_vehicle_path)
    t9["_transport_path"] = t9["leap_branch_path"].apply(_transport_path)

    base_year: int = int(t9["base_year"].iloc[0]) if "base_year" in t9.columns else min(projection_years)
    economy_col = t9["economy"].iloc[0]
    scenario_col = t9["scenario"].iloc[0]

    rows: list[dict] = []

    # ── Deduplicate to one row per technology branch ──────────────────────
    # All fuel rows of the same drive type share the same stock/mileage.
    # Priority for deduplication: prefer the primary fuel row for each drive type.
    _primary_fuel_map = {"BEV": "Electricity", "FCEV": "Hydrogen", "PHEV": "Electricity", "EREV": "Electricity"}
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
    transport_totals = tech_rows.groupby("_transport_path")["adjusted_stock"].sum().to_dict()
    vehicle_totals = tech_rows.groupby("_vehicle_path")["adjusted_stock"].sum().to_dict()
    vehicle_share_rows = tech_rows.groupby(
        ["economy", "scenario", "_transport_path", "_vehicle_path"],
        dropna=False,
        as_index=False,
    )["adjusted_stock"].sum()
    for _, row in vehicle_share_rows.iterrows():
        transport_total = float(transport_totals.get(row["_transport_path"], 0.0))
        vehicle_share = (float(row["adjusted_stock"]) / transport_total * 100.0) if transport_total > 0 else 0.0
        rows.append({
            "economy": row["economy"], "scenario": row["scenario"],
            "year": base_year, "leap_branch_path": row["_vehicle_path"],
            "variable": "Stock Share", "value": vehicle_share, "unit": "Share",
        })

    for _, row in tech_rows.iterrows():
        vehicle_total = float(vehicle_totals.get(row["_vehicle_path"], 0.0))
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
            if int(row["year"]) not in projection_years:
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
