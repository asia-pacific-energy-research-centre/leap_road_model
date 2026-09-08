"""
Module 5 — Vehicle sales share preparation.

Produces:
  T7_sales_shares  — base-year sales shares by vehicle type, drive, and size.
  T7f_future_shares — full base-year→end-year sales share trajectories,
      derived by scaling provided future shares to be consistent with the
      new base year.

Input: future_sales_shares — a tidy DataFrame with columns
    [economy, scenario, year, vehicle_type, drive_type, size, sales_share]
    covering years after the base year (e.g. 2023–2060). Typically loaded
    from the road_model_inputs_interface LEAP-format output via
    parse_leap_format_inputs() in road_workflow.py.
    Missing intermediate years are filled by linear interpolation between
    the provided year points.

Scaling method (shape-preserve + ICE-as-residual):
  1. For each non-ICE drive (BEV, PHEV, FCEV):
       - Pin the starting value to the new base-year share.
       - Pin the ending value to the provided terminal-year share.
       - Interpolate in between following the shape of the provided
         trajectory (not a straight line — the S-curve is preserved).
     Formula per year t:
       weight(t) = (provided(t) - anchor) / (terminal - anchor)
       scaled(t) = new_base + weight(t) × (terminal - new_base)
  2. ICE share = 1 − sum(non-ICE) at each year.
  3. If ICE goes negative at any year, fall back to linear interpolation
     between new base and terminal for all drives, then renormalise.
  4. Special cases:
       - Drive has anchor=0 and terminal=0 but new_base>0: hold flat.
       - Drive has anchor==terminal (flat trajectory): hold at new_base.
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

from schemas.validation import validate_table

log = logging.getLogger(__name__)

# Non-ICE drives (scaling targets)
_NON_ICE = {"HEV", "BEV", "PHEV", "EREV", "FCEV"}

# Drive type colours for charts
_DRIVE_COLOURS = {
    "ICE":  "#888888",
    "HEV":  "#607D8B",
    "BEV":  "#2196F3",
    "PHEV": "#9C27B0",
    "EREV": "#673AB7",
    "FCEV": "#4CAF50",
}

# Projection horizon
_END_YEAR = 2060


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def run_module5(
    base_year_branches: pd.DataFrame,
    future_sales_shares: pd.DataFrame | None = None,
    economy: str = "",
    scenarios: list[str] | None = None,
    economy_aliases: list[str] | None = None,
    ev_sales_data: pd.DataFrame | None = None,
    researcher_sales_shares: pd.DataFrame | None = None,
    base_year: int = 2022,
    charts_dir: str | Path | None = None,
    diagnostics_dir: str | Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Run Module 5: base-year sales shares + scaled future trajectories.

    Args:
        base_year_branches: T4_base_year_branches from Module 2.
        future_sales_shares: Optional tidy DataFrame with columns
            [economy, scenario, year, vehicle_type, drive_type, size, sales_share]
            covering years after the base year (e.g. 2023–2060). Produced by
            parse_leap_format_inputs() in road_workflow.py from the
            road_model_inputs_interface LEAP-format output. When None, no
            future scaling is applied and T7f mirrors the base-year shares.
        economy: Economy code e.g. '12_NZ'. Used for filtering and chart titles.
        scenarios: Scenarios to process. Defaults to ['Reference', 'Target'].
        economy_aliases: Optional economy aliases accepted in future sales data
            for filtering (e.g. long region names like "United States").
        ev_sales_data: Optional observed EV sales share DataFrame.
            Columns: [economy, scenario, vehicle_type, ev_sales_share, source].
        researcher_sales_shares: Optional researcher-provided shares
            (full override). Columns: [economy, scenario, vehicle_type,
            drive_type, sales_share].
        charts_dir: If provided, write diagnostic charts here.
        diagnostics_dir: Optional shared diagnostics root. If charts_dir is
            not provided, charts are written to diagnostics_dir/module5/.

    Returns:
        (T7_base_year, T7f_future_shares)
    """
    scenarios = scenarios or ["Target"]

    base_year = int(base_year)
    if base_year > _END_YEAR:
        raise ValueError(f"Module 5 base year {base_year} exceeds projection end year {_END_YEAR}.")

    # 1. Prepare future shares — filter/fill from provided tidy DataFrame
    provided_shares = _prepare_future_shares(
        future_sales_shares,
        economy,
        scenarios,
        economy_aliases=economy_aliases,
        base_year=base_year,
    )

    # 2. Compute base-year shares from stock proportions + EV data
    base_shares = _compute_base_year_shares(
        base_year_branches, ev_sales_data, economy, scenarios, base_year=base_year,
    )

    # 3. Apply researcher overrides to base year if provided
    if researcher_sales_shares is not None:
        base_shares = _apply_researcher_overrides(
            base_shares, researcher_sales_shares, base_year=base_year,
        )

    # 4. Scale future trajectories
    future_shares, scaling_flags = _scale_future_shares(
        base_shares, provided_shares, base_year=base_year,
    )

    # 5. Log flags
    flagged = scaling_flags[scaling_flags["fallback_used"]] if not scaling_flags.empty else pd.DataFrame()
    if not flagged.empty:
        log.warning(
            "%s: %d economy×vehicle×scenario combination(s) switched to linear "
            "interpolation because the shape-preserving method produced a negative ICE "
            "share (non-ICE targets exceed 100%%). Each affected combination linearly "
            "interpolates all drive-type shares from base year to their target-year "
            "values instead:\n%s",
            economy, len(flagged),
            flagged[["economy", "scenario", "vehicle_type"]].to_string(index=False),
        )

    # 6. Validate base-year output
    errors = validate_table(base_shares, "T7_sales_shares")
    for err in errors:
        log.warning("T7 validation: %s", err)

    if charts_dir is None and diagnostics_dir is not None:
        charts_dir = Path(diagnostics_dir) / "module5"

    # 7. Charts
    if charts_dir is not None:
        _write_charts(
            base_shares, future_shares, provided_shares, scaling_flags,
            economy, charts_dir, base_year=base_year,
        )

    return base_shares, future_shares


