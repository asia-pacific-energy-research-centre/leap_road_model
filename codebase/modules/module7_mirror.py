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
from modules.reconciliation_aggregation import build_reconciled_technology_assumptions
from schemas.validation import validate_table

log = logging.getLogger(__name__)

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
    sales_shares: pd.DataFrame | None = None,
    projection_years: list[int] | range | None = None,
    mileage_adjustment_variables: pd.DataFrame | None = None,
    efficiency_adjustment_variables: pd.DataFrame | None = None,
    scrappage_by_year: pd.DataFrame | Mapping[str, Mapping[int, float]] | None = None,
    diagnostics_dir: str | None = None,
    base_year_branches: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """
    Run the Python mirror of the LEAP road stock/activity/energy calculation.

    Args:
        sales_turnover: T6_sales_turnover DataFrame from Module 4.
        reconciliation_scalars: T9_reconciliation_scalars DataFrame from Module 6.
        device_shares: T10_device_shares DataFrame from Module 6.
        sales_shares: Optional T7f sales shares. Used to split vehicle-level
            turnover into technology-level mirror stocks when T6 has no
            drive_type column.
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
        base_year_branches: Optional T4 base-year branch table from Module 2.
            Used as a fallback source of mileage_km_per_year and
            efficiency_km_per_gj for branches present in sales_turnover
            (via future sales shares) but absent from reconciliation_scalars
            because they had no ESTO base-year energy data.

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
        sales_shares=sales_shares,
        mileage_adjustment_variables=mileage_adjustment_variables,
        efficiency_adjustment_variables=efficiency_adjustment_variables,
        scrappage_by_year=scrappage_by_year,
        base_year_branches=base_year_branches,
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
    rename = {
        "adjusted_stock": "base_stock",
        "adjusted_mileage_km_per_year": "base_mileage_km_per_year",
        "adjusted_efficiency_km_per_gj": "base_efficiency_km_per_gj",
        "final_technology_energy_pj": "base_energy_pj",
    }
    df = build_reconciled_technology_assumptions(reconciliation_scalars)
    group_keys = [c for c in _DIMENSION_COLUMNS if c in df.columns]
    keep = group_keys + [
        "adjusted_stock",
        "adjusted_mileage_km_per_year",
        "adjusted_efficiency_km_per_gj",
        "final_technology_energy_pj",
        "leap_branch_path",
    ]
    keep = [c for c in keep if c in df.columns]

    out = df[keep].rename(columns=rename)
    return out


def _fill_missing_assumptions_from_t4(
    merged: pd.DataFrame,
    base_year_branches: pd.DataFrame,
) -> pd.DataFrame:
    """
    Fill NaN base_mileage_km_per_year / base_efficiency_km_per_gj from T4.

    T9 only has reconciled assumptions for branches with ESTO energy data.
    Branches present in sales shares (e.g. future-tech BEV, FCEV) but absent
    from ESTO get NaN after the T9 merge. T4 holds Module 1's raw assumptions
    for every branch including zero-stock ones, so we fill from there.
    """
    t4 = base_year_branches.copy()
    rename = {}
    if "mileage_km_per_year" in t4.columns:
        rename["mileage_km_per_year"] = "_t4_mileage"
    if "efficiency_km_per_gj" in t4.columns:
        rename["efficiency_km_per_gj"] = "_t4_efficiency"
    if not rename:
        return merged

    t4 = t4.rename(columns=rename)
    fill_cols = list(rename.values())
    dim_cols = _common_dimension_columns(merged, t4)
    if not dim_cols:
        return merged

    t4_lookup = (
        t4[dim_cols + fill_cols]
        .dropna(subset=fill_cols, how="all")
        .drop_duplicates(subset=dim_cols, keep="first")
    )
    out = merged.reset_index().merge(t4_lookup, on=dim_cols, how="left").set_index("index")
    out.index.name = None

    if "_t4_mileage" in fill_cols:
        t4_mileage = pd.to_numeric(out["_t4_mileage"], errors="coerce")
        needs_mileage = (
            merged["base_mileage_km_per_year"].isna()
            | (pd.to_numeric(merged["base_mileage_km_per_year"], errors="coerce").fillna(0.0) <= 0)
        )
        out.loc[needs_mileage, "base_mileage_km_per_year"] = t4_mileage[needs_mileage]

    if "_t4_efficiency" in fill_cols:
        t4_efficiency = pd.to_numeric(out["_t4_efficiency"], errors="coerce")
        needs_efficiency = (
            merged["base_efficiency_km_per_gj"].isna()
            | (pd.to_numeric(merged["base_efficiency_km_per_gj"], errors="coerce").fillna(0.0) <= 0)
        )
        out.loc[needs_efficiency, "base_efficiency_km_per_gj"] = t4_efficiency[needs_efficiency]

    return out.drop(columns=[c for c in fill_cols if c in out.columns])


def _validate_assumptions_for_nonzero_sales(merged: pd.DataFrame) -> None:
    """
    Raise if any branch has new_sales > 0 but no base-year mileage or efficiency.

    This catches the case where a researcher enables sales shares for a fuel/drive
    combination that had no ESTO data in the base year and therefore has no
    mileage or efficiency assumption — which would silently produce NaN energy.
    """
    new_sales = pd.to_numeric(merged.get("new_sales", pd.Series(0.0, index=merged.index)), errors="coerce").fillna(0.0)
    missing_mileage = merged["base_mileage_km_per_year"].isna() | (
        pd.to_numeric(merged["base_mileage_km_per_year"], errors="coerce").fillna(0.0) <= 0
    )
    missing_efficiency = merged["base_efficiency_km_per_gj"].isna() | (
        pd.to_numeric(merged["base_efficiency_km_per_gj"], errors="coerce").fillna(0.0) <= 0
    )
    problem_mask = (new_sales > 0) & (missing_mileage | missing_efficiency)

    if not problem_mask.any():
        return

    label_cols = [c for c in ["economy", "scenario", "vehicle_type", "drive_type", "size"] if c in merged.columns]
    bad_rows = merged.loc[problem_mask, label_cols + ["base_mileage_km_per_year", "base_efficiency_km_per_gj"]].copy()
    bad_rows["missing"] = bad_rows.apply(_missing_assumption_label, axis=1)
    bad = (
        bad_rows[label_cols + ["missing"]]
        .drop_duplicates()
        .groupby(label_cols, dropna=False, as_index=False)["missing"]
        .agg(_combine_missing_labels)
        .sort_values(label_cols)
    )

    branch_lines = "\n".join(
        f"  {row.to_dict()}" for _, row in bad.iterrows()
    )
    raise ValueError(
        f"Sales shares are set > 0 for {len(bad)} branch(es) that have no base-year "
        f"mileage or efficiency assumption. These branches had no ESTO data in the base "
        f"year, so the model cannot compute energy for projected vehicles. Either:\n"
        f"  (a) set mileage and efficiency values for these branches in the researcher "
        f"input parameters, or\n"
        f"  (b) remove the sales shares for these branches.\n\n"
        f"Affected branches:\n{branch_lines}"
    )


def _missing_assumption_label(row: pd.Series) -> str:
    """Return which base assumption is missing on one merged Module 7 row."""
    missing_mileage = (
        pd.isna(row.get("base_mileage_km_per_year"))
        or float(row.get("base_mileage_km_per_year") or 0) <= 0
    )
    missing_efficiency = (
        pd.isna(row.get("base_efficiency_km_per_gj"))
        or float(row.get("base_efficiency_km_per_gj") or 0) <= 0
    )
    if missing_mileage and missing_efficiency:
        return "mileage and efficiency"
    if missing_mileage:
        return "mileage"
    return "efficiency"


def _combine_missing_labels(labels: pd.Series) -> str:
    """Combine per-year missing labels for one branch into one readable label."""
    unique = set(labels.dropna().astype(str))
    if "mileage and efficiency" in unique or {"mileage", "efficiency"}.issubset(unique):
        return "mileage and efficiency"
    if "mileage" in unique:
        return "mileage"
    if "efficiency" in unique:
        return "efficiency"
    return ""


def calculate_mirror_technology_outputs(
    sales_turnover: pd.DataFrame,
    base_assumptions: pd.DataFrame,
    projection_years: list[int],
    sales_shares: pd.DataFrame | None = None,
    mileage_adjustment_variables: pd.DataFrame | None = None,
    efficiency_adjustment_variables: pd.DataFrame | None = None,
    scrappage_by_year: pd.DataFrame | Mapping[str, Mapping[int, float]] | None = None,
    base_year_branches: pd.DataFrame | None = None,
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

    if "drive_type" not in t6.columns and sales_shares is not None and not sales_shares.empty:
        t6 = _split_vehicle_turnover_to_technology(
            sales_turnover=t6,
            base_assumptions=base_assumptions,
            sales_shares=sales_shares,
        )

    join_keys = _common_dimension_columns(t6, base_assumptions)
    if not join_keys:
        raise ValueError("sales_turnover and base_assumptions do not share dimension columns.")

    merged = t6.merge(base_assumptions, on=join_keys, how="left")

    if base_year_branches is not None and not base_year_branches.empty:
        merged = _fill_missing_assumptions_from_t4(merged, base_year_branches)

    _validate_assumptions_for_nonzero_sales(merged)

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


def _split_vehicle_turnover_to_technology(
    sales_turnover: pd.DataFrame,
    base_assumptions: pd.DataFrame,
    sales_shares: pd.DataFrame,
) -> pd.DataFrame:
    """
    Split vehicle-level stock turnover to technology branches.

    Module 4 produces vehicle-type totals. Module 7 needs technology-level
    rows, otherwise each drive receives the full vehicle stock and drive-share
    charts become artificially even. This keeps the reconciled base-year
    technology stocks from T9 and allocates future sales by T7f sales shares.
    """
    if "base_stock" not in base_assumptions.columns:
        return sales_turnover.copy()

    vt_keys = [
        c for c in ["economy", "scenario", "transport_type", "vehicle_type"]
        if c in sales_turnover.columns and c in base_assumptions.columns
    ]
    if "year" not in sales_turnover.columns or not vt_keys:
        return sales_turnover.copy()

    tech_cols = [c for c in _DIMENSION_COLUMNS if c in base_assumptions.columns]
    tech = base_assumptions[tech_cols + ["base_stock"]].copy()
    tech["base_stock"] = pd.to_numeric(tech["base_stock"], errors="coerce").fillna(0.0)
    if tech.empty:
        return sales_turnover.copy()

    share_cols = [
        c for c in ["economy", "scenario", "transport_type", "vehicle_type", "drive_type", "year"]
        if c in sales_shares.columns
    ]
    share_lookup = sales_shares[share_cols + ["sales_share"]].copy()
    share_lookup["year"] = pd.to_numeric(share_lookup["year"], errors="coerce").astype("Int64")
    share_lookup["sales_share"] = pd.to_numeric(share_lookup["sales_share"], errors="coerce").fillna(0.0)

    out_rows: list[dict[str, Any]] = []
    for vt_key, vt_turnover in sales_turnover.groupby(vt_keys, dropna=False):
        if not isinstance(vt_key, tuple):
            vt_key = (vt_key,)
        key_filter = pd.Series(True, index=tech.index)
        for col, value in zip(vt_keys, vt_key):
            key_filter &= tech[col].eq(value)
        tech_rows = tech[key_filter].copy()
        if tech_rows.empty:
            out_rows.extend(vt_turnover.to_dict("records"))
            continue

        tech_rows["_base_drive_total"] = tech_rows.groupby("drive_type")["base_stock"].transform("sum")
        tech_rows["_size_share"] = np.where(
            tech_rows["_base_drive_total"] > 0,
            tech_rows["base_stock"] / tech_rows["_base_drive_total"],
            1.0 / tech_rows.groupby("drive_type")["drive_type"].transform("count"),
        )

        current_stock = tech_rows["base_stock"].copy()
        first_year = int(pd.to_numeric(vt_turnover["year"], errors="coerce").min())
        for _, total_row in vt_turnover.sort_values("year").iterrows():
            year = int(total_row["year"])
            row_total_stock = float(pd.to_numeric(pd.Series([total_row.get("stock", np.nan)]), errors="coerce").iloc[0])
            new_sales = float(pd.to_numeric(pd.Series([total_row.get("new_sales", 0.0)]), errors="coerce").fillna(0.0).iloc[0])
            retirements = float(pd.to_numeric(
                pd.Series([total_row.get("total_retirements", total_row.get("natural_retirements", 0.0))]),
                errors="coerce",
            ).fillna(0.0).iloc[0])

            if year != first_year:
                previous_total = current_stock.sum()
                retirement_share = current_stock / previous_total if previous_total > 0 else 0.0
                current_stock = (current_stock - retirements * retirement_share).clip(lower=0.0)

                sales_by_drive = _sales_share_for_technology_rows(
                    sales_shares=share_lookup,
                    tech_rows=tech_rows,
                    vt_keys=vt_keys,
                    vt_key=vt_key,
                    year=year,
                )
                current_stock = current_stock + new_sales * sales_by_drive * tech_rows["_size_share"]

                current_total = current_stock.sum()
                if row_total_stock > 0 and current_total > 0:
                    current_stock = current_stock * (row_total_stock / current_total)

            for idx, tech_row in tech_rows.iterrows():
                out = total_row.to_dict()
                for col in tech_cols:
                    out[col] = tech_row[col]
                out["stock"] = float(current_stock.loc[idx])
                out_rows.append(out)

    return pd.DataFrame(out_rows).reset_index(drop=True)


def _sales_share_for_technology_rows(
    sales_shares: pd.DataFrame,
    tech_rows: pd.DataFrame,
    vt_keys: list[str],
    vt_key: tuple[Any, ...],
    year: int,
) -> pd.Series:
    """Return one drive-level sales share per technology row."""
    mask = sales_shares["year"].eq(year)
    for col, value in zip(vt_keys, vt_key):
        if col in sales_shares.columns:
            mask &= sales_shares[col].eq(value)
    year_shares = sales_shares.loc[mask]

    if year_shares.empty:
        base_drive = tech_rows.groupby("drive_type")["base_stock"].sum()
        total = base_drive.sum()
        share_map = (base_drive / total).to_dict() if total > 0 else {}
    else:
        share_map = (
            year_shares.groupby("drive_type")["sales_share"]
            .sum()
            .to_dict()
        )

    return tech_rows["drive_type"].map(share_map).fillna(0.0)


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
