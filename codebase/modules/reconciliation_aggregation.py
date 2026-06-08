from __future__ import annotations

import numpy as np
import pandas as pd


TECH_DIMENSION_COLUMNS = [
    "economy",
    "scenario",
    "transport_type",
    "vehicle_type",
    "drive_type",
    "size",
]


def build_reconciled_technology_assumptions(reconciliation_scalars: pd.DataFrame) -> pd.DataFrame:
    """
    Collapse fuel-level reconciliation rows to one technology-level row.

    Module 6 reconciles stock, mileage, and efficiency at fuel-row level. LEAP
    stock and Module 7's mirror stock are technology-level values, so selecting
    one arbitrary fuel row can understate multi-fuel branches. The stable
    technology stock is the sum of vehicles implied by each reconciled fuel row.
    """
    required = {
        "drive_type",
        "leap_branch_path",
        "adjusted_stock",
        "adjusted_mileage_km_per_year",
        "adjusted_efficiency_km_per_gj",
        "final_branch_fuel_pj",
    }
    missing = sorted(required - set(reconciliation_scalars.columns))
    if missing:
        raise KeyError(f"Missing columns in reconciliation_scalars: {missing}")

    df = reconciliation_scalars.copy()
    group_keys = [c for c in TECH_DIMENSION_COLUMNS if c in df.columns]
    if not group_keys:
        raise ValueError("reconciliation_scalars must contain model dimension columns.")

    for col in [
        "adjusted_stock",
        "adjusted_mileage_km_per_year",
        "adjusted_efficiency_km_per_gj",
        "final_branch_fuel_pj",
    ]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    df["_tech_path"] = df["leap_branch_path"].apply(_technology_path)
    df["_energy_per_vehicle_pj"] = np.where(
        df["adjusted_efficiency_km_per_gj"] > 0,
        df["adjusted_mileage_km_per_year"] / df["adjusted_efficiency_km_per_gj"] / 1_000_000,
        np.nan,
    )
    df["_implied_vehicles"] = np.where(
        df["_energy_per_vehicle_pj"] > 0,
        df["final_branch_fuel_pj"] / df["_energy_per_vehicle_pj"],
        0.0,
    )
    df["_implied_vehicles"] = pd.to_numeric(df["_implied_vehicles"], errors="coerce").fillna(0.0).clip(lower=0.0)

    # Single-fuel branches with zero observed energy still need their stock
    # carried through, otherwise zero-energy BEV/FCEV branches disappear from
    # stock shares and projection diagnostics.
    fuel_counts = df.groupby(group_keys, dropna=False)["leap_branch_path"].transform("count")
    zero_implied = df.groupby(group_keys, dropna=False)["_implied_vehicles"].transform("sum").le(0.0)
    single_zero_energy = fuel_counts.eq(1) & zero_implied
    df.loc[single_zero_energy, "_implied_vehicles"] = df.loc[single_zero_energy, "adjusted_stock"]

    df["_weighted_mileage"] = df["adjusted_mileage_km_per_year"] * df["_implied_vehicles"]

    grouped = df.groupby(group_keys, dropna=False)
    out = grouped.agg(
        adjusted_stock=("_implied_vehicles", "sum"),
        final_technology_energy_pj=("final_branch_fuel_pj", "sum"),
        _weighted_mileage=("_weighted_mileage", "sum"),
        _first_mileage=("adjusted_mileage_km_per_year", "first"),
        _first_efficiency=("adjusted_efficiency_km_per_gj", "first"),
        leap_branch_path=("_tech_path", "first"),
    ).reset_index()

    out["adjusted_mileage_km_per_year"] = np.where(
        out["adjusted_stock"] > 0,
        out["_weighted_mileage"] / out["adjusted_stock"],
        out["_first_mileage"],
    )
    energy_per_vehicle = np.where(
        out["adjusted_stock"] > 0,
        out["final_technology_energy_pj"] / out["adjusted_stock"],
        np.nan,
    )
    derived_efficiency = np.where(
        energy_per_vehicle > 0,
        out["adjusted_mileage_km_per_year"] / energy_per_vehicle / 1_000_000,
        np.nan,
    )
    # Fall back to the LEAP-provided efficiency when energy-based derivation is
    # impossible (e.g. zero-stock technologies like FCEV with no base-year energy).
    out["adjusted_efficiency_km_per_gj"] = np.where(
        pd.isna(derived_efficiency),
        out["_first_efficiency"],
        derived_efficiency,
    )

    if "base_year" in df.columns:
        base_years = grouped["base_year"].first().reset_index(name="base_year")
        out = out.merge(base_years, on=group_keys, how="left")

    return out.drop(columns=["_weighted_mileage", "_first_mileage", "_first_efficiency"])


def _technology_path(branch_path: str) -> str:
    parts = str(branch_path).rsplit("\\", 1)
    return parts[0] if len(parts) > 1 else str(branch_path)