# ---------------------------------------------------------------------------
# Step 1: prepare future shares from provided tidy DataFrame
# ---------------------------------------------------------------------------

def _prepare_future_shares(
    future_sales_shares: pd.DataFrame | None,
    economy: str,
    scenarios: list[str],
    economy_aliases: list[str] | None = None,
    base_year: int = 2022,
) -> pd.DataFrame:
    """
    Filter and fill the provided future sales shares DataFrame.

    Expects columns: economy, scenario, year, vehicle_type, drive_type, optional
    size, sales_share. Retains size-labelled technology rows, then fills
    missing intermediate years by linear interpolation between provided points.

    Returns a DataFrame with those same columns covering every integer year
    from the first provided year to _END_YEAR, or an empty DataFrame when
    no data is provided.
    """
    if future_sales_shares is None or future_sales_shares.empty:
        return pd.DataFrame()

    df = future_sales_shares.copy()

    scenario_lookup = _build_requested_scenario_lookup(scenarios)
    requested_scenarios = set(scenario_lookup.keys())

    # Filter to the requested economy and scenarios
    if economy and "economy" in df.columns:
        accepted_economies = {
            _normalise_key(economy),
            *{
                _normalise_key(alias)
                for alias in (economy_aliases or [])
                if isinstance(alias, str) and alias.strip()
            },
        }
        econ_norm = df["economy"].map(_normalise_key)
        df = df[econ_norm.isin(accepted_economies)].copy()
        # Keep output economy label consistent with workflow economy code.
        df["economy"] = economy
    if "scenario" in df.columns:
        mapped = df["scenario"].map(_normalise_scenario_label)
        df = df[mapped.isin(requested_scenarios)].copy()
        # Relabel to the requested scenario token so downstream joins remain exact.
        df["scenario"] = mapped[mapped.isin(requested_scenarios)].map(scenario_lookup)

    if df.empty:
        log.warning("No future sales share data found for economy=%s scenarios=%s", economy, scenarios)
        return pd.DataFrame()

    df = df[df["year"] > base_year].copy()
    if df.empty:
        log.warning("future_sales_shares contains no years after base year %d", base_year)
        return pd.DataFrame()

    # Preserve size-labelled technologies. Sales shares are still normalised
    # across the whole vehicle type, so heavy and medium truck rows jointly sum
    # to one rather than each size independently summing to one.
    group_cols = ["economy", "scenario", "year", "vehicle_type", "drive_type", "size"]
    group_cols = [c for c in group_cols if c in df.columns]
    df = df.groupby(group_cols, as_index=False)["sales_share"].sum()

    # Normalise within each (economy, scenario, year, vehicle_type) so shares sum to 1
    totals = df.groupby(["economy", "scenario", "year", "vehicle_type"])["sales_share"].transform("sum")
    mask = totals > 0
    df.loc[mask, "sales_share"] = df.loc[mask, "sales_share"] / totals[mask]

    # Fill missing years via linear interpolation between provided points
    df = _fill_missing_years(df, _END_YEAR)

    return df


def _fill_missing_years(df: pd.DataFrame, end_year: int) -> pd.DataFrame:
    """
    For each (economy, scenario, vehicle_type, drive_type, size) group, linearly
    interpolate sales_share for any integer year between the first provided
    year and end_year that is not already present in the data.
    """
    group_cols = ["economy", "scenario", "vehicle_type", "drive_type", "size"]
    group_cols = [c for c in group_cols if c in df.columns]

    filled_parts: list[pd.DataFrame] = []
    for keys, grp in df.groupby(group_cols):
        grp = grp.set_index("year")["sales_share"].sort_index()
        first_year = int(grp.index.min())
        all_years = range(first_year, end_year + 1)
        grp = grp.reindex(all_years).interpolate(method="index").ffill().bfill()
        part = grp.reset_index().rename(columns={"index": "year"})
        for col, val in zip(group_cols, keys if isinstance(keys, tuple) else (keys,)):
            part[col] = val
        filled_parts.append(part)

    if not filled_parts:
        return df

    return pd.concat(filled_parts, ignore_index=True)


# ---------------------------------------------------------------------------
# Step 2: base-year shares
# ---------------------------------------------------------------------------

