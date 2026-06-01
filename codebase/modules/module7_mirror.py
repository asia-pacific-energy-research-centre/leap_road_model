"""
Module 7 - Optional Python mirror and post-LEAP validation.

Two roles:
1. QA: check that LEAP results match the intended road model logic.
2. Continuity: preserve a working Python version that could become standalone.

The first implementation does NOT read researcher-edited LEAP assumptions
back into Python. That is a later enhancement.

Outputs:
    T13_mirror_outputs: technology-level stock, vehicle-km, and energy.
    T13_mirror_fuel_outputs: fuel-level energy after applying Device Shares.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from diagnostics.module_charts import write_module7_charts
from schemas.validation import validate_table

log = logging.getLogger(__name__)

_PRIMARY_FUEL_BY_DRIVE = {
    "BEV": "Electricity",
    "FCEV": "Hydrogen",
    "PHEV": "Electricity",
}

_DIMENSION_COLUMNS = [
    "economy",
    "scenario",
    "transport_type",
    "vehicle_type",
    "drive_type",
    "size",
]


def run_module7_mirror(
    sales_turnover: pd.DataFrame,
    reconciliation_scalars: pd.DataFrame,
    device_shares: pd.DataFrame,
    projection_years: list[int] | range | None = None,
    mileage_adjustment_variables: pd.DataFrame | None = None,
    efficiency_adjustment_variables: pd.DataFrame | None = None,
    scrappage_by_year: pd.DataFrame | Mapping[str, Mapping[int, float]] | None = None,
    diagnostics_dir: str | None = None,
) -> dict[str, pd.DataFrame]:
    """
    Run the Python mirror of the LEAP road stock/activity/energy calculation.

    Args:
        sales_turnover: T6_sales_turnover DataFrame from Module 4.
        reconciliation_scalars: T9_reconciliation_scalars DataFrame from Module 6.
        device_shares: T10_device_shares DataFrame from Module 6.
        projection_years: Optional year filter. If omitted, all T6 years are used.
        mileage_adjustment_variables: Optional DataFrame with mileage
            adjustment factors by year. Value column can be 'value',
            'adjustment_factor', or 'mileage_adjustment'.
        efficiency_adjustment_variables: Optional DataFrame with efficiency
            adjustment factors by year. Value column can be 'value',
            'adjustment_factor', or 'efficiency_adjustment'.
        scrappage_by_year: Optional explicit scrappage. Supports either a
            DataFrame with year/dimensions/value or a dict
            {vehicle_type: {year: count}}.
        diagnostics_dir: Optional directory root for Module 7 PNG diagnostic
            charts. When provided, charts are written to
            diagnostics_dir/module7/.

    Returns:
        Dict with:
            T13: technology-level mirror outputs.
            T13_fuel: fuel-level mirror energy outputs.
    """
    years = _resolve_projection_years(sales_turnover, projection_years)
    base_assumptions = build_base_technology_assumptions(reconciliation_scalars)

    technology_outputs = calculate_mirror_technology_outputs(
        sales_turnover=sales_turnover,
        base_assumptions=base_assumptions,
        projection_years=years,
        mileage_adjustment_variables=mileage_adjustment_variables,
        efficiency_adjustment_variables=efficiency_adjustment_variables,
        scrappage_by_year=scrappage_by_year,
    )
    fuel_outputs = calculate_mirror_fuel_outputs(technology_outputs, device_shares)

    errors = validate_table(technology_outputs, "T13_mirror_outputs")
    for err in errors:
        log.warning("Validation: %s", err)

    outputs = {"T13": technology_outputs, "T13_fuel": fuel_outputs}
    if diagnostics_dir is not None:
        write_module7_charts(outputs, diagnostics_dir)

    return outputs


def build_base_technology_assumptions(reconciliation_scalars: pd.DataFrame) -> pd.DataFrame:
    """
    Build one base assumption row per technology branch from T9.

    T9 is fuel-level. Stock, mileage, and efficiency are technology-level
    assumptions repeated across fuels, so this keeps one preferred fuel row
    per technology branch and strips the fuel segment from the LEAP path.
    """
    required = {
        "drive_type",
        "leap_branch_path",
        "adjusted_mileage_km_per_year",
        "adjusted_efficiency_km_per_gj",
    }
    missing = sorted(required - set(reconciliation_scalars.columns))
    if missing:
        raise KeyError(f"Missing columns in reconciliation_scalars: {missing}")

    df = reconciliation_scalars.copy()
    group_keys = [c for c in _DIMENSION_COLUMNS if c in df.columns]
    if not group_keys:
        raise ValueError("reconciliation_scalars must contain model dimension columns.")

    df["_tech_path"] = df["leap_branch_path"].apply(_technology_path)
    df["_primary_sort"] = df.apply(_primary_fuel_sort_key, axis=1)
    df = (
        df.sort_values("_primary_sort")
        .drop_duplicates(subset=group_keys)
        .reset_index(drop=True)
    )

    rename = {
        "adjusted_stock": "base_stock",
        "adjusted_mileage_km_per_year": "base_mileage_km_per_year",
        "adjusted_efficiency_km_per_gj": "base_efficiency_km_per_gj",
        "_tech_path": "leap_branch_path",
    }
    keep = group_keys + [
        "adjusted_stock",
        "adjusted_mileage_km_per_year",
        "adjusted_efficiency_km_per_gj",
        "_tech_path",
    ]
    keep = [c for c in keep if c in df.columns]

    out = df[keep].rename(columns=rename)
    return out.drop(columns=["_primary_sort"], errors="ignore")


def calculate_mirror_technology_outputs(
    sales_turnover: pd.DataFrame,
    base_assumptions: pd.DataFrame,
    projection_years: list[int],
    mileage_adjustment_variables: pd.DataFrame | None = None,
    efficiency_adjustment_variables: pd.DataFrame | None = None,
    scrappage_by_year: pd.DataFrame | Mapping[str, Mapping[int, float]] | None = None,
) -> pd.DataFrame:
    """
    Calculate technology-level mirror stocks, vehicle-km, and energy.

    Internal units:
        mileage: km / vehicle / year
        efficiency: km / GJ
        vehicle_km: km / year
        energy: PJ
    """
    if "year" not in sales_turnover.columns:
        raise KeyError("sales_turnover must contain 'year'.")

    t6 = sales_turnover.copy()
    t6 = t6[t6["year"].astype(int).isin(set(projection_years))].copy()

    join_keys = _common_dimension_columns(t6, base_assumptions)
    if not join_keys:
        raise ValueError("sales_turnover and base_assumptions do not share dimension columns.")

    merged = t6.merge(base_assumptions, on=join_keys, how="left")
    missing_base = merged["base_mileage_km_per_year"].isna().sum()
    if missing_base:
        log.warning("%d Module 7 rows have no base mileage/efficiency assumption", missing_base)

    explicit_scrappage = _coerce_scrappage(scrappage_by_year, merged)
    stock = _calculate_mirror_stock(merged, explicit_scrappage)

    merged["mirror_stock"] = stock.clip(lower=0.0)
    merged["mileage_adjustment"] = _lookup_adjustment(
        merged,
        mileage_adjustment_variables,
        value_columns=["mileage_adjustment", "adjustment_factor", "value"],
        default=1.0,
    )
    merged["efficiency_adjustment"] = _lookup_adjustment(
        merged,
        efficiency_adjustment_variables,
        value_columns=["efficiency_adjustment", "adjustment_factor", "value"],
        default=1.0,
    )

    merged["mirror_mileage_km_per_year"] = (
        pd.to_numeric(merged["base_mileage_km_per_year"], errors="coerce")
        * merged["mileage_adjustment"]
    )
    merged["mirror_efficiency_km_per_gj"] = (
        pd.to_numeric(merged["base_efficiency_km_per_gj"], errors="coerce")
        * merged["efficiency_adjustment"]
    )
    merged["mirror_vehicle_km"] = merged["mirror_stock"] * merged["mirror_mileage_km_per_year"]
    merged["mirror_energy_pj"] = np.where(
        merged["mirror_efficiency_km_per_gj"] > 0,
        merged["mirror_vehicle_km"] / merged["mirror_efficiency_km_per_gj"] / 1_000_000,
        np.nan,
    )

    for col in [
        "leap_stock",
        "leap_vehicle_km",
        "leap_energy_pj",
        "stock_difference",
        "energy_difference_pj",
    ]:
        merged[col] = pd.NA

    keep = [
        "economy",
        "scenario",
        "year",
        "transport_type",
        "vehicle_type",
        "drive_type",
        "size",
        "leap_branch_path",
        "mirror_stock",
        "mirror_mileage_km_per_year",
        "mirror_vehicle_km",
        "mirror_efficiency_km_per_gj",
        "mirror_energy_pj",
        "mileage_adjustment",
        "efficiency_adjustment",
        "leap_stock",
        "leap_vehicle_km",
        "leap_energy_pj",
        "stock_difference",
        "energy_difference_pj",
    ]
    keep = [c for c in keep if c in merged.columns]
    return merged[keep].reset_index(drop=True)


def calculate_mirror_fuel_outputs(
    technology_outputs: pd.DataFrame,
    device_shares: pd.DataFrame,
) -> pd.DataFrame:
    """
    Split technology-level mirror energy to fuels using T10 Device Shares.
    """
    if "device_share" not in device_shares.columns:
        raise KeyError("device_shares must contain 'device_share'.")

    share_cols = [
        c
        for c in _DIMENSION_COLUMNS + ["fuel", "leap_branch_path", "device_share"]
        if c in device_shares.columns
    ]
    shares = device_shares[share_cols].copy()
    shares = shares.rename(columns={"leap_branch_path": "fuel_leap_branch_path"})

    join_keys = _common_dimension_columns(technology_outputs, shares)
    merged = technology_outputs.merge(shares, on=join_keys, how="left")
    merged["device_share"] = pd.to_numeric(merged["device_share"], errors="coerce").fillna(0.0)
    merged["mirror_fuel_energy_pj"] = merged["mirror_energy_pj"] * merged["device_share"]

    keep = [
        "economy",
        "scenario",
        "year",
        "transport_type",
        "vehicle_type",
        "drive_type",
        "size",
        "fuel",
        "fuel_leap_branch_path",
        "mirror_stock",
        "mirror_vehicle_km",
        "mirror_energy_pj",
        "device_share",
        "mirror_fuel_energy_pj",
    ]
    keep = [c for c in keep if c in merged.columns]
    return merged[keep].reset_index(drop=True)


def compare_with_leap(
    mirror_outputs: pd.DataFrame,
    leap_extracted_outputs: pd.DataFrame | None = None,
    *,
    stock_variable: str = "Stock",
    activity_variable: str = "Activity Level",
    energy_variable: str = "Final Energy Intensity",
) -> pd.DataFrame:
    """
    Compare Python mirror results with extracted tidy LEAP results.

    Args:
        mirror_outputs: T13 DataFrame from run_module7_mirror().
        leap_extracted_outputs: Tidy LEAP output with columns
            [scenario, year, leap_branch_path, variable, value].
        stock_variable: LEAP variable name to use for stock comparison.
        activity_variable: LEAP variable name to use for activity comparison.
        energy_variable: LEAP variable name to use for energy comparison.

    Returns:
        T13 DataFrame with LEAP comparison columns populated where available.
    """
    if leap_extracted_outputs is None or leap_extracted_outputs.empty:
        return mirror_outputs.copy()

    required = {"scenario", "year", "leap_branch_path", "variable", "value"}
    missing = sorted(required - set(leap_extracted_outputs.columns))
    if missing:
        raise KeyError(f"Missing columns in leap_extracted_outputs: {missing}")

    value_map = {
        stock_variable: "leap_stock",
        activity_variable: "leap_vehicle_km",
        energy_variable: "leap_energy_pj",
    }
    leap = leap_extracted_outputs[
        leap_extracted_outputs["variable"].isin(value_map.keys())
    ].copy()
    if leap.empty:
        return mirror_outputs.copy()

    leap["variable"] = leap["variable"].map(value_map)
    index_cols = ["scenario", "year", "leap_branch_path"]
    if "economy" in leap.columns and "economy" in mirror_outputs.columns:
        index_cols.insert(0, "economy")

    leap_wide = (
        leap.pivot_table(index=index_cols, columns="variable", values="value", aggfunc="first")
        .reset_index()
    )
    leap_wide.columns.name = None

    out = mirror_outputs.drop(
        columns=[
            "leap_stock",
            "leap_vehicle_km",
            "leap_energy_pj",
            "stock_difference",
            "energy_difference_pj",
        ],
        errors="ignore",
    ).merge(leap_wide, on=index_cols, how="left")

    out["stock_difference"] = (
        out["mirror_stock"] - pd.to_numeric(out.get("leap_stock"), errors="coerce")
    )
    out["energy_difference_pj"] = (
        out["mirror_energy_pj"] - pd.to_numeric(out.get("leap_energy_pj"), errors="coerce")
    )
    return out.reset_index(drop=True)


def _resolve_projection_years(
    sales_turnover: pd.DataFrame,
    projection_years: list[int] | range | None,
) -> list[int]:
    if projection_years is not None:
        return [int(y) for y in projection_years]
    if "year" not in sales_turnover.columns:
        raise KeyError("sales_turnover must contain 'year'.")
    return sorted(
        pd.to_numeric(sales_turnover["year"], errors="coerce")
        .dropna()
        .astype(int)
        .unique()
        .tolist()
    )


def _technology_path(branch_path: str) -> str:
    parts = str(branch_path).rsplit("\\", 1)
    return parts[0] if len(parts) > 1 else str(branch_path)


def _primary_fuel_sort_key(row: pd.Series) -> int:
    primary = _PRIMARY_FUEL_BY_DRIVE.get(str(row.get("drive_type", "")))
    if primary is None:
        return 0
    return 0 if row.get("fuel") == primary else 1


def _common_dimension_columns(left: pd.DataFrame, right: pd.DataFrame) -> list[str]:
    return [c for c in _DIMENSION_COLUMNS if c in left.columns and c in right.columns]


def _calculate_mirror_stock(df: pd.DataFrame, explicit_scrappage: pd.Series) -> pd.Series:
    if {"surviving_stock", "new_sales"}.issubset(df.columns):
        additional = _numeric_column_or_default(df, "additional_retirements", 0.0)
        return (
            pd.to_numeric(df["surviving_stock"], errors="coerce").fillna(0.0)
            + pd.to_numeric(df["new_sales"], errors="coerce").fillna(0.0)
            - additional
            - explicit_scrappage
        )

    if "stock" in df.columns:
        return pd.to_numeric(df["stock"], errors="coerce").fillna(0.0) - explicit_scrappage

    if "target_stock" in df.columns:
        return pd.to_numeric(df["target_stock"], errors="coerce").fillna(0.0) - explicit_scrappage

    raise KeyError(
        "sales_turnover must contain stock, target_stock, or surviving_stock/new_sales columns."
    )


def _coerce_scrappage(
    scrappage_by_year: pd.DataFrame | Mapping[str, Mapping[int, float]] | None,
    base_df: pd.DataFrame,
) -> pd.Series:
    base = _numeric_column_or_default(base_df, "scrappage_for_leap", 0.0)

    if scrappage_by_year is None:
        return base.astype(float)

    if isinstance(scrappage_by_year, pd.DataFrame):
        if scrappage_by_year.empty:
            return base.astype(float)
        value_col = _first_present(scrappage_by_year, ["scrappage", "scrappage_for_leap", "value"])
        if value_col is None:
            raise KeyError("scrappage DataFrame must contain scrappage, scrappage_for_leap, or value.")
        join_cols = ["year"] + _common_dimension_columns(base_df, scrappage_by_year)
        lookup = scrappage_by_year[join_cols + [value_col]].rename(
            columns={value_col: "_explicit_scrappage"}
        )
        merged = base_df.reset_index().merge(lookup, on=join_cols, how="left").set_index("index")
        extra = pd.to_numeric(merged["_explicit_scrappage"], errors="coerce").fillna(0.0)
        return (base + extra.reindex(base.index).fillna(0.0)).astype(float)

    rows: list[dict[str, Any]] = []
    for vehicle_type, by_year in scrappage_by_year.items():
        for year, value in by_year.items():
            rows.append({
                "vehicle_type": str(vehicle_type),
                "year": int(year),
                "_explicit_scrappage": float(value),
            })
    if not rows:
        return base.astype(float)

    lookup = pd.DataFrame(rows)
    merged = base_df.reset_index().merge(lookup, on=["vehicle_type", "year"], how="left").set_index("index")
    extra = pd.to_numeric(merged["_explicit_scrappage"], errors="coerce").fillna(0.0)
    return (base + extra.reindex(base.index).fillna(0.0)).astype(float)


def _lookup_adjustment(
    base_df: pd.DataFrame,
    adjustment_df: pd.DataFrame | None,
    *,
    value_columns: list[str],
    default: float,
) -> pd.Series:
    if adjustment_df is None or adjustment_df.empty:
        return pd.Series(float(default), index=base_df.index, dtype=float)

    value_col = _first_present(adjustment_df, value_columns)
    if value_col is None:
        raise KeyError(f"Adjustment DataFrame must contain one of: {value_columns}")

    join_cols = ["year"] + _common_dimension_columns(base_df, adjustment_df)
    if "year" not in adjustment_df.columns:
        join_cols = _common_dimension_columns(base_df, adjustment_df)

    if not join_cols:
        raise ValueError("Adjustment DataFrame must share at least one join dimension or year.")

    lookup = adjustment_df[join_cols + [value_col]].copy()
    lookup = lookup.rename(columns={value_col: "_adjustment"})
    lookup = lookup.drop_duplicates(subset=join_cols, keep="last")

    merged = base_df.reset_index().merge(lookup, on=join_cols, how="left").set_index("index")
    return (
        pd.to_numeric(merged["_adjustment"], errors="coerce")
        .fillna(float(default))
        .reindex(base_df.index)
        .astype(float)
    )


def _numeric_column_or_default(df: pd.DataFrame, column: str, default: float) -> pd.Series:
    if column not in df.columns:
        return pd.Series(float(default), index=df.index, dtype=float)
    return pd.to_numeric(df[column], errors="coerce").fillna(float(default)).astype(float)


def _first_present(df: pd.DataFrame, columns: list[str]) -> str | None:
    for col in columns:
        if col in df.columns:
            return col
    return None