def _compute_base_year_shares(
    base_year_branches: pd.DataFrame,
    ev_sales_data: pd.DataFrame | None,
    economy: str,
    scenarios: list[str],
    *,
    base_year: int = 2022,
) -> pd.DataFrame:
    """
    Compute base-year (2022) sales shares from stock proportions + EV data.

    Logic:
      - EV sales shares come from ev_sales_data if available, else from
        stock proportions as a proxy.
      - Remaining share is allocated to non-EV drives by stock proportion.
      - ICE is always the residual after EVs are set.
    """
    rows = []

    base_df = base_year_branches.copy()
    if "scenario" in base_df.columns:
        base_df["_scenario_norm"] = base_df["scenario"].map(_normalise_scenario_label)

    for scenario in scenarios:
        if "scenario" in base_df.columns:
            scenario_norm = _normalise_scenario_label(scenario)
            sub = base_df[base_df["_scenario_norm"] == scenario_norm]
        else:
            sub = base_df

        stock_group_cols = ["vehicle_type", "drive_type"]
        if "size" in sub.columns:
            stock_group_cols.append("size")
        stock_by_drive = (
            sub.groupby(stock_group_cols, dropna=False)["stock"]
            .sum()
            .reset_index()
        )

        for vt, grp in stock_by_drive.groupby("vehicle_type"):
            total = grp["stock"].sum()
            if total <= 0:
                log.warning("%s %s %s: zero total stock — using equal shares", economy, scenario, vt)
                for _, tech_row in grp.iterrows():
                    rows.append(_share_row(
                        economy, scenario, vt, tech_row["drive_type"],
                        1 / len(grp), "stock_proportion", base_year,
                        size=tech_row.get("size"),
                    ))
                continue

            drive_stocks = grp.groupby("drive_type")["stock"].sum().to_dict()

            # EV shares: from observed data or stock proportions
            ev_share = _resolve_ev_share_for_vehicle_type(
                ev_sales_data, economy, scenario, vt, drive_stocks, total
            )

            # Non-ICE assignments
            bev_share  = ev_share.get("BEV", 0.0)
            phev_share = ev_share.get("PHEV", 0.0)
            fcev_share = ev_share.get("FCEV", 0.0)

            non_ice_total = bev_share + phev_share + fcev_share
            ice_share = max(0.0, 1.0 - non_ice_total)

            flag = "iea_ev" if ev_sales_data is not None else "stock_proportion"
            for drive, share in [
                ("ICE", ice_share), ("BEV", bev_share),
                ("PHEV", phev_share), ("FCEV", fcev_share),
            ]:
                drive_rows = grp[grp["drive_type"].eq(drive)]
                if drive_rows.empty and share > 0:
                    rows.append(_share_row(economy, scenario, vt, drive, share, flag, base_year))
                    continue
                drive_total = float(drive_rows["stock"].sum())
                for _, tech_row in drive_rows.iterrows():
                    size_fraction = float(tech_row["stock"]) / drive_total if drive_total > 0 else 1 / len(drive_rows)
                    rows.append(_share_row(
                        economy, scenario, vt, drive, share * size_fraction, flag, base_year,
                        size=tech_row.get("size"),
                    ))

    base = pd.DataFrame(rows)
    if base.empty:
        return base

    # Renormalise within each vehicle type to ensure exact sum to 1
    base = _renormalise(base, ["economy", "scenario", "vehicle_type"], "sales_share")
    return base


def _resolve_ev_share_for_vehicle_type(
    ev_sales_data: pd.DataFrame | None,
    economy: str,
    scenario: str,
    vehicle_type: str,
    drive_stocks: dict[str, float],
    total_stock: float,
) -> dict[str, float]:
    """Return {drive_type: share} for non-ICE drives."""
    if ev_sales_data is not None:
        # Try to find observed EV share
        mask = (
            (ev_sales_data.get("economy", pd.Series()) == economy)
            & (ev_sales_data.get("scenario", pd.Series()) == scenario)
            & (ev_sales_data.get("vehicle_type", pd.Series()) == vehicle_type)
        )
        obs = ev_sales_data[mask] if not ev_sales_data.empty else pd.DataFrame()
        if not obs.empty and "ev_sales_share" in obs.columns:
            # Allocate total EV share across BEV/PHEV/FCEV by stock proportion
            total_ev_share = obs["ev_sales_share"].iloc[0]
            ev_stocks = {d: drive_stocks.get(d, 0.0) for d in _NON_ICE}
            total_ev_stock = sum(ev_stocks.values())
            if total_ev_stock > 0:
                return {d: total_ev_share * (s / total_ev_stock) for d, s in ev_stocks.items()}
            # All EV stock is zero → assign entirely to BEV
            return {"BEV": total_ev_share, "PHEV": 0.0, "FCEV": 0.0}

    # Fallback: use stock proportions for all drives
    return {d: drive_stocks.get(d, 0.0) / total_stock for d in _NON_ICE}


def _share_row(
    economy: str, scenario: str, vehicle_type: str,
    drive_type: str, sales_share: float, source_flag: str, base_year: int,
    size: str | None = None,
) -> dict:
    row = {
        "economy": economy,
        "scenario": scenario,
        "vehicle_type": vehicle_type,
        "drive_type": drive_type,
        "sales_share": sales_share,
        "ev_sales_share_used": sales_share if drive_type in _NON_ICE else 0.0,
        "source_flag": source_flag,
        "year": base_year,
    }
    if size is not None and not pd.isna(size):
        row["size"] = size
    return row


# ---------------------------------------------------------------------------
# Step 3: researcher overrides
# ---------------------------------------------------------------------------

def _row_key_tuples(df: pd.DataFrame, columns: list[str]) -> pd.Series:
    """Build stable row keys without pandas ``DataFrame.agg`` dtype coercion."""
    values = df.loc[:, columns].astype("string").fillna("")
    return pd.Series(
        list(values.itertuples(index=False, name=None)),
        index=df.index,
        dtype="object",
    )


def _apply_researcher_overrides(
    base_shares: pd.DataFrame,
    researcher_shares: pd.DataFrame,
    *,
    base_year: int = 2022,
) -> pd.DataFrame:
    """Replace or add base-year shares with researcher-provided values."""
    if researcher_shares is None or researcher_shares.empty:
        return base_shares

    key_cols = ["economy", "scenario", "vehicle_type", "drive_type"]
    if "size" in researcher_shares.columns:
        key_cols.append("size")
    keep_cols = key_cols + ["sales_share"]
    if "source_flag" in researcher_shares.columns:
        keep_cols.append("source_flag")
    researcher = researcher_shares[keep_cols].copy()
    researcher = researcher.dropna(subset=["vehicle_type", "drive_type", "sales_share"])
    if researcher.empty:
        return base_shares

    if "source_flag" not in researcher.columns:
        researcher["source_flag"] = "researcher"

    group_cols = ["economy", "scenario", "vehicle_type"]
    provided_totals = researcher.groupby(group_cols)["sales_share"].sum().reset_index(name="_provided_total")
    ice_groups = researcher[researcher["drive_type"].astype(str).str.upper().eq("ICE")][group_cols].drop_duplicates()
    complete_groups = pd.concat(
        [
            provided_totals[provided_totals["_provided_total"].between(0.999, 1.001)][group_cols],
            ice_groups,
        ],
        ignore_index=True,
    ).drop_duplicates()
    complete_keys = set(_row_key_tuples(complete_groups, group_cols))

    all_keys = set(_row_key_tuples(provided_totals, group_cols))
    incomplete_keys = all_keys - complete_keys
    if incomplete_keys:
        incomplete_rows = provided_totals[
            _row_key_tuples(provided_totals, group_cols).isin(incomplete_keys)
        ]
        raise ValueError(
            "Module 1 sales-share override is incomplete for the following "
            "(economy, scenario, vehicle_type) group(s) \u2014 shares don't sum to "
            "~1.0 and no explicit ICE row was provided, so it's ambiguous whether "
            "the remaining share should fall back to stock proportions or is "
            "simply missing from Module 1:\n"
            f"{incomplete_rows.to_string(index=False)}"
        )

    if complete_keys:
        base_keys = _row_key_tuples(base_shares, group_cols)
        base_shares = base_shares[~base_keys.isin(complete_keys)].copy()

    merged = base_shares.merge(
        researcher.rename(
            columns={
                "sales_share": "researcher_share",
                "source_flag": "override_source_flag",
            }
        ),
        on=key_cols, how="left",
    )
    has_override = merged["researcher_share"].notna()
    merged.loc[has_override, "sales_share"] = merged.loc[has_override, "researcher_share"]
    merged.loc[has_override, "source_flag"] = merged.loc[has_override, "override_source_flag"]

    existing_keys = set(_row_key_tuples(merged, key_cols))
    missing = researcher[
        ~_row_key_tuples(researcher, key_cols).isin(existing_keys)
    ].copy()
    if not missing.empty:
        missing["ev_sales_share_used"] = np.where(
            missing["drive_type"].isin(_NON_ICE),
            missing["sales_share"],
            0.0,
        )
        missing["year"] = base_year
        base_columns = merged.drop(columns=["researcher_share", "override_source_flag"]).columns
        merged = pd.concat(
            [merged.drop(columns=["researcher_share", "override_source_flag"]), missing[base_columns]],
            ignore_index=True,
        )
    else:
        merged = merged.drop(columns=["researcher_share", "override_source_flag"])

    return _renormalise(merged, ["economy", "scenario", "vehicle_type"], "sales_share")


# ---------------------------------------------------------------------------
# Step 4: scale future trajectories
# ---------------------------------------------------------------------------

def _scale_future_shares(
    base_shares: pd.DataFrame,
    future_shares: pd.DataFrame,
    *,
    base_year: int = 2022,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Scale provided future trajectories to match new base-year shares.

    Returns:
        (future_shares_df, scaling_flags_df)

    future_shares_df columns:
        [economy, scenario, year, vehicle_type, drive_type,
         sales_share, scaling_method]

    scaling_flags_df columns:
        [economy, scenario, vehicle_type, fallback_used, min_ice_share]
    """
    if future_shares is None or future_shares.empty or base_shares.empty:
        log.warning(
            "Cannot scale future shares — missing base or future trajectory data; "
            "using flat fallback projection (%d-%d) from base-year shares",
            base_year,
            _END_YEAR,
        )
        if base_shares.empty:
            return pd.DataFrame(), pd.DataFrame()

        flat_rows: list[dict[str, object]] = []
        for _, row in base_shares.iterrows():
            for yr in range(base_year, _END_YEAR + 1):
                flat_row = {
                    "economy": row.get("economy", ""),
                    "scenario": row.get("scenario", ""),
                    "year": yr,
                    "vehicle_type": row.get("vehicle_type", ""),
                    "drive_type": row.get("drive_type", ""),
                    "sales_share": row.get("sales_share", 0.0),
                    "scaling_method": "flat_base_fallback",
                    "drive_method": "flat_base_fallback",
                }
                if "size" in row.index:
                    flat_row["size"] = row["size"]
                flat_rows.append(flat_row)

        return pd.DataFrame(flat_rows), pd.DataFrame()

    model_drives = ["ICE", "HEV", "BEV", "PHEV", "EREV", "FCEV"]
    anchor_year = int(future_shares["year"].min())
    all_years = list(range(anchor_year, _END_YEAR + 1))

    future_rows: list[dict] = []
    flag_rows: list[dict] = []

    for (economy, scenario, vehicle_type), base_grp in base_shares.groupby(
        ["economy", "scenario", "vehicle_type"]
    ):
        future_grp = future_shares[
            (future_shares["economy"] == economy)
            & (future_shares["scenario"] == scenario)
            & (future_shares["vehicle_type"] == vehicle_type)
        ].copy()
        has_size = "size" in base_grp.columns or "size" in future_grp.columns
        if has_size:
            base_grp["size"] = base_grp.get("size", pd.Series(pd.NA, index=base_grp.index)).fillna("")
            future_grp["size"] = future_grp.get("size", pd.Series(pd.NA, index=future_grp.index)).fillna("")

        key_cols = ["drive_type"] + (["size"] if has_size else [])
        technology_keys = list({tuple(row) for row in pd.concat([base_grp[key_cols], future_grp[key_cols]]).itertuples(index=False, name=None)})
        new_base = dict(zip(base_grp[key_cols].itertuples(index=False, name=None), base_grp["sales_share"]))
        anchor_row = future_grp[future_grp["year"] == anchor_year]
        terminal_row = future_grp[future_grp["year"] == _END_YEAR]
        anchor_shares = dict(zip(anchor_row[key_cols].itertuples(index=False, name=None), anchor_row["sales_share"]))
        terminal_shares = dict(zip(terminal_row[key_cols].itertuples(index=False, name=None), terminal_row["sales_share"]))

        future_by_year: dict[int, dict[tuple[str, ...], float]] = {}
        for yr in all_years:
            yr_row = future_grp[future_grp["year"] == yr]
            future_by_year[yr] = dict(zip(yr_row[key_cols].itertuples(index=False, name=None), yr_row["sales_share"]))

        non_ice_keys = [key for key in technology_keys if key[0] in _NON_ICE]
        ice_keys = [key for key in technology_keys if key[0] == "ICE"]
        drive_method: dict[tuple[str, ...], str] = {}
        for key in non_ice_keys:
            anchor = anchor_shares.get(key, 0.0)
            terminal = terminal_shares.get(key, 0.0)
            new_b = new_base.get(key, 0.0)
            if anchor == terminal == 0.0 and new_b > 0.0:
                drive_method[key] = "hold_flat"
            elif abs(terminal - anchor) < 1e-9:
                drive_method[key] = "hold_at_base"
            else:
                drive_method[key] = "shape_preserve"

        year_shares: dict[int, dict[tuple[str, ...], float]] = {}
        for yr in all_years:
            provided = future_by_year[yr]
            scaled: dict[tuple[str, ...], float] = {}
            for key in non_ice_keys:
                anchor = anchor_shares.get(key, 0.0)
                terminal = terminal_shares.get(key, 0.0)
                new_b = new_base.get(key, 0.0)
                if drive_method[key] in {"hold_flat", "hold_at_base"}:
                    scaled[key] = new_b
                else:
                    weight = (provided.get(key, 0.0) - anchor) / (terminal - anchor)
                    scaled[key] = max(0.0, new_b + weight * (terminal - new_b))
            ice_remaining = 1.0 - sum(scaled.values())
            provided_ice_total = sum(provided.get(key, 0.0) for key in ice_keys)
            base_ice_total = sum(new_base.get(key, 0.0) for key in ice_keys)
            for key in ice_keys:
                if provided_ice_total > 0:
                    ice_weight = provided.get(key, 0.0) / provided_ice_total
                elif base_ice_total > 0:
                    ice_weight = new_base.get(key, 0.0) / base_ice_total
                else:
                    ice_weight = 1 / len(ice_keys) if ice_keys else 0.0
                scaled[key] = ice_remaining * ice_weight
            year_shares[yr] = scaled

        min_ice = min(sum(s.get(key, 0.0) for key in ice_keys) for s in year_shares.values())
        fallback_used = min_ice < 0.0
        if fallback_used:
            log.debug("%s %s %s: ICE share goes negative (%.3f) — switching to linear interpolation", economy, scenario, vehicle_type, min_ice)
            year_shares = _linear_interpolate_fallback(new_base, terminal_shares, all_years, base_year=base_year)

        method = "linear_interpolate" if fallback_used else "shape_preserve_ice_residual"
        for yr, shares in year_shares.items():
            for key, share in shares.items():
                row = {
                    "economy": economy,
                    "scenario": scenario,
                    "year": yr,
                    "vehicle_type": vehicle_type,
                    "drive_type": key[0],
                    "sales_share": max(0.0, share),
                    "scaling_method": method,
                    "drive_method": drive_method.get(key, method),
                }
                if has_size:
                    row["size"] = key[1] or pd.NA
                future_rows.append(row)

        new_base_by_drive = _aggregate_technology_shares(new_base)
        terminal_by_drive = _aggregate_technology_shares(terminal_shares)
        methods_by_drive = {
            drive: ",".join(sorted({method for key, method in drive_method.items() if key[0] == drive})) or "n/a"
            for drive in _NON_ICE
        }
        flag_rows.append({
            "economy":          economy,
            "scenario":         scenario,
            "vehicle_type":     vehicle_type,
            "fallback_used":    fallback_used,
            "min_ice_share":    min_ice,
            # New base-year shares (2022)
            "new_base_ICE":     new_base_by_drive.get("ICE",  0.0),
            "new_base_HEV":     new_base_by_drive.get("HEV",  0.0),
            "new_base_BEV":     new_base_by_drive.get("BEV",  0.0),
            "new_base_PHEV":    new_base_by_drive.get("PHEV", 0.0),
            "new_base_EREV":    new_base_by_drive.get("EREV", 0.0),
            "new_base_FCEV":    new_base_by_drive.get("FCEV", 0.0),
            # 9th edition terminal shares (2060)
            "terminal_ICE":     terminal_by_drive.get("ICE",  0.0),
            "terminal_HEV":     terminal_by_drive.get("HEV",  0.0),
            "terminal_BEV":     terminal_by_drive.get("BEV",  0.0),
            "terminal_PHEV":    terminal_by_drive.get("PHEV", 0.0),
            "terminal_EREV":    terminal_by_drive.get("EREV", 0.0),
            "terminal_FCEV":    terminal_by_drive.get("FCEV", 0.0),
            # Per-drive method applied
            "method_HEV":       methods_by_drive["HEV"],
            "method_BEV":       methods_by_drive["BEV"],
            "method_PHEV":      methods_by_drive["PHEV"],
            "method_EREV":      methods_by_drive["EREV"],
            "method_FCEV":      methods_by_drive["FCEV"],
        })

    future_df = pd.DataFrame(future_rows)
    flags_df = pd.DataFrame(flag_rows)

    # Add base year row at the front (from Module 5 base shares)
    base_future = base_shares.copy()
    base_future["scaling_method"] = "module5_base"
    base_future["scale_factor"] = 1.0
    if not future_df.empty:
        future_df = pd.concat([base_future, future_df], ignore_index=True)

    return future_df, flags_df


def _aggregate_technology_shares(shares: dict[tuple[str, ...], float]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for key, value in shares.items():
        totals[key[0]] = totals.get(key[0], 0.0) + value
    return totals


def _linear_interpolate_fallback(
    new_base: dict[tuple[str, ...], float],
    terminal_shares: dict[tuple[str, ...], float],
    all_years: list[int],
    *,
    base_year: int = 2022,
) -> dict[int, dict[tuple[str, ...], float]]:
    """
    Fallback used when shape-preserve method causes ICE to go negative.
    Linearly interpolates every drive between new_base (2022) and the
    9th edition terminal (2060), then renormalises so shares sum to 1.
    """
    if not terminal_shares:
        terminal_shares = new_base.copy()

    span = _END_YEAR - base_year
    technology_keys = set(new_base) | set(terminal_shares)
    year_shares: dict[int, dict[tuple[str, ...], float]] = {}
    for yr in all_years:
        t = (yr - base_year) / span if span > 0 else 1.0
        shares: dict[tuple[str, ...], float] = {}
        for key in technology_keys:
            b = new_base.get(key, 0.0)
            e = terminal_shares.get(key, 0.0)
            shares[key] = max(0.0, b + t * (e - b))
        total = sum(shares.values())
        if total > 0:
            shares = {key: value / total for key, value in shares.items()}
        year_shares[yr] = shares

    return year_shares


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def _write_charts(
    base_shares: pd.DataFrame,
    future_shares: pd.DataFrame,
    provided_shares: pd.DataFrame,
    scaling_flags: pd.DataFrame,
    economy: str,
    charts_dir: str | Path,
    *,
    base_year: int = 2022,
) -> None:
    """Write one chart file per vehicle type showing provided vs scaled trajectories."""
    charts_dir = Path(charts_dir)
    charts_dir.mkdir(parents=True, exist_ok=True)

    vehicle_types = base_shares["vehicle_type"].unique()
    scenarios = base_shares["scenario"].unique()

    for vehicle_type in vehicle_types:
        for scenario in scenarios:
            _plot_vehicle_type(
                base_shares, future_shares, provided_shares, scaling_flags,
                economy, vehicle_type, scenario, charts_dir, base_year=base_year,
            )

    log.info("Wrote Module 5 charts to %s", charts_dir)


def _plot_vehicle_type(
    base_shares: pd.DataFrame,
    future_shares: pd.DataFrame,
    provided_shares: pd.DataFrame,
    scaling_flags: pd.DataFrame,
    economy: str,
    vehicle_type: str,
    scenario: str,
    charts_dir: Path,
    *,
    base_year: int = 2022,
) -> None:
    """
    3-panel chart:
      Left  — Provided future trajectory stacked area (unscaled input)
      Middle — Base-year stacked bar (Module 5 estimate)
      Right  — Scaled trajectory stacked area (what goes into LEAP)
    Plus a plain-English text block below all panels.
    """
    drives = ["ICE", "HEV", "BEV", "PHEV", "EREV", "FCEV"]
    anchor_year = base_year + 1
    future_years = list(range(anchor_year, _END_YEAR + 1))
    all_years = list(range(base_year, _END_YEAR + 1))

    # Pull flag row for this vehicle type + scenario
    flag_row = pd.DataFrame()
    if not scaling_flags.empty and "scenario" in scaling_flags.columns:
        flag_row = scaling_flags[
            (scaling_flags["scenario"] == scenario)
            & (scaling_flags["vehicle_type"] == vehicle_type)
        ]
    fallback_used = (not flag_row.empty) and flag_row["fallback_used"].any()

    # ------------------------------------------------------------------ layout
    fig = plt.figure(figsize=(18, 6.5))
    fig.suptitle(
        f"{economy}  ·  {vehicle_type}  ·  {scenario}  —  Vehicle Sales Shares",
        fontsize=13, fontweight="bold", y=0.98,
    )

    # 3 chart columns + 1 text row below
    outer_gs = fig.add_gridspec(
        2, 1,
        height_ratios=[4, 1.4],
        hspace=0.55,
    )
    chart_gs = outer_gs[0].subgridspec(1, 3, width_ratios=[3, 1, 3], wspace=0.12)

    ax_left   = fig.add_subplot(chart_gs[0])
    ax_mid    = fig.add_subplot(chart_gs[1], sharey=ax_left)
    ax_right  = fig.add_subplot(chart_gs[2], sharey=ax_left)
    ax_text   = fig.add_subplot(outer_gs[1])
    ax_text.axis("off")

    # --------------------------------------------------------- left: provided trajectory
    ax_left.set_title("Provided trajectory (input)", fontsize=10, pad=6)
    provided_sub = provided_shares[
        (provided_shares["scenario"] == scenario)
        & (provided_shares["vehicle_type"] == vehicle_type)
    ] if not provided_shares.empty else pd.DataFrame()

    left_data: dict[str, list[float]] = {d: [] for d in drives}
    for yr in future_years:
        row = provided_sub[provided_sub["year"] == yr] if not provided_sub.empty else pd.DataFrame()
        provided_dict = row.groupby("drive_type")["sales_share"].sum().to_dict() if not row.empty else {}
        for d in drives:
            left_data[d].append(provided_dict.get(d, 0.0))

    _draw_stacked_area(ax_left, future_years, left_data, drives)
    ax_left.set_xlim(anchor_year, _END_YEAR)

    # ----------------------------------------------------- middle: base-year bar
    ax_mid.set_title(f"{base_year}\nBase Year", fontsize=10, pad=6)
    base_sub = base_shares[
        (base_shares["scenario"] == scenario)
        & (base_shares["vehicle_type"] == vehicle_type)
    ] if not base_shares.empty else pd.DataFrame()

    base_dict = base_sub.groupby("drive_type")["sales_share"].sum().to_dict() \
        if not base_sub.empty else {}

    bottom = 0.0
    for d in drives:
        val = base_dict.get(d, 0.0)
        ax_mid.bar(
            0, val, bottom=bottom,
            color=_DRIVE_COLOURS.get(d, "#cccccc"),
            alpha=0.85, width=0.7,
        )
        if val >= 0.04:
            ax_mid.text(
                0, bottom + val / 2,
                f"{val:.0%}",
                ha="center", va="center",
                fontsize=8, color="white", fontweight="bold",
            )
        bottom += val

    ax_mid.set_xlim(-0.6, 0.6)
    ax_mid.set_xticks([])
    ax_mid.tick_params(labelleft=False)

    # -------------------------------------------------- right: scaled trajectory
    sf_labels = []
    if not flag_row.empty:
        for d in ("BEV", "PHEV", "FCEV"):
            base_col     = f"new_base_{d}"
            terminal_col = f"terminal_{d}"
            method_col   = f"method_{d}"
            if base_col in flag_row.columns and terminal_col in flag_row.columns:
                base_val     = flag_row[base_col].iloc[0]
                terminal_val = flag_row[terminal_col].iloc[0]
                method_val   = flag_row[method_col].iloc[0] if method_col in flag_row.columns else ""
                if method_val == "hold_flat":
                    sf_labels.append(f"{d}: {base_val:.0%} (held flat — absent from 9th ed)")
                elif base_val > 0 or terminal_val > 0:
                    sf_labels.append(f"{d}: {base_val:.0%} → {terminal_val:.0%}")

    method_note = "  (fallback: linear interpolation)" if fallback_used else ""
    right_title = f"Scaled Trajectory ({base_year}–{_END_YEAR}){method_note}"
    ax_right.set_title(right_title, fontsize=10, pad=6)

    new_sub = future_shares[
        (future_shares["scenario"] == scenario)
        & (future_shares["vehicle_type"] == vehicle_type)
    ] if not future_shares.empty else pd.DataFrame()

    right_data: dict[str, list[float]] = {d: [] for d in drives}
    for yr in all_years:
        row = new_sub[new_sub["year"] == yr] if not new_sub.empty else pd.DataFrame()
        row_dict = row.groupby("drive_type")["sales_share"].sum().to_dict() if not row.empty else {}
        for d in drives:
            right_data[d].append(row_dict.get(d, 0.0))

    _draw_stacked_area(ax_right, all_years, right_data, drives)
    ax_right.set_xlim(base_year, _END_YEAR)

    # Scale factor annotation on right panel
    if sf_labels:
        ax_right.text(
            0.98, 0.98, "\n".join(sf_labels),
            transform=ax_right.transAxes,
            ha="right", va="top", fontsize=8,
            color="#333333",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.7, edgecolor="#cccccc"),
        )

    # --------------------------------------------------- shared axis formatting
    pct_fmt = plt.FuncFormatter(lambda x, _: f"{x:.0%}")
    for ax in (ax_left, ax_mid, ax_right):
        ax.set_ylim(0, 1.05)
        ax.yaxis.set_major_formatter(pct_fmt)
        ax.grid(axis="y", alpha=0.3)

    for ax in (ax_left, ax_right):
        ax.set_xlabel("Year", fontsize=9)

    ax_left.set_ylabel("Sales share", fontsize=9)
    ax_mid.set_ylabel("")

    # Vertical divider lines between panels (cosmetic)
    for ax in (ax_left, ax_mid):
        ax.spines["right"].set_visible(False)

    # Shared legend below charts
    handles = [
        plt.Rectangle((0, 0), 1, 1, color=_DRIVE_COLOURS.get(d, "#cccccc"), label=d)
        for d in drives
    ]
    fig.legend(
        handles=handles, loc="upper center",
        ncol=4, bbox_to_anchor=(0.5, 0.48),
        fontsize=9, framealpha=0.7,
    )

    # ------------------------------------------------------ explanatory text
    base_source = (
        base_sub["source_flag"].iloc[0]
        if not base_sub.empty and "source_flag" in base_sub.columns
        else "stock proportions"
    )
    source_readable = {
        "iea_ev":           "IEA EV sales data",
        "stock_proportion": "stock-proportion proxy (no observed EV sales data)",
        "researcher":       "researcher-provided override",
    }.get(base_source, base_source)

    sf_text = (
        "  ".join(sf_labels) if sf_labels
        else "No EV trajectory adjustment needed."
    )

    fallback_note = (
        "\n[FALLBACK METHOD used] Shape-preserving interpolation caused ICE share to go negative. "
        f"Switched to straight-line interpolation for all drives from the new {base_year} base year to the 9th edition 2060 terminal shares, then renormalised."
        if fallback_used else ""
    )

    explanation = (
        f"HOW TO READ THIS CHART   |   Vehicle type: {vehicle_type}   |   Scenario: {scenario}\n\n"
        f"LEFT PANEL — The provided future trajectory for how {vehicle_type} sales will be split by drive type "
        f"(ICE, BEV, PHEV, FCEV) up to {_END_YEAR}. "
        f"These are the input shares, normalised within the {vehicle_type} bucket.\n\n"
        f"MIDDLE BAR — The {base_year} base-year sales share estimate for {vehicle_type}. "
        f"Source: {source_readable}. "
        f"This is the starting point that the new model needs to match.\n\n"
        f"RIGHT PANEL — The final trajectory that will be loaded into LEAP. Each EV drive type starts at the new {base_year} base-year value "
        f"and ends at the same {_END_YEAR} terminal share as the provided trajectory, following the same shape in between. "
        f"ICE takes whatever share is left over. "
        f"Drive trajectories: {sf_text}{fallback_note}"
    )

    ax_text.text(
        0.0, 1.0, explanation,
        transform=ax_text.transAxes,
        ha="left", va="top",
        fontsize=8.5,
        color="#222222",
        wrap=True,
        family="monospace",
    )

    # Save
    fname = charts_dir / f"module5_{economy}_{vehicle_type}_{scenario}.png"
    plt.savefig(fname, dpi=120, bbox_inches="tight")
    plt.close(fig)
    log.debug("Saved chart: %s", fname)


def _draw_stacked_area(
    ax: plt.Axes,
    years: list[int],
    data: dict[str, list[float]],
    drives: list[str],
) -> None:
    """Draw a stacked area chart on ax."""
    stacks = []
    labels = []
    colors = []
    for d in drives:
        vals = [v if not (isinstance(v, float) and np.isnan(v)) else 0.0 for v in data[d]]
        stacks.append(vals)
        labels.append(d)
        colors.append(_DRIVE_COLOURS.get(d, "#cccccc"))

    ax.stackplot(years, stacks, labels=labels, colors=colors, alpha=0.85)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _renormalise(
    df: pd.DataFrame,
    group_cols: list[str],
    share_col: str,
) -> pd.DataFrame:
    """Renormalise share_col to sum to 1 within each group."""
    totals = df.groupby(group_cols)[share_col].transform("sum")
    mask = totals > 0
    df = df.copy()
    df.loc[mask, share_col] = df.loc[mask, share_col] / totals[mask]
    return df


def _normalise_key(value: object) -> str:
    """Normalise free-text keys (economy/scenario aliases) for comparisons."""
    return str(value or "").strip().lower()


def _normalise_scenario_label(value: object) -> str:
    """Map common scenario aliases to canonical internal labels."""
    raw = _normalise_key(value)
    if raw in {"target", "tgt", "t"}:
        return "target"
    if raw in {"reference", "ref", "r", "baseline", "base"}:
        return "reference"
    return raw


def _build_requested_scenario_lookup(scenarios: list[str]) -> dict[str, str]:
    """
    Build canonical-scenario -> requested-label mapping.

    Example:
      scenarios=["TGT"] gives {"target": "TGT"}
      scenarios=["Target"] gives {"target": "Target"}
    """
    lookup: dict[str, str] = {}
    for scenario in scenarios:
        canonical = _normalise_scenario_label(scenario)
        lookup.setdefault(canonical, scenario)
    return lookup
