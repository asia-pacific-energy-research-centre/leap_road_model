"""
Plotly-based interactive HTML dashboard for road model QA verification.

Generates one self-contained HTML page per module plus an index page.  Each
page shows all verification charts as embedded Plotly figures, mirroring the
static matplotlib PNGs produced by module_charts.py but as interactive charts.

Usage (called automatically by road_workflow.py when enable_visualisations=True)::

    from diagnostics.plotly_dashboard import write_module_pages
    write_module_pages(workflow_outputs, dashboard_dir, economy="12_NZ")

Or call per-module functions directly::

    figs = module2_figures(t4)   # returns list[(title, go.Figure)]
"""

from __future__ import annotations

import json
import math
import os
from html import escape
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    import plotly.io as pio

    _PLOTLY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PLOTLY_AVAILABLE = False


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_PROFILE_VARIABLES = {"Survival Rate", "Vintage Profile Share"}


def _collapse_age_series(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse survival/vintage profile age-series rows into one representative row.

    Profile data has one row per age step (Age 0…Age 30) and all rows share the
    same issue or comment, so showing 31 identical lines is not useful. Grouped
    rows are collapsed to a single entry with the age range noted in Branch Path.
    """
    if df.empty:
        return df

    import re as _re
    var_col = next((c for c in ["Variable", "variable"] if c in df.columns), None)
    path_col = next((c for c in ["Branch Path", "leap_branch_path"] if c in df.columns), None)
    if var_col is None:
        return df

    is_profile = df[var_col].isin(_PROFILE_VARIABLES)
    non_profile = df[~is_profile].copy()
    profile = df[is_profile].copy()
    if profile.empty:
        return non_profile

    if path_col:
        profile["_base"] = profile[path_col].apply(
            lambda p: _re.sub(r"\\?Age\s+\d+", "", str(p)).strip("\\").strip()
        )
        group_cols = [c for c in ["_base", var_col, "review_reason"] if c in profile.columns]
    else:
        profile["_base"] = ""
        group_cols = [c for c in [var_col, "review_reason"] if c in profile.columns]

    collapsed: list[pd.Series] = []
    for _key, grp in profile.groupby(group_cols, sort=False, dropna=False):
        rep = grp.iloc[0].copy()
        n = len(grp)
        if path_col and n > 1:
            rep[path_col] = rep.get("_base", "") + f"  (ages 0–{n - 1}, {n} steps)"
        collapsed.append(rep)

    collapsed_df = pd.DataFrame(collapsed).drop(columns=["_base"], errors="ignore")
    return pd.concat([non_profile, collapsed_df], ignore_index=True)


def _annual_survival_to_cumulative_probability(annual_survival: pd.Series) -> pd.Series:
    """Convert annual survival probabilities p(age) to cumulative survival S(age)."""
    annual = pd.Series(annual_survival, dtype=float).sort_index().clip(0.0, 1.0)
    if annual.empty:
        return annual

    cumulative_values: list[float] = []
    current = 1.0
    for idx, age in enumerate(annual.index):
        if idx > 0:
            previous_age = annual.index[idx - 1]
            current *= float(annual.loc[previous_age])
        cumulative_values.append(current)
    return pd.Series(cumulative_values, index=annual.index, dtype=float)


_COLOURS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
]
_TEMPLATE = "plotly_white"

_COLORS_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "colors.json"


def _load_colors_config() -> dict[str, dict[str, str]]:
    """Load color config from config/colors.json, returning empty dicts on failure."""
    try:
        with open(_COLORS_CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return {
            k: v for k, v in data.items()
            if isinstance(v, dict) and not k.startswith("_")
        }
    except Exception:
        return {}


_COLORS_CONFIG = _load_colors_config()

# Fuel colours — from config/colors.json (aligned with leap_dashboard product_color_legend).
_FUEL_COLOURS: dict[str, str] = _COLORS_CONFIG.get("fuel_colors", {
    "Motor gasoline": "#842482",
    "Gas and diesel oil": "#711D55",
    "Petroleum products": "#842482",
    "Hydrogen": "#F67AA3",
    "Hydrogen-based fuels": "#D46FA0",
    "Electricity": "#FFD757",
    "Biogasoline": "#F09417",
    "Biodiesel": "#304A1E",
    "Biojet kerosene": "#9ACD32",
    "Natural gas": "#0070C0",
    "Gas": "#0070C0",
    "LNG": "#A20042",
    "LPG": "#000099",
    "CNG": "#FFCC00",
    "Biogas": "#00FE73",
    "Efuel": "#7030A0",
    "E-fuel": "#7030A0",
    "Coal": "#0D0D0D",
    "Nuclear": "#C6188C",
    "Hydro": "#B0D6F0",
    "Solar": "#FFD700",
    "Wind": "#000099",
    "Biomass": "#2E8B57",
    "Others": "#8A8A8A",
})

# Drive-type colours — from config/colors.json (master_config.xlsx colors tab).
_DRIVE_COLOURS: dict[str, str] = _COLORS_CONFIG.get("drive_type_colors", {
    "ICE": "#632B8D",
    "BEV": "#00B9CC",
    "PHEV": "#B8D0ED",
    "FCEV": "#D000D0",
    "HEV": "#62BAB4",
    "CNG": "#FFCC00",
    "LPG": "#000099",
})

# Vehicle-type colours — from config/colors.json (master_config.xlsx colors tab).
_VEHICLE_TYPE_COLOURS: dict[str, str] = _COLORS_CONFIG.get("vehicle_type_colors", {
    "Light private vehicle": "#1F77B4",
    "Light commercial vehicle": "#98DF8A",
    "Bus": "#40928C",
    "Truck": "#CF8DC2",
    "truck": "#CF8DC2",
    "Motorcycle": "#8E72BF",
    "motorcycle": "#8E72BF",
})

# Transport-mode colours — from config/colors.json (master_config.xlsx colors tab).
_TRANSPORT_MODE_COLOURS: dict[str, str] = _COLORS_CONFIG.get("transport_mode_colors", {
    "Road": "#40928C",
    "Rail": "#43506D",
    "Aviation": "#ABD3EF",
    "Marine": "#70A0DC",
    "Pipeline": "#621674",
    "Transport": "#0E71C2",
    "Non-specified": "#8A8A8A",
})


def _fuel_colour(fuel: str, idx: int) -> str:
    return _FUEL_COLOURS.get(str(fuel), _COLOURS[idx % len(_COLOURS)])


def _drive_colour(drive: str, idx: int) -> str:
    return _DRIVE_COLOURS.get(str(drive), _COLOURS[idx % len(_COLOURS)])


_VT_ALIASES: dict[str, str] = {
    "LPV": "Light private vehicle",
    "LPVs": "Light private vehicle",
    "Private car": "Light private vehicle",
    "LCV": "Light commercial vehicle",
    "LCVs": "Light commercial vehicle",
    "Light commercial": "Light commercial vehicle",
    "Buses": "Bus",
    "bus": "Bus",
    "buses": "Bus",
    "Trucks": "Truck",
    "trucks": "Truck",
    "Motorcycles": "Motorcycle",
    "motorcycles": "Motorcycle",
    "Moped": "Motorcycle",
    "moped": "Motorcycle",
    "Motorbike": "Motorcycle",
    "motorbike": "Motorcycle",
}


def _vehicle_type_colour(vt: str, idx: int) -> str:
    normalized = _VT_ALIASES.get(str(vt), str(vt))
    return _VEHICLE_TYPE_COLOURS.get(normalized, _COLOURS[idx % len(_COLOURS)])


def _freight_vehicle_label(vehicle_type: str) -> str:
    """Return a concise modeller-facing label for common freight vehicle types."""
    normalized = _VT_ALIASES.get(str(vehicle_type), str(vehicle_type))
    lowered = normalized.lower()
    if "commercial" in lowered:
        return "LCV"
    if "truck" in lowered:
        return "Truck"
    return normalized


def _transport_mode_colour(mode: str, idx: int) -> str:
    return _TRANSPORT_MODE_COLOURS.get(str(mode), _COLOURS[idx % len(_COLOURS)])


def _can_plot() -> bool:
    return _PLOTLY_AVAILABLE


def _safe_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").dropna()


def _layout(title: str, **kwargs: Any) -> dict[str, Any]:
    return dict(title=title, template=_TEMPLATE, **kwargs)


def _categorical_x_values(fig: Any) -> list[str]:
    """Return string-like x-axis labels used across traces in a figure."""
    labels: list[str] = []
    for trace in getattr(fig, "data", []):
        x = getattr(trace, "x", None)
        if x is None:
            continue
        for value in x:
            if isinstance(value, str) and value:
                labels.append(value)
    return labels


def _has_multiple_panels(fig: Any) -> bool:
    """Heuristic for subplot-style figures that benefit from extra width."""
    layout_json = getattr(fig, "layout", None)
    if layout_json is None:
        return False
    layout_dict = layout_json.to_plotly_json()
    return any(
        key.startswith(("xaxis", "yaxis")) and key not in {"xaxis", "yaxis"}
        for key in layout_dict
    )


def _should_render_wide(fig: Any, explicit_wide: bool = False) -> bool:
    """Decide whether a chart should span the full dashboard width."""
    if explicit_wide or _has_multiple_panels(fig):
        return True

    trace_types = {getattr(trace, "type", "") for trace in getattr(fig, "data", [])}
    if "heatmap" in trace_types:
        return True

    labels = _categorical_x_values(fig)
    if not labels:
        return False

    unique_labels = list(dict.fromkeys(labels))
    max_len = max(len(label) for label in unique_labels)
    has_compound_labels = any(("|" in label) or ("/" in label) for label in unique_labels)

    return (
        len(unique_labels) >= 8
        or max_len >= 16
        or (len(unique_labels) >= 6 and max_len >= 12)
        or has_compound_labels
    )


def _apply_dashboard_layout(fig: Any, wide: bool = False) -> Any:
    """Tune Plotly figures so they fit dashboard cards more gracefully."""
    labels = _categorical_x_values(fig)
    unique_labels = list(dict.fromkeys(labels))
    max_len = max((len(label) for label in unique_labels), default=0)
    needs_label_rotation = len(unique_labels) >= 6 or max_len >= 12
    has_legend = len(getattr(fig, "data", [])) > 1 and any(
        getattr(trace, "name", None) for trace in getattr(fig, "data", [])
    )

    fig.update_layout(
        autosize=True,
        title=None,
        height=460 if wide else 400,
        margin=dict(
            l=64,
            r=24,
            t=36 if has_legend else 20,
            b=92 if needs_label_rotation else 64,
        ),
        legend=(
            dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="left",
                x=0,
            )
            if has_legend else None
        ),
    )

    layout_dict = fig.layout.to_plotly_json()
    for axis_name in [key for key in layout_dict if key.startswith(("xaxis", "yaxis"))]:
        axis_update: dict[str, Any] = {
            "automargin": True,
            "title_standoff": 10,
        }
        if axis_name.startswith("xaxis") and needs_label_rotation:
            axis_update.update({"tickangle": -30, "tickfont": {"size": 10}})
        fig.update_layout(**{axis_name: axis_update})

    return fig


# ---------------------------------------------------------------------------
# Module 1 — base-year inputs
# ---------------------------------------------------------------------------

def _module1_source_category(row: pd.Series) -> str:
    """Map raw Module 1 source metadata into dashboard-friendly categories."""
    source_type = str(row.get("source_type", "") or "").strip().lower()
    source_name = str(row.get("source_name", "") or "").strip().lower()
    input_source = str(row.get("input_source", "") or "").strip().lower()

    if "transport_leap_export" in source_type or "transport_leap_export" in source_name:
        return "Researcher-provided"
    if input_source in {"researcher", "researcher_import", "researcher_provided"}:
        return "Researcher-provided"
    # "provided" is the marker emitted by the static bundle for all values — treat as default.
    # "default" and "default_filled" are explicit default markers.
    # "normalised" is set by the interface frontend when sales shares are normalised to sum to 100.
    if source_type == "default_input_workbook" or input_source in {"default", "default_filled", "provided", "normalised"}:
        return "Default value"
    return "Other model input"


def _module1_major_branch(df: pd.DataFrame) -> pd.Series:
    transport = df.get("transport_type", pd.Series("", index=df.index)).fillna("").astype(str)
    vehicle = df.get("vehicle_type", pd.Series("", index=df.index)).fillna("").astype(str)
    return (transport + " / " + vehicle).str.strip(" /")


def _format_pct(value: float | int | None) -> str:
    if value is None or pd.isna(value) or not np.isfinite(value):
        return ""
    return f"{value:+.1f}%"


def _module1_default_original_table(merged_inputs: pd.DataFrame) -> Any | None:
    """Summarise Module 1 value provenance by broad branch and measure."""
    required = {"transport_type", "vehicle_type", "variable", "value"}
    if not required.issubset(merged_inputs.columns):
        return None

    df = merged_inputs.copy()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value", "variable"])
    if df.empty:
        return None

    df["major_branch"] = _module1_major_branch(df)
    df["source_category"] = df.apply(_module1_source_category, axis=1)

    count_table = (
        df.groupby(["major_branch", "variable", "source_category"]).size()
        .unstack(fill_value=0)
        .reset_index()
    )
    for col in ["Default value", "Researcher-provided", "Other model input"]:
        if col not in count_table.columns:
            count_table[col] = 0

    medians = (
        df.groupby(["major_branch", "variable", "source_category"])["value"].median()
        .unstack()
        .reset_index()
    )
    if {"Default value", "Researcher-provided"}.issubset(medians.columns):
        original = pd.to_numeric(medians["Researcher-provided"], errors="coerce")
        default = pd.to_numeric(medians["Default value"], errors="coerce")
        medians["default_vs_original_median"] = np.where(
            original.ne(0) & original.notna() & default.notna(),
            (default / original - 1.0) * 100.0,
            np.nan,
        )
    else:
        medians["default_vs_original_median"] = np.nan

    table_df = count_table.merge(
        medians[["major_branch", "variable", "default_vs_original_median"]],
        on=["major_branch", "variable"],
        how="left",
    )
    table_df["total_values"] = (
        table_df["Default value"]
        + table_df["Researcher-provided"]
        + table_df["Other model input"]
    )
    table_df = table_df.sort_values(["major_branch", "variable"], key=lambda s: s.astype(str))

    fig = go.Figure(data=[go.Table(
        header=dict(
            values=[
                "Major branch",
                "Measure",
                "Total values",
                "Default values",
                "Researcher-provided",
                "Other inputs",
                "Default vs researcher median",
            ],
            fill_color="#E8EDF7",
            align="left",
        ),
        cells=dict(
            values=[
                table_df["major_branch"].tolist(),
                table_df["variable"].tolist(),
                table_df["total_values"].astype(int).tolist(),
                table_df["Default value"].astype(int).tolist(),
                table_df["Researcher-provided"].astype(int).tolist(),
                table_df["Other model input"].astype(int).tolist(),
                table_df["default_vs_original_median"].map(_format_pct).tolist(),
            ],
            fill_color="white",
            align="left",
            height=24,
        ),
        columnwidth=[2.0, 1.2, 0.9, 0.9, 0.9, 0.8, 1.2],
    )])
    fig.update_layout(**_layout("Module 1 - Default and researcher-provided values by branch/measure"))
    return fig


def _raw_missing_rows_table(raw_df: pd.DataFrame, max_rows: int = 50) -> Any | None:
    """Return a table of raw CSV rows where every year-value column is blank.

    These rows are silently dropped by parse_leap_format_inputs so they would
    otherwise be invisible in the dashboard.
    """
    year_cols = [
        c for c in raw_df.columns
        if isinstance(c, str) and c.strip().isdigit() and len(c.strip()) == 4
    ]
    if not year_cols:
        return None

    missing_mask = raw_df[year_cols].isna().all(axis=1)
    missing = raw_df.loc[missing_mask].copy()
    if missing.empty:
        return None

    missing = _collapse_age_series(missing)
    id_cols = [c for c in ["Branch Path", "Variable", "Scenario", "Region"] if c in missing.columns]
    shown = missing[id_cols + [c for c in year_cols if c in missing.columns]].head(max_rows)

    fig = go.Figure(data=[go.Table(
        header=dict(
            values=id_cols + year_cols,
            fill_color="#E8EDF7",
            align="left",
        ),
        cells=dict(
            values=[shown[col].fillna("").astype(str).tolist() for col in id_cols + year_cols],
            fill_color="white",
            align="left",
            height=24,
        ),
    )])
    fig.update_layout(**_layout("Rows with missing year values (dropped before processing)"))
    return fig


def _missing_rows_table(
    df: pd.DataFrame,
    check_cols: list[str],
    display_cols: list[str],
    max_rows: int = 50,
) -> Any | None:
    """Return a compact table for rows missing required dashboard fields."""
    if df is None or df.empty:
        return None

    available_check_cols = [c for c in check_cols if c in df.columns]
    if not available_check_cols:
        return None

    missing_mask = df[available_check_cols].isna().any(axis=1)
    missing = df.loc[missing_mask].copy()
    if missing.empty:
        return None

    shown_cols = [c for c in display_cols if c in missing.columns]
    shown_cols += [c for c in available_check_cols if c not in shown_cols]
    shown = missing[shown_cols].head(max_rows)

    fig = go.Figure(data=[go.Table(
        header=dict(
            values=shown_cols,
            fill_color="#E8EDF7",
            align="left",
        ),
        cells=dict(
            values=[shown[col].fillna("").astype(str).tolist() for col in shown_cols],
            fill_color="white",
            align="left",
            height=24,
        ),
    )])
    fig.update_layout(**_layout("Rows with missing required values"))
    return fig


def _count_model_variables(raw_df: pd.DataFrame) -> tuple[int, int]:
    """Return (total_vars, provided_vars) counting distinct (branch, variable) slots.

    Profile age-series (Survival Rate, Vintage Profile Share) are collapsed to one
    slot per series so 31 age rows count as 1 variable, not 31.
    """
    import re as _re

    var_col  = "Variable"  if "Variable"  in raw_df.columns else None
    path_col = "Branch Path" if "Branch Path" in raw_df.columns else None
    year_cols = [c for c in raw_df.columns if isinstance(c, str) and c.strip().isdigit() and len(c.strip()) == 4]
    if not var_col or not path_col or not year_cols:
        return 0, 0

    is_profile = raw_df[var_col].isin(_PROFILE_VARIABLES)
    keys = raw_df.apply(
        lambda r: (
            _re.sub(r"\\?Age\s+\d+", "", str(r[path_col])).strip("\\").strip(),
            r[var_col],
        ) if is_profile.loc[r.name] else (r[path_col], r[var_col]),
        axis=1,
    )
    total    = keys.nunique()
    provided = keys[raw_df[year_cols].notna().any(axis=1)].nunique()
    return total, provided


def _count_raw_missing(raw_df: pd.DataFrame) -> tuple[int, int]:
    """Return (raw_count, collapsed_count) for rows where all year columns are blank.

    raw_count is the true row count; collapsed_count is what the table shows after
    profile age-series are merged into one representative row each.
    """
    year_cols = [
        c for c in raw_df.columns
        if isinstance(c, str) and c.strip().isdigit() and len(c.strip()) == 4
    ]
    if not year_cols:
        return 0, 0
    missing = raw_df[raw_df[year_cols].isna().all(axis=1)].copy()
    raw_count = len(missing)
    if raw_count == 0:
        return 0, 0
    collapsed = _collapse_age_series(missing)
    return raw_count, len(collapsed)


def _module1_summary_html(
    merged_inputs: pd.DataFrame,
    raw_df: pd.DataFrame | None = None,
) -> str:
    """Return an HTML summary banner with key input stats for the module 1 page."""
    if merged_inputs is None or merged_inputs.empty:
        return ""

    df = merged_inputs.copy()
    total = len(df)
    if total == 0:
        return ""

    df["_src"] = df.apply(_module1_source_category, axis=1)
    researcher = int((df["_src"] == "Researcher-provided").sum())
    default = int((df["_src"] == "Default value").sum())
    other = int((df["_src"] == "Other model input").sum())

    # Variable counts from raw_df so profiles and scalars are included, with
    # age-series collapsed to 1 slot per series.
    if raw_df is not None:
        total_vars, provided_vars = _count_model_variables(raw_df)
        missing_raw, missing_collapsed = _count_raw_missing(raw_df)
    else:
        total_vars = provided_vars = total  # fall back to merged_inputs row count
        missing_raw = missing_collapsed = 0

    n_comments = 0
    if "review_reason" in df.columns:
        n_comments = int(
            df["review_reason"].fillna("").astype(str).str.strip().ne("").sum()
        )

    def _pct(n: int, base: int) -> str:
        return f"{n / base * 100:.0f}%" if base else "0%"

    researcher_pct = _pct(researcher, total)
    default_pct    = _pct(default, total)
    other_pct      = _pct(other, total)

    researcher_style = "color:#1565c0;font-weight:600" if researcher > 0 else "color:#757575"
    if missing_raw == 0:
        missing_html = '<span style="color:#2e7d32">&#10003; None</span>'
    elif missing_raw == missing_collapsed:
        missing_html = f'<span style="color:#e65100">&#9888; {missing_collapsed} — see table below</span>'
    else:
        missing_html = (
            f'<span style="color:#e65100">&#9888; {missing_collapsed}'
            f' (covering {missing_raw} raw rows incl. profile age steps) — see table below</span>'
        )

    items = [
        f"<li><strong>Variables to fill in:</strong> {total_vars} total &mdash; {provided_vars} provided, {total_vars - provided_vars} missing</li>",
        f"<li><strong>Default values:</strong> {default} ({default_pct})</li>",
        f'<li><strong>Researcher-provided:</strong> <span style="{researcher_style}">{researcher} ({researcher_pct})</span></li>',
        f"<li><strong>Other inputs:</strong> {other} ({other_pct})</li>",
        f"<li><strong>Missing values (dropped from processing):</strong> {missing_html}</li>",
    ]
    if n_comments > 0:
        items.append(
            f'<li><strong>Notes:</strong> {n_comments} row{"s" if n_comments != 1 else ""} with notes — see input data table below</li>'
        )

    return (
        '<div class="intro-card">'
        "<h3>Input overview</h3>"
        f'<ul>{"".join(items)}</ul>'
        "</div>"
    )


def _module1_input_data_table(
    merged_inputs: pd.DataFrame,
    raw_df: pd.DataFrame | None = None,
) -> Any | None:
    """Return a table of all input rows sent to Module 2.

    Uses raw_df when available. Profile age-series rows that share the same
    note are collapsed to a single representative line.
    """
    source = raw_df if raw_df is not None else merged_inputs
    if source is None or source.empty:
        return None

    df = source.copy()
    if "review_reason" in df.columns:
        df["review_reason"] = df["review_reason"].fillna("").astype(str).str.strip()
    else:
        df["review_reason"] = ""

    # Collapse age-series profile rows before displaying.
    df = _collapse_age_series(df)

    if raw_df is not None:
        # Raw LEAP format: Branch Path, Variable, unit, scale, year value, note.
        year_cols = sorted(
            [c for c in df.columns if isinstance(c, str) and c.strip().isdigit()],
            key=int,
        )
        value_col = year_cols[0] if year_cols else None
        col_map: dict[str, str] = {"Branch Path": "Branch", "Variable": "Measure"}
        if value_col:
            col_map[value_col] = f"Value ({value_col})"
        if "unit" in df.columns:
            col_map["unit"] = "Unit"
        if "scale" in df.columns:
            col_map["scale"] = "Scale"
        col_map["review_reason"] = "Note"
        col_widths: dict[str, float] = {
            "Branch Path": 2.2, "Variable": 0.9, "unit": 0.6, "scale": 0.5, "review_reason": 2.5,
        }
        if value_col:
            col_widths[value_col] = 0.7
    else:
        col_map = {
            "transport_type": "Transport",
            "vehicle_type": "Vehicle type",
            "drive_type": "Drive",
            "fuel": "Fuel",
            "variable": "Measure",
            "value": "Value",
            "unit": "Unit",
            "scale": "Scale",
            "review_reason": "Note",
        }
        col_widths = {
            "transport_type": 0.8, "vehicle_type": 1.0, "drive_type": 0.6,
            "fuel": 0.9, "variable": 0.8, "value": 0.6, "unit": 0.6, "scale": 0.5,
            "review_reason": 2.5,
        }

    display_cols = [c for c in col_map if c in df.columns]
    shown = df[display_cols].copy()
    non_text = {"Branch Path", "Variable", "variable", "review_reason", "unit", "scale"}
    for col in display_cols:
        if col not in non_text:
            shown[col] = pd.to_numeric(shown[col], errors="coerce").round(3).astype(str).replace("nan", "")
    shown = shown.fillna("").astype(str)

    fig = go.Figure(data=[go.Table(
        header=dict(values=[col_map[c] for c in display_cols], fill_color="#E8EDF7", align="left"),
        cells=dict(
            values=[shown[c].tolist() for c in display_cols],
            fill_color="white", align="left", height=28,
        ),
        columnwidth=[col_widths.get(c, 1.0) for c in display_cols],
    )])
    fig.update_layout(**_layout("Module 1 — Input data table"))
    return fig


def module1_figures(
    merged_inputs: pd.DataFrame,
    raw_df: pd.DataFrame | None = None,
) -> list[tuple[str, Any]]:
    """Interactive QA figures for Module 1 LEAP-format base-year inputs."""
    if not _can_plot() or merged_inputs is None or merged_inputs.empty:
        return []

    figs: list[tuple[str, Any]] = []

    # Show the provenance detail table only when there are actually researcher-provided
    # or other non-default values — an all-defaults run gains nothing from it.
    df_src = merged_inputs.copy()
    df_src["_src"] = df_src.apply(_module1_source_category, axis=1)
    has_non_default = (df_src["_src"] != "Default value").any()
    if has_non_default:
        source_table = _module1_default_original_table(merged_inputs)
        if source_table is not None:
            figs.append((
                "Default and researcher-provided values by branch/measure",
                source_table,
                True,
                "Counts base-year values by branch and measure. When both default and researcher-provided values exist in a group, the last column compares their medians.",
            ))

    # Missing year values — checked against the raw CSV because parse_leap_format_inputs
    # silently drops rows with blank year cells before they reach merged_inputs.
    # The summary banner already signals "none" when this table is absent.
    if raw_df is not None:
        missing_table = _raw_missing_rows_table(raw_df)
        if missing_table is not None:
            figs.append((
                "Rows with missing year value",
                missing_table,
                True,
                "Rows in the raw input CSV where the year value column is blank. "
                "These were dropped before processing and are not included in any model calculations.",
            ))

    # Input data table — all rows sent to Module 2, with unit, scale and any notes.
    input_data_table = _module1_input_data_table(merged_inputs, raw_df=raw_df)
    if input_data_table is not None:
        figs.append((
            "Input data table",
            input_data_table,
            True,
            "All data inputs sent to the model. Shows the branch, measure, value, unit, scale and any notes.",
        ))

    return figs


# ---------------------------------------------------------------------------
# Module 2 — base-year branches
# ---------------------------------------------------------------------------

def module2_figures(t4: pd.DataFrame) -> list[tuple[str, Any]]:
    """Interactive QA figures for Module 2 base-year branch table (T4)."""
    if not _can_plot() or t4 is None or t4.empty:
        return []

    figs: list[tuple[str, Any]] = []

    spread_fig = _spread_dot_chart(t4, "Spread of stock, mileage and efficiency — base-year input data")
    if spread_fig is not None:
        figs.append((
            "Spread of stock / mileage / efficiency — base-year input data",
            spread_fig,
            True,
            "Based directly on the base-year input data (T4), not on any simulated or reconciled model output. "
            "Each dot is one branch's value, jittered within its category and coloured by category. Categories "
            "are sorted by median value (highest to lowest). Use the dropdown to switch between vehicle type, "
            "drive type, and transport type groupings.",
        ))

    missing_table = _missing_rows_table(
        t4,
        check_cols=[
            "vehicle_type", "drive_type", "fuel",
            "stock", "mileage_km_per_year", "efficiency_km_per_gj",
        ],
        display_cols=[
            "economy", "scenario", "transport_type", "vehicle_type", "size",
            "drive_type", "fuel", "leap_branch_path",
        ],
    )
    if missing_table is not None:
        figs.append((
            "Rows with missing branch values",
            missing_table,
            True,
            "Lists branch rows missing required dimensions or base-year stock, mileage, or efficiency values.",
        ))

    return figs


# ---------------------------------------------------------------------------
# Module 3 — stock targets
# ---------------------------------------------------------------------------

def module3_figures(
    t5: pd.DataFrame,
    population: pd.Series | None = None,
    show_freight_energy_context: bool = False,
    t13: pd.DataFrame | None = None,
    show_passenger_energy_context: bool = False,
    gdp: pd.Series | None = None,
    esto_road_energy_pj: pd.DataFrame | None = None,
) -> list[tuple[str, Any]]:
    """Interactive QA figures for Module 3 stock targets (T5)."""
    if not _can_plot() or t5 is None or t5.empty:
        return []

    figs: list[tuple[str, Any]] = []

    req = {"year", "transport_type", "vehicle_type", "target_stock"}
    if req.issubset(t5.columns):
        fig = make_subplots(rows=1, cols=2, subplot_titles=["Passenger", "Freight"])
        # Build a global vehicle-type index so colours are consistent across both panels,
        # even when the name doesn't match the colour map and the fallback palette is used.
        all_vts = sorted(t5["vehicle_type"].dropna().unique().tolist(), key=str)
        vt_global_idx = {str(vt): i for i, vt in enumerate(all_vts)}
        for col_idx, tt in enumerate(["passenger", "freight"], 1):
            sub = t5[t5["transport_type"] == tt]
            if sub.empty:
                continue
            for vt, grp in sub.groupby("vehicle_type"):
                i = vt_global_idx.get(str(vt), 0)
                series = grp.groupby("year")["target_stock"].sum().sort_index()
                fig.add_trace(
                    go.Scatter(
                        x=series.index.tolist(), y=series.values.tolist(),
                        name=str(vt), mode="lines",
                        line=dict(color=_vehicle_type_colour(str(vt), i)),
                        legendgroup=str(vt), showlegend=True,
                    ),
                    row=1, col=col_idx,
                )
        fig.update_layout(**_layout("Module 3 — Target stock trajectories"))
        figs.append(("Target stock trajectories", fig))

    if {"year", "motorisation_level"}.issubset(t5.columns):
        # motorisation_level is already an economy-level envelope value replicated
        # across passenger vehicle rows in T5, so use mean/first-like aggregation
        # rather than summing across rows.
        sub = t5[(t5.get("transport_type") == "passenger") & t5["motorisation_level"].notna()].copy()
        if not sub.empty:
            line = (sub.groupby("year")["motorisation_level"].mean() * 1000.0).dropna().sort_index()
            sat = (
                (sub.groupby("year")["saturation_level"].mean() * 1000.0).dropna().sort_index()
                if "saturation_level" in sub.columns else pd.Series(dtype=float)
            )
            orig_sat = (
                (sub.groupby("year")["original_saturation_level"].mean() * 1000.0).dropna().sort_index()
                if "original_saturation_level" in sub.columns else pd.Series(dtype=float)
            )
            sat_was_adjusted = (
                bool(sub["saturation_was_adjusted"].fillna(False).any())
                if "saturation_was_adjusted" in sub.columns else False
            )
            fig = go.Figure()
            if not line.empty:
                fig.add_trace(go.Scatter(
                    x=line.index.tolist(), y=line.values.tolist(),
                    name="Projected X-LPV-equivalent vehicles", mode="lines+markers",
                ))
            if not sat.empty:
                fig.add_trace(go.Scatter(
                    x=sat.index.tolist(), y=sat.values.tolist(),
                    name="Saturation level", mode="lines+markers",
                    line=dict(dash="dash"),
                ))
            if sat_was_adjusted and not orig_sat.empty:
                fig.add_trace(go.Scatter(
                    x=orig_sat.index.tolist(), y=orig_sat.values.tolist(),
                    name="Original saturation level (reduced — calibration bounds exceeded)",
                    mode="lines",
                    line=dict(dash="dash", color="#2E7D32"),
                ))
            fig.update_layout(
                **_layout("Module 3 - Passenger X-LPV-equivalent vehicles per 1,000 people"),
                xaxis_title="Year", yaxis_title="X-LPV-equivalent vehicles per 1,000 people",
            )
            caption = (
                "Projected passenger stock converted to X-LPV-equivalent vehicles per 1,000 people, "
                "compared with the saturation level."
            )
            if sat_was_adjusted:
                caption += (
                    ' <span style="color:#e65100;font-weight:500">The original saturation level (green dashed line) was reduced to the achieved '
                    "motorisation level because passenger_saturation_reached=True was set but the "
                    "vehicle weight calibration bounds were exceeded — the fleet cannot be weighted "
                    "up to the original target.</span>"
                )
            figs.append((
                "Passenger X-LPV-equivalent vehicles vs saturation",
                fig,
                caption,
            ))

    if population is not None and not population.empty:
        population_series = pd.to_numeric(population, errors="coerce").dropna().sort_index()
        population_series.index = pd.to_numeric(population_series.index, errors="coerce")
        population_series = population_series[population_series.index.notna()]
        if not population_series.empty:
            population_series.index = population_series.index.astype(int)
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=population_series.index.tolist(),
                y=(population_series / 1_000_000.0).tolist(),
                name="Population",
                mode="lines+markers",
                line=dict(color="#1565C0", width=3),
            ))
            fig.update_layout(
                **_layout("Module 3 - Population"),
                xaxis_title="Year",
                yaxis_title="Population (million people)",
            )
            figs.append((
                "Population",
                fig,
                "Macro population input used by Module 3 when converting ownership into total passenger stock.",
            ))

    weight_cols = {
        "vehicle_type",
        "original_vehicle_equivalent_weight",
        "adjusted_vehicle_equivalent_weight",
        "weight_calibration_applied",
    }
    if weight_cols.issubset(t5.columns):
        extra_cols = [c for c in ["weight_lower_bound", "weight_upper_bound", "weight_calibration_applied"] if c in t5.columns]
        weights_df = (
            t5[t5["transport_type"] == "passenger"]
            [["vehicle_type", "original_vehicle_equivalent_weight", "adjusted_vehicle_equivalent_weight"] + extra_cols]
            .dropna(subset=["vehicle_type"])
            .drop_duplicates("vehicle_type")
        )
        if not weights_df.empty:
            weights_df = weights_df.sort_values("vehicle_type").reset_index(drop=True)
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=weights_df["vehicle_type"].tolist(),
                y=weights_df["original_vehicle_equivalent_weight"].tolist(),
                name="Original X-LPV weight",
                marker_color="#5E6AD2",
            ))
            fig.add_trace(go.Bar(
                x=weights_df["vehicle_type"].tolist(),
                y=weights_df["adjusted_vehicle_equivalent_weight"].tolist(),
                name="Adjusted X-LPV weight",
                marker_color="#EF6C00",
            ))
            # Add bound whiskers (dotted vertical lines from lower to upper bound)
            # for vehicle types that have calibration bounds
            if "weight_lower_bound" in weights_df.columns and "weight_upper_bound" in weights_df.columns:
                bounds_rows = weights_df[
                    weights_df["weight_lower_bound"].notna() & weights_df["weight_upper_bound"].notna()
                ]
                for _, brow in bounds_rows.iterrows():
                    vt = brow["vehicle_type"]
                    lb = float(brow["weight_lower_bound"])
                    ub = float(brow["weight_upper_bound"])
                    fig.add_trace(go.Scatter(
                        x=[vt, vt],
                        y=[lb, ub],
                        mode="lines+markers",
                        name=f"{vt} weight bounds [{lb}–{ub}]",
                        line=dict(color="rgba(0,0,0,0.55)", dash="dot", width=2),
                        marker=dict(symbol="line-ew", size=12, color="black", line=dict(width=2)),
                        showlegend=True,
                    ))
            applied = bool(weights_df["weight_calibration_applied"].fillna(False).any()) if "weight_calibration_applied" in weights_df.columns else False
            fig.update_layout(
                **_layout("Module 3 - Passenger X-LPV weight calibration"),
                barmode="group",
                xaxis_title="Vehicle type",
                yaxis_title="X-LPV-equivalent weight",
            )
            caption = (
                "Original and adjusted passenger vehicle-equivalent weights. "
                "Adjusted values are used only when Module 1 marks the economy as passenger-saturated. "
                "Dotted whiskers show the allowed calibration bounds for each vehicle type."
            )
            if not applied:
                caption += " Calibration was not applied for this run."
            figs.append(("Passenger X-LPV weight calibration", fig, caption))

    if show_passenger_energy_context:
        base_year = int(pd.to_numeric(t5["year"], errors="coerce").dropna().min()) if "year" in t5.columns else None

        def _clean_year_series(series: pd.Series | None) -> pd.Series:
            if series is None:
                return pd.Series(dtype=float)
            cleaned = pd.to_numeric(series, errors="coerce").dropna().sort_index()
            cleaned.index = pd.to_numeric(cleaned.index, errors="coerce")
            cleaned = cleaned[cleaned.index.notna()]
            if cleaned.empty:
                return pd.Series(dtype=float)
            cleaned.index = cleaned.index.astype(int)
            return cleaned.sort_index()

        def _cagr_from_index(index_series: pd.Series) -> float | None:
            if index_series.empty or len(index_series) < 2:
                return None
            first_year = int(index_series.index.min())
            last_year = int(index_series.index.max())
            periods = last_year - first_year
            first_value = float(index_series.loc[first_year])
            last_value = float(index_series.loc[last_year])
            if periods <= 0 or first_value <= 0 or last_value <= 0:
                return None
            return (last_value / first_value) ** (1 / periods) - 1

        def _index_to_base(series: pd.Series, base: int | None) -> pd.Series:
            if base is None or series.empty:
                return pd.Series(dtype=float)
            base_value = series.get(base)
            if base_value is None or pd.isna(base_value) or float(base_value) <= 0:
                return pd.Series(dtype=float)
            return series / float(base_value) * 100

        def _fmt_rate(value: float | None) -> str:
            if value is None or pd.isna(value):
                return "n/a"
            return f"{float(value) * 100:.2f}%/yr"

        passenger_stock_index = pd.Series(dtype=float)
        projected_passenger_stock_growth = None
        if base_year is not None and {"year", "transport_type", "target_stock"}.issubset(t5.columns):
            passenger_stock = (
                t5[t5["transport_type"].astype(str).str.lower() == "passenger"]
                .groupby("year")["target_stock"]
                .sum()
                .sort_index()
            )
            passenger_stock = pd.to_numeric(passenger_stock, errors="coerce").dropna()
            passenger_stock_index = _index_to_base(passenger_stock, base_year)
            projected_passenger_stock_growth = _cagr_from_index(passenger_stock_index)

        passenger_energy_index = pd.Series(dtype=float)
        projected_passenger_energy_growth = None
        if (
            base_year is not None
            and isinstance(t13, pd.DataFrame)
            and not t13.empty
            and {"year", "transport_type", "mirror_energy_pj"}.issubset(t13.columns)
        ):
            t13_passenger = t13[t13["transport_type"].astype(str).str.lower() == "passenger"].copy()
            if not t13_passenger.empty:
                projected_energy = (
                    t13_passenger.groupby("year")["mirror_energy_pj"]
                    .sum()
                    .sort_index()
                )
                projected_energy = pd.to_numeric(projected_energy, errors="coerce").dropna()
                passenger_energy_index = _index_to_base(projected_energy, base_year)
                projected_passenger_energy_growth = _cagr_from_index(passenger_energy_index)

        historical_energy_index = pd.Series(dtype=float)
        historical_passenger_energy_growth = None
        if (
            base_year is not None
            and
            isinstance(esto_road_energy_pj, pd.DataFrame)
            and not esto_road_energy_pj.empty
            and {"year", "transport_type", "energy_pj"}.issubset(esto_road_energy_pj.columns)
        ):
            energy_df = esto_road_energy_pj[
                esto_road_energy_pj["transport_type"].astype(str).str.lower() == "passenger"
            ].copy()
            if not energy_df.empty:
                historical_energy = (
                    energy_df.groupby("year")["energy_pj"]
                    .sum()
                    .sort_index()
                )
                historical_energy = pd.to_numeric(historical_energy, errors="coerce").dropna()
                historical_energy = historical_energy[historical_energy.index <= base_year]
                historical_energy_index = _index_to_base(historical_energy, base_year)
                historical_passenger_energy_growth = _cagr_from_index(historical_energy_index.tail(11))

        gdp_per_capita_index = pd.Series(dtype=float)
        historical_gdp_per_capita_growth = None
        projected_gdp_per_capita_growth = None
        gdp_series = _clean_year_series(gdp)
        population_series_for_gdp = _clean_year_series(population)
        if base_year is not None and not gdp_series.empty and not population_series_for_gdp.empty:
            common_years = gdp_series.index.intersection(population_series_for_gdp.index)
            gdp_pc = gdp_series.loc[common_years] / population_series_for_gdp.loc[common_years].replace(0.0, float("nan"))
            gdp_pc = gdp_pc.dropna().sort_index()
            gdp_per_capita_index = _index_to_base(gdp_pc, base_year)
            historical_gdp_per_capita_growth = _cagr_from_index(gdp_per_capita_index[gdp_per_capita_index.index <= base_year].tail(11))
            projected_gdp_per_capita_growth = _cagr_from_index(gdp_per_capita_index[gdp_per_capita_index.index >= base_year])

        if (
            not passenger_stock_index.empty
            or not passenger_energy_index.empty
            or not historical_energy_index.empty
            or not gdp_per_capita_index.empty
        ):
            fig = go.Figure()
            if not historical_energy_index.empty:
                fig.add_trace(go.Scatter(
                    x=historical_energy_index.index.tolist(),
                    y=historical_energy_index.tolist(),
                    mode="lines",
                    name="Historical passenger energy index",
                    line=dict(color="#C26A00", width=2, dash="dot"),
                    opacity=0.75,
                ))
            historical_gdp_pc = gdp_per_capita_index[gdp_per_capita_index.index <= base_year] if base_year is not None else pd.Series(dtype=float)
            projected_gdp_pc = gdp_per_capita_index[gdp_per_capita_index.index >= base_year] if base_year is not None else pd.Series(dtype=float)
            if not historical_gdp_pc.empty:
                fig.add_trace(go.Scatter(
                    x=historical_gdp_pc.index.tolist(),
                    y=historical_gdp_pc.tolist(),
                    mode="lines",
                    name="Historical GDP per capita index",
                    line=dict(color="#263238", width=2, dash="dot"),
                    opacity=0.65,
                ))
            if not projected_gdp_pc.empty:
                fig.add_trace(go.Scatter(
                    x=projected_gdp_pc.index.tolist(),
                    y=projected_gdp_pc.tolist(),
                    mode="lines",
                    name="Projected GDP per capita index",
                    line=dict(color="#263238", width=3),
                ))
            if not passenger_stock_index.empty:
                fig.add_trace(go.Scatter(
                    x=passenger_stock_index.index.tolist(),
                    y=passenger_stock_index.tolist(),
                    mode="lines+markers",
                    name="Projected passenger stock index",
                    line=dict(color="#1565C0", width=3),
                ))
            if not passenger_energy_index.empty:
                fig.add_trace(go.Scatter(
                    x=passenger_energy_index.index.tolist(),
                    y=passenger_energy_index.tolist(),
                    mode="lines",
                    name="Simulated projected passenger energy index",
                    line=dict(color="#C26A00", width=3, dash="dash"),
                ))
            if base_year is not None:
                fig.add_vline(
                    x=base_year,
                    line_width=2,
                    line_dash="dot",
                    line_color="#7A869A",
                    annotation_text="Base year",
                    annotation_position="top",
                )
            fig.update_layout(
                **_layout("Passenger energy growth compared with GDP per capita"),
                yaxis_title=f"Index ({base_year} = 100)" if base_year is not None else "Index",
                xaxis_title="Year",
            )
            kpis = [
                ("Historical passenger energy growth", _fmt_rate(historical_passenger_energy_growth)),
                ("Historical GDP per capita growth", _fmt_rate(historical_gdp_per_capita_growth)),
                ("Projected GDP per capita growth", _fmt_rate(projected_gdp_per_capita_growth)),
                ("Projected passenger stock growth", _fmt_rate(projected_passenger_stock_growth)),
                ("Simulated projected passenger energy growth", _fmt_rate(projected_passenger_energy_growth)),
            ]
            kpi_html = "".join(
                '<div class="kpi-item">'
                f'<span>{escape(label)}</span>'
                f'<strong>{escape(value)}</strong>'
                '</div>'
                for label, value in kpis
            )
            caption = (
                f"<p>Passenger energy and GDP per capita are indexed to {base_year} = 100. "
                "The passenger stock line is the Module 3/4 stock trajectory, which is driven by the GDP-per-capita motorisation envelope. "
                "Dotted lines show historical growth before the base year; the dashed passenger energy line uses Module 7 simulated energy, "
                "so it reflects stock, mileage, efficiency, turnover, and drive-mix changes.</p>"
                f'<div class="kpi-grid">{kpi_html}</div>'
            )
            figs.append((
                "Passenger energy growth context",
                fig,
                caption,
            ))

    if {"year", "transport_type", "vehicle_type", "target_stock", "gdp_elasticity_used"}.issubset(t5.columns):
        freight_sub = t5[t5["transport_type"] == "freight"].copy()
        if not freight_sub.empty:
            base_year = int(freight_sub["year"].min())
            base_stocks = (
                freight_sub[freight_sub["year"] == base_year]
                .groupby("vehicle_type")["target_stock"].sum()
            )
            el_map = (
                freight_sub[["vehicle_type", "gdp_elasticity_used"]]
                .dropna(subset=["gdp_elasticity_used"])
                .drop_duplicates("vehicle_type")
                .set_index("vehicle_type")["gdp_elasticity_used"]
            )
            diag = pd.DataFrame()
            diag_cols = {
                "vehicle_type",
                "gdp_elasticity_used",
                "freight_raw_elasticity",
                "freight_elasticity_clamped",
                "freight_energy_growth_rate",
                "freight_gdp_growth_rate",
                "freight_elasticity_data_source",
                "freight_elasticity_note",
            }
            if diag_cols.issubset(t5.columns):
                diag_select_cols = [*diag_cols]
                if "freight_elasticity_adjustment" in t5.columns:
                    diag_select_cols.append("freight_elasticity_adjustment")
                diag = (
                    freight_sub[diag_select_cols]
                    .drop_duplicates("vehicle_type")
                    .sort_values("vehicle_type")
                    .reset_index(drop=True)
                )
                if "freight_elasticity_adjustment" not in diag.columns:
                    diag["freight_elasticity_adjustment"] = 1.0
            fig = go.Figure()
            gdp_index = pd.Series(dtype=float)
            if "gdp_index" in freight_sub.columns:
                gdp_index = (
                    freight_sub.groupby("year")["gdp_index"]
                    .mean()
                    .dropna()
                    .sort_index()
                )
                if not gdp_index.empty:
                    fig.add_trace(go.Scatter(
                        x=gdp_index.index.tolist(),
                        y=gdp_index.tolist(),
                        mode="lines",
                        name="GDP index",
                        line=dict(color="#263238", width=3),
                    ))
            indexed_stock_series_by_label: dict[str, pd.Series] = {}
            for i, (vt, grp) in enumerate(freight_sub.groupby("vehicle_type")):
                series = grp.groupby("year")["target_stock"].sum().sort_index()
                base = base_stocks.get(vt)
                indexed_series = (series / base * 100) if (base is not None and base > 0) else series
                el_val = el_map.get(vt)
                el_str = f" (ε={el_val:.2f})" if el_val is not None and not pd.isna(el_val) else ""
                label = _freight_vehicle_label(str(vt))
                indexed_stock_series_by_label[label] = indexed_series
                fig.add_trace(go.Scatter(
                    x=series.index.tolist(), y=indexed_series.tolist(),
                    mode="lines+markers",
                    name=f"{label} stock index{el_str}",
                    line=dict(color=_vehicle_type_colour(str(vt), i)),
                ))
            fig.update_layout(
                **_layout("Freight stock growth compared with GDP"),
                yaxis_title=f"Index ({base_year} = 100)",
                xaxis_title="Year",
            )

            def _first_numeric(series: pd.Series) -> float | None:
                values = pd.to_numeric(series, errors="coerce").dropna()
                return float(values.iloc[0]) if not values.empty else None

            def _fmt_num(value: float | None, decimals: int = 2, suffix: str = "") -> str:
                if value is None or pd.isna(value):
                    return "n/a"
                return f"{float(value):.{decimals}f}{suffix}"

            def _cagr_from_index(index_series: pd.Series) -> float | None:
                if index_series.empty or len(index_series) < 2:
                    return None
                first_year = int(index_series.index.min())
                last_year = int(index_series.index.max())
                periods = last_year - first_year
                first_value = float(index_series.loc[first_year])
                last_value = float(index_series.loc[last_year])
                if periods <= 0 or first_value <= 0 or last_value <= 0:
                    return None
                return (last_value / first_value) ** (1 / periods) - 1

            kpi_parts: list[str] = []
            kpi_source = diag if not diag.empty else (
                el_map.reset_index()
                .rename(columns={"index": "vehicle_type", "gdp_elasticity_used": "gdp_elasticity_used"})
            )
            for _, row in kpi_source.iterrows():
                vt_label = _freight_vehicle_label(str(row.get("vehicle_type", "")))
                el_value = pd.to_numeric(pd.Series([row.get("gdp_elasticity_used")]), errors="coerce").dropna()
                display_value = float(el_value.iloc[0]) if not el_value.empty else None
                if vt_label:
                    kpi_parts.append(
                        '<div class="kpi-item">'
                        f'<span>{escape(vt_label)} elasticity</span>'
                        f'<strong>{_fmt_num(display_value)}</strong>'
                        '</div>'
                    )

            energy_growth = _first_numeric(diag["freight_energy_growth_rate"]) if not diag.empty else None
            gdp_growth = _first_numeric(diag["freight_gdp_growth_rate"]) if not diag.empty else None
            projected_gdp_growth = _cagr_from_index(gdp_index)
            selected_elasticities = pd.to_numeric(el_map, errors="coerce").dropna()
            implied_projected_growth = (
                selected_elasticities * projected_gdp_growth
                if projected_gdp_growth is not None and not selected_elasticities.empty
                else pd.Series(dtype=float)
            )
            lookback_years = 10

            def _indexed_growth_line(growth_rate: float | None, years: list[int]) -> list[float] | None:
                if growth_rate is None or pd.isna(growth_rate):
                    return None
                return [100 * ((1 + float(growth_rate)) ** (year - base_year)) for year in years]

            simulated_freight_energy_index = pd.Series(dtype=float)
            simulated_projected_energy_growth = None
            if (
                show_freight_energy_context
                and isinstance(t13, pd.DataFrame)
                and not t13.empty
                and {"year", "transport_type", "mirror_energy_pj"}.issubset(t13.columns)
            ):
                t13_freight = t13[t13["transport_type"].astype(str).str.lower() == "freight"].copy()
                if not t13_freight.empty:
                    freight_energy = (
                        t13_freight.groupby("year")["mirror_energy_pj"]
                        .sum()
                        .sort_index()
                    )
                    freight_energy = pd.to_numeric(freight_energy, errors="coerce").dropna()
                    base_energy = freight_energy.get(base_year)
                    if base_energy is not None and pd.notna(base_energy) and float(base_energy) > 0:
                        simulated_freight_energy_index = freight_energy / float(base_energy) * 100
                        simulated_projected_energy_growth = _cagr_from_index(simulated_freight_energy_index)

            historical_years = list(range(base_year - lookback_years, base_year + 1))
            projection_years = (
                sorted(int(year) for year in gdp_index.index.tolist())
                if not gdp_index.empty
                else sorted(int(year) for year in freight_sub["year"].dropna().unique().tolist())
            )
            historical_energy_index = _indexed_growth_line(energy_growth, historical_years)
            historical_gdp_index = _indexed_growth_line(gdp_growth, historical_years)

            if show_freight_energy_context and historical_gdp_index is not None:
                fig.add_trace(go.Scatter(
                    x=historical_years,
                    y=historical_gdp_index,
                    mode="lines",
                    name="Historical GDP index",
                    line=dict(color="#263238", width=2, dash="dot"),
                    opacity=0.65,
                ))
            if show_freight_energy_context and historical_energy_index is not None:
                fig.add_trace(go.Scatter(
                    x=historical_years,
                    y=historical_energy_index,
                    mode="lines",
                    name="Historical freight energy index",
                    line=dict(color="#C26A00", width=2, dash="dot"),
                    opacity=0.75,
                ))
            if show_freight_energy_context and not simulated_freight_energy_index.empty and len(simulated_freight_energy_index) >= 2:
                fig.add_trace(go.Scatter(
                    x=simulated_freight_energy_index.index.tolist(),
                    y=simulated_freight_energy_index.tolist(),
                    mode="lines",
                    name="Simulated projected freight energy index",
                    line=dict(color="#C26A00", width=3, dash="dash"),
                ))
            if show_freight_energy_context:
                fig.add_vline(
                    x=base_year,
                    line_width=2,
                    line_dash="dot",
                    line_color="#7A869A",
                    annotation_text="Base year",
                    annotation_position="top",
                )
            clamped = False
            if not diag.empty:
                clamped_values = diag["freight_elasticity_clamped"].fillna(False).map(
                    lambda value: str(value).strip().lower() in {"true", "1", "yes", "y"}
                )
                clamped = bool(clamped_values.any())
            adjusted = False
            if not diag.empty and "freight_elasticity_adjustment" in diag.columns:
                adjustment_values = pd.to_numeric(diag["freight_elasticity_adjustment"], errors="coerce").dropna()
                adjusted = bool((adjustment_values.sub(1.0).abs() > 1e-9).any())
            override_text = ""
            if not diag.empty:
                override_text = " ".join(
                    diag.get("freight_elasticity_data_source", pd.Series(dtype=str)).fillna("").astype(str).tolist()
                    + diag.get("freight_elasticity_note", pd.Series(dtype=str)).fillna("").astype(str).tolist()
                ).lower()
            override_applied = clamped or adjusted or ("override" in override_text)
            kpi_parts.extend([
                '<div class="kpi-item"><span>Historical freight energy growth</span>'
                f'<strong>{_fmt_num(energy_growth * 100 if energy_growth is not None else None, suffix="%/yr")}</strong></div>',
                '<div class="kpi-item"><span>Historical GDP growth</span>'
                f'<strong>{_fmt_num(gdp_growth * 100 if gdp_growth is not None else None, suffix="%/yr")}</strong></div>',
                '<div class="kpi-item"><span>Projected GDP growth</span>'
                f'<strong>{_fmt_num(projected_gdp_growth * 100 if projected_gdp_growth is not None else None, suffix="%/yr")}</strong></div>',
            ])
            if not implied_projected_growth.empty and implied_projected_growth.round(6).nunique() == 1:
                kpi_parts.append(
                    '<div class="kpi-item"><span>Implied projected freight stock growth</span>'
                    f'<strong>{_fmt_num(float(implied_projected_growth.iloc[0]) * 100, suffix="%/yr")}</strong></div>'
                )
            elif not implied_projected_growth.empty:
                for vt, value in implied_projected_growth.items():
                    vt_label = _freight_vehicle_label(str(vt))
                    kpi_parts.append(
                        f'<div class="kpi-item"><span>Implied projected {escape(vt_label)} stock growth</span>'
                        f'<strong>{_fmt_num(float(value) * 100, suffix="%/yr")}</strong></div>'
                    )
            else:
                kpi_parts.append(
                    '<div class="kpi-item"><span>Implied projected freight stock growth</span>'
                    '<strong>n/a</strong></div>'
                )
            if show_freight_energy_context:
                kpi_parts.append(
                    '<div class="kpi-item"><span>Simulated projected freight energy growth</span>'
                    f'<strong>{_fmt_num(simulated_projected_energy_growth * 100 if simulated_projected_energy_growth is not None else None, suffix="%/yr")}</strong></div>'
                )
            kpi_parts.extend([
                '<div class="kpi-item"><span>Clamp/override applied</span>'
                f'<strong>{"Yes" if override_applied else "No"}</strong></div>',
            ])

            equal_elasticities = (
                len(selected_elasticities) > 1
                and selected_elasticities.round(6).nunique() == 1
            )
            lcv_stock_index = indexed_stock_series_by_label.get("LCV")
            truck_stock_index = indexed_stock_series_by_label.get("Truck")
            lcv_truck_overlap = False
            if lcv_stock_index is not None and truck_stock_index is not None:
                common_years = lcv_stock_index.index.intersection(truck_stock_index.index)
                if len(common_years) > 0:
                    lcv_truck_overlap = bool(np.allclose(
                        lcv_stock_index.loc[common_years].astype(float).to_numpy(),
                        truck_stock_index.loc[common_years].astype(float).to_numpy(),
                        equal_nan=True,
                    ))
            overlap_note = ""
            if lcv_truck_overlap:
                overlap_note = (
                    "<p>LCV and Truck have the same indexed stock trajectory in this chart, "
                    "so one line may sit directly on top of the other.</p>"
                )
            elif equal_elasticities and lcv_stock_index is not None and truck_stock_index is not None:
                overlap_note = (
                    "<p>LCV and Truck use the same freight elasticity, but this chart reflects the rendered stock trajectories. "
                    "If post-reconciliation adjustments differ by vehicle type, their indexed lines can still diverge.</p>"
                )
            if show_freight_energy_context and not simulated_freight_energy_index.empty:
                freight_energy_context_note = (
                    "<p>Post-reconciliation results include a base-year energy calibration and Module 7 simulation, "
                    "so the dashed freight energy line uses simulated freight energy from stock, mileage, efficiency, "
                    "turnover, and drive-mix assumptions. Use it to compare projected freight energy growth against "
                    "historical freight energy and GDP growth rates.</p>"
                    "<p>Dotted lines before the base year show the historical growth rates used to estimate elasticity. "
                    "The dashed freight energy line after the base year shows simulated projected freight energy indexed "
                    "to the reconciled base year.</p>"
                )
            elif show_freight_energy_context:
                freight_energy_context_note = (
                    "<p>Post-reconciliation stock results are available, but Module 7 simulated freight energy is not available "
                    "in this dashboard run. Energy growth is therefore not plotted here; use the Module 7 page after simulation "
                    "outputs are generated.</p>"
                )
            else:
                freight_energy_context_note = (
                    "<p>At this pre-reconciliation stage, the dashboard only knows the freight stock trajectory. "
                    "Projected freight energy use is not shown because the base year has not yet been reconciled to ESTO fuel energy "
                    "and Module 7 has not simulated stock, mileage, efficiency, turnover, and drive mix.</p>"
                )
            caption = (
                '<p class="chart-subtitle">Freight stock growth compared with GDP</p>'
                f"<p>Freight stock is indexed to {base_year} = 100. "
                "Solid stock lines show the rendered freight stock trajectory. The green dashed stock estimate shows the "
                "GDP-elasticity calculation that drives the freight stock growth assumption before any later adjustments.</p>"
                + freight_energy_context_note
                + f"{overlap_note}"
                + f'<div class="kpi-grid">{"".join(kpi_parts)}</div>'
            )

            if selected_elasticities.empty:
                interpretation = (
                    "Review whether the freight stock trajectory is plausible for the economy. "
                    "Low freight growth may be reasonable for mature economies, but may understate freight growth where "
                    "construction, manufacturing, logistics, mining, or road freight activity is expected to expand strongly."
                )
            elif selected_elasticities.round(2).nunique() == 1:
                interpretation = (
                    f"An elasticity of around {selected_elasticities.iloc[0]:.2f} means freight stock grows more slowly than GDP. "
                    "Review whether this is plausible for the economy: low values may be reasonable for mature economies, "
                    "but may understate freight growth where construction, manufacturing, logistics, mining, or road freight activity "
                    "is expected to expand strongly."
                )
            else:
                el_summary = ", ".join(
                    f"{_freight_vehicle_label(str(vt))}: {float(val):.2f}"
                    for vt, val in selected_elasticities.items()
                )
                interpretation = (
                    f"The selected freight elasticities ({el_summary}) determine how quickly each freight stock line grows relative to GDP. "
                    "Review whether these trajectories are plausible for the economy: low values may be reasonable for mature economies, "
                    "but may understate freight growth where construction, manufacturing, logistics, mining, or road freight activity "
                    "is expected to expand strongly."
                )

            after_html = f'<div class="interpretation-note">{escape(interpretation)}</div>'

            if not diag.empty:
                _el_num = pd.to_numeric(diag["gdp_elasticity_used"], errors="coerce")
                _gdp_gr = pd.to_numeric(diag["freight_gdp_growth_rate"], errors="coerce")
                _implied_growth = (_el_num * _gdp_gr * 100).round(2)
                _implied_growth_str = _implied_growth.where(_implied_growth.notna(), other=pd.NA).astype(str).replace("<NA>", "").replace("nan", "").tolist()

                table = go.Figure(data=[go.Table(
                    header=dict(
                        values=[
                            "Vehicle type",
                            "Final elasticity",
                            "Raw elasticity",
                            "Clamped",
                            "Energy growth %/yr",
                            "GDP growth %/yr",
                            "Elasticity adjustment",
                            "Implied freight growth %/yr",
                            "Source",
                            "Note",
                        ],
                        fill_color="#E8EDF7",
                        align="left",
                    ),
                    cells=dict(
                        values=[
                            diag["vehicle_type"].astype(str).tolist(),
                            pd.to_numeric(diag["gdp_elasticity_used"], errors="coerce").round(4).astype(str).tolist(),
                            pd.to_numeric(diag["freight_raw_elasticity"], errors="coerce").round(4).astype(str).replace("nan", "").tolist(),
                            diag["freight_elasticity_clamped"].fillna(False).map(
                                lambda value: "Yes" if str(value).strip().lower() in {"true", "1", "yes", "y"} else "No"
                            ).tolist(),
                            (pd.to_numeric(diag["freight_energy_growth_rate"], errors="coerce") * 100).round(2).astype(str).replace("nan", "").tolist(),
                            (pd.to_numeric(diag["freight_gdp_growth_rate"], errors="coerce") * 100).round(2).astype(str).replace("nan", "").tolist(),
                            pd.to_numeric(diag["freight_elasticity_adjustment"], errors="coerce").round(4).astype(str).replace("nan", "").tolist(),
                            _implied_growth_str,
                            diag["freight_elasticity_data_source"].fillna("").astype(str).tolist(),
                            diag["freight_elasticity_note"].fillna("").astype(str).tolist(),
                        ],
                        fill_color="white",
                        align="left",
                        height=24,
                    ),
                )])
                table.update_layout(**_layout("Freight elasticity calculation details"))
                table_html = pio.to_html(
                    _apply_dashboard_layout(table, wide=True),
                    full_html=False,
                    include_plotlyjs=False,
                    config={"responsive": True, "displaylogo": False},
                )
                details_intro = (
                    "Elasticity is estimated as historical freight energy growth divided by historical GDP growth. "
                    "It is then adjusted, clamped, or overridden only where configured."
                )
                after_html += (
                    '<details class="details-panel">'
                    '<summary>Show elasticity calculation details</summary>'
                    f'<p>{escape(details_intro)}</p>'
                    f'{table_html}'
                    '</details>'
                )

            figs.append((
                "Freight stock growth assumption",
                fig,
                True,
                caption,
                after_html,
            ))

    return figs


# ---------------------------------------------------------------------------
# Module 4 — sales & turnover
# ---------------------------------------------------------------------------

def module4_figures(t6: pd.DataFrame, t6v: pd.DataFrame) -> list[tuple[str, Any]]:
    """Interactive QA figures for Module 4 sales/turnover (T6, T6v)."""
    if not _can_plot():
        return []

    figs: list[tuple[str, Any]] = []

    if t6 is not None and not t6.empty and {"year", "vehicle_type", "new_sales"}.issubset(t6.columns):
        fig = go.Figure()
        for i, (vt, grp) in enumerate(t6.groupby("vehicle_type")):
            s = grp.groupby("year")["new_sales"].sum().sort_index()
            if len(s) > 1:
                s = s.iloc[1:]
            fig.add_trace(go.Scatter(
                x=s.index.tolist(), y=s.values.tolist(), name=str(vt), mode="lines",
                line=dict(color=_vehicle_type_colour(str(vt), i)),
            ))
        fig.update_layout(
            **_layout("Module 4 — New sales by vehicle type"),
            xaxis_title="Year", yaxis_title="New sales",
        )
        figs.append(("New sales by vehicle type", fig))

    if t6 is not None and not t6.empty and {"year", "vehicle_type", "stock"}.issubset(t6.columns):
        fig = go.Figure()
        for i, (vt, grp) in enumerate(t6.groupby("vehicle_type")):
            s = grp.groupby("year")["stock"].sum().sort_index()
            fig.add_trace(go.Scatter(
                x=s.index.tolist(), y=s.values.tolist(), name=str(vt), mode="lines",
                line=dict(color=_vehicle_type_colour(str(vt), i)),
            ))
        fig.update_layout(
            **_layout("Module 4 — Stock trajectory by vehicle type"),
            xaxis_title="Year", yaxis_title="Stock",
        )
        figs.append(("Stock trajectory by vehicle type", fig))

    if t6 is not None and not t6.empty and {"year", "natural_retirements", "additional_retirements"}.issubset(t6.columns):
        rr = t6.groupby("year")[["natural_retirements", "additional_retirements"]].sum().sort_index()
        if len(rr) > 1:
            rr = rr.iloc[1:]
        fig = go.Figure()
        for ret_name, ret_col, ret_color in [
            ("natural", "natural_retirements", "#5E6AD2"),
            ("additional", "additional_retirements", "#EF6C00"),
        ]:
            fig.add_trace(go.Scatter(
                x=rr.index.tolist(), y=rr[ret_col].tolist(),
                name=ret_name, stackgroup="ret", mode="lines",
                line=dict(color=ret_color, width=0.7),
                fillcolor=ret_color,
            ))
        fig.update_layout(
            **_layout("Module 4 — Retirements by type"),
            xaxis_title="Year", yaxis_title="Vehicles retired",
        )
        figs.append(("Retirements by type", fig))

    if t6v is not None and not t6v.empty and {"vehicle_type", "age", "vintage_share"}.issubset(t6v.columns):
        fig = go.Figure()
        for i, (vt, grp) in enumerate(t6v.groupby("vehicle_type")):
            g = grp.sort_values("age")
            fig.add_trace(go.Scatter(
                x=g["age"].tolist(), y=g["vintage_share"].tolist(), name=str(vt), mode="lines",
                line=dict(color=_vehicle_type_colour(str(vt), i)),
            ))
        fig.update_layout(
            **_layout("Module 4 — Base-year vintage profiles"),
            xaxis_title="Age", yaxis_title="Vintage share",
        )
        figs.append((
            "Base-year vintage profiles",
            fig,
            "Fleet age distribution in the base year after lifecycle calibration. Each line sums to 1 across ages; higher early-age shares mean a younger fleet."
        ))

    if t6v is not None and not t6v.empty and {"vehicle_type", "age", "survival_probability"}.issubset(t6v.columns):
        fig = go.Figure()
        for i, (vt, grp) in enumerate(t6v.groupby("vehicle_type")):
            g = grp.sort_values("age")
            cumulative = _annual_survival_to_cumulative_probability(
                g.set_index("age")["survival_probability"]
            )
            fig.add_trace(go.Scatter(
                x=cumulative.index.tolist(), y=cumulative.tolist(), name=str(vt), mode="lines",
                line=dict(color=_vehicle_type_colour(str(vt), i)),
            ))
        fig.update_layout(
            **_layout("Module 4 — Base-year survival curves"),
            xaxis_title="Age", yaxis_title="Cumulative survival probability",
        )
        figs.append((
            "Base-year survival curves",
            fig,
            "Probability that a new vehicle is still in the fleet at each age after turnover calibration. This is derived from the annual survival probabilities used internally by Module 4."
        ))

    if t6 is not None and not t6.empty and {"new_sales", "target_stock", "year"}.issubset(t6.columns):
        tmp = t6.groupby("year")[["new_sales", "target_stock"]].sum().sort_index()
        if len(tmp) > 1:
            tmp = tmp.iloc[1:]
        ratio = (tmp["new_sales"] / tmp["target_stock"].replace(0, float("nan"))).dropna()
        if not ratio.empty:
            fig = go.Figure(go.Scatter(
                x=ratio.index.tolist(), y=ratio.tolist(), mode="lines",
                line=dict(color="#5E35B1"),
            ))
            fig.update_layout(
                **_layout("Module 4 — Sales / stock ratio"),
                xaxis_title="Year", yaxis_title="Ratio",
            )
            figs.append(("Sales / stock ratio", fig))

    event_cols = {"year", "vehicle_type", "stock_above_target", "scale_factor_applied"}
    if t6 is not None and not t6.empty and event_cols.issubset(t6.columns):
        events = t6[t6["stock_above_target"].fillna(False).astype(bool)].copy()
        if not events.empty:
            counts = events.groupby(["year", "vehicle_type"]).size().reset_index(name="event_count")
            fig = go.Figure()
            for i, (vt, grp) in enumerate(counts.groupby("vehicle_type")):
                grp = grp.sort_values("year")
                fig.add_trace(go.Bar(
                    x=grp["year"].tolist(),
                    y=grp["event_count"].tolist(),
                    name=str(vt),
                    marker_color=_vehicle_type_colour(str(vt), i),
                ))
            fig.update_layout(
                **_layout("Module 4 - Stock above target events"),
                barmode="stack",
                xaxis_title="Year",
                yaxis_title="Event count",
            )
            figs.append((
                "Stock above target events",
                fig,
                "Years where surviving cohorts exceeded the target stock and were scaled down instead of requiring new sales.",
            ))

            shown = events.copy()
            shown["scale_factor_applied"] = pd.to_numeric(
                shown["scale_factor_applied"], errors="coerce"
            )
            shown = shown.sort_values(["year", "vehicle_type"]).head(80)
            table_cols = [
                col for col in [
                    "year",
                    "transport_type",
                    "vehicle_type",
                    "target_stock",
                    "new_sales",
                    "stock",
                    "scale_factor_applied",
                ]
                if col in shown.columns
            ]
            table = go.Figure(data=[go.Table(
                header=dict(values=table_cols, fill_color="#E8EDF7", align="left"),
                cells=dict(
                    values=[
                        (
                            shown[col].round(4).astype(str).tolist()
                            if pd.api.types.is_numeric_dtype(shown[col])
                            else shown[col].fillna("").astype(str).tolist()
                        )
                        for col in table_cols
                    ],
                    fill_color="white",
                    align="left",
                    height=24,
                ),
            )])
            table.update_layout(**_layout("Module 4 - Stock above target event table"))
            figs.append((
                "Stock above target event table",
                table,
                True,
                "Shows the first 80 stock-above-target events and the scale factor applied to surviving cohorts.",
            ))

    return figs


# ---------------------------------------------------------------------------
# Module 5 — sales shares
# ---------------------------------------------------------------------------

def module5_figures(t7: pd.DataFrame, t7f: pd.DataFrame) -> list[tuple[str, Any]]:
    """Interactive QA figures for Module 5 sales shares (T7, T7f)."""
    if not _can_plot():
        return []

    figs: list[tuple[str, Any]] = []

    # Base-year chart (single chart only)
    if t7 is not None and not t7.empty and {"vehicle_type", "drive_type", "sales_share"}.issubset(t7.columns):
        base_df = t7.copy()
        base_year_label = ""
        if "year" in base_df.columns:
            years = pd.to_numeric(base_df["year"], errors="coerce").dropna().astype(int)
            if not years.empty:
                base_year = int(years.min())
                base_df = base_df[pd.to_numeric(base_df["year"], errors="coerce") == base_year]
                base_year_label = f" ({base_year})"
        if "scenario" in base_df.columns:
            scenario_labels = base_df["scenario"].dropna().astype(str)
            if scenario_labels.str.casefold().eq("target").any():
                base_df = base_df[base_df["scenario"].astype(str).str.casefold().eq("target")].copy()

        pvt = base_df.pivot_table(
            index="vehicle_type", columns="drive_type",
            values="sales_share", aggfunc="mean", fill_value=0,
        )
        if not pvt.empty:
            non_ice_cols = [c for c in pvt.columns if str(c).upper() != "ICE"]
            order_key = pvt[non_ice_cols].sum(axis=1) if non_ice_cols else pvt.sum(axis=1)
            pvt = pvt.loc[order_key.sort_values(ascending=False).index]
            drive_order = pvt.sum(axis=0).sort_values(ascending=False).index.tolist()

            fig = go.Figure()
            for j, col in enumerate(drive_order):
                fig.add_trace(go.Bar(
                    name=str(col), y=pvt.index.tolist(), x=(pvt[col] * 100).tolist(),
                    orientation="h",
                    marker_color=_drive_colour(str(col), j),
                ))
            fig.update_layout(
                **_layout(f"Module 5 — Sales shares (base-year){base_year_label}"),
                barmode="stack", xaxis_title="Sales share (%)", yaxis_title="Vehicle type",
                xaxis=dict(range=[0, 105]),
            )
            figs.append((
                f"Sales shares (base-year){base_year_label}",
                fig,
                True,
                "Vehicle types are sorted by non-ICE share, with the largest values at the bottom so smaller rows stay easier to compare.",
            ))

    # Projected chart (only show when true multi-year projected data exists)
    if t7f is not None and not t7f.empty and {"drive_type", "sales_share", "year"}.issubset(t7f.columns):
        years = pd.to_numeric(t7f["year"], errors="coerce").dropna().astype(int)
        unique_years = sorted(years.unique().tolist())
        if len(unique_years) > 1:
            # Average scenarios first, then fill missing (year, vehicle_type, drive_type)
            # combos with 0 before averaging across vehicle types.  A direct pivot_table
            # mean would use unequal denominators for drive types absent from some vehicle
            # types in the base year, causing the stacked total to exceed 100 %.
            traj = (
                t7f.groupby(["year", "vehicle_type", "drive_type"])["sales_share"]
                .mean()
                .unstack("drive_type", fill_value=0.0)
                .groupby(level="year")
                .mean()
                .sort_index()
            )
            if not traj.empty:
                drive_order = traj.mean(axis=0).sort_values(ascending=False).index.tolist()
                fig = go.Figure()
                for j, col in enumerate(drive_order):
                    _c = _drive_colour(str(col), j)
                    fig.add_trace(go.Scatter(
                        x=traj.index.tolist(), y=(traj[col] * 100).tolist(),
                        name=str(col), stackgroup="share", mode="lines",
                        line=dict(color=_c, width=0.7),
                        fillcolor=_c,
                    ))
                year_range = f" ({unique_years[0]}-{unique_years[-1]})"
                fig.update_layout(
                    **_layout(f"Module 5 — Sales shares (projected){year_range}"),
                    xaxis_title="Year", yaxis_title="Sales share (%)",
                    yaxis=dict(range=[0, 105]),
                )
                figs.append((
                    f"Sales shares (projected){year_range}",
                    fig,
                    True,
                    "Shows average projected technology mix over time across branches (displayed only when multi-year projected data exists).",
                ))

    return figs


# ---------------------------------------------------------------------------
# Module 6 — reconciliation & LEAP handoff
# ---------------------------------------------------------------------------

def module6_figures(module6_outputs: dict[str, Any]) -> list[tuple[str, Any]]:
    """Interactive QA figures for Module 6 reconciliation (T8–T12)."""
    if not _can_plot() or not module6_outputs:
        return []

    figs: list[tuple[str, Any]] = []
    _t4 = module6_outputs.get("T4"); t4 = _t4 if isinstance(_t4, pd.DataFrame) else pd.DataFrame()
    _t8 = module6_outputs.get("T8"); t8 = _t8 if isinstance(_t8, pd.DataFrame) else pd.DataFrame()
    _t9 = module6_outputs.get("T9"); t9 = _t9 if isinstance(_t9, pd.DataFrame) else pd.DataFrame()
    _t10 = module6_outputs.get("T10"); t10 = _t10 if isinstance(_t10, pd.DataFrame) else pd.DataFrame()
    _t12 = module6_outputs.get("T12"); t12 = _t12 if isinstance(_t12, pd.DataFrame) else pd.DataFrame()
    _t12_phev = module6_outputs.get("T12_phev"); t12_phev = _t12_phev if isinstance(_t12_phev, pd.DataFrame) else pd.DataFrame()

    spread_fig = _spread_pre_vs_post_chart(t4, t9)
    if spread_fig is not None:
        figs.append((
            "Spread of stock / mileage / efficiency — pre vs post reconciliation",
            spread_fig,
            True,
            "Each line connects one branch's pre-reconciliation value (blue, from base-year input data T4) to its "
            "post-reconciliation value (red, from Module 6's adjusted output T9), so the shift caused by "
            "reconciliation is visible per branch. Categories are sorted by median value (highest to lowest). Use "
            "the dropdown to switch between vehicle type, drive type, and transport type groupings.",
        ))

    if not t12.empty and {
        "fuel", "remaining_esto_pj", "post_reconciliation_model_pj",
    }.issubset(t12.columns):
        chart = t12.copy()
        if "reconciliation_status" not in chart.columns:
            chart["reconciliation_status"] = "unknown"
        if "gap_pct" not in chart.columns:
            chart["gap_pct"] = np.nan

        fuels = chart["fuel"].tolist()
        post_vals = chart["post_reconciliation_model_pj"].tolist()
        statuses = chart["reconciliation_status"].fillna("unknown").astype(str).tolist()
        gaps = pd.to_numeric(chart["gap_pct"], errors="coerce").tolist()

        fig = go.Figure()
        if "pre_reconciliation_model_pj" in chart.columns:
            fig.add_trace(go.Bar(
                name="Previous model energy (pre-reconciliation)",
                x=fuels,
                y=chart["pre_reconciliation_model_pj"].tolist(),
                marker_color="#8E24AA",
            ))

        fig.add_trace(go.Bar(
            name="ESTO target",
            x=fuels,
            y=chart["remaining_esto_pj"].tolist(),
            marker_color="#1565C0",
        ))

        for status, label, colour in [
            ("ok", "Post-reconciliation model (OK)", "#43A047"),
            ("large_adjustment", "Post-reconciliation model (Large adjustment)", "#FFA000"),
            ("failed", "Post-reconciliation model (FAILED reconciliation)", "#E53935"),
            ("unknown", "Post-reconciliation model (Status unknown)", "#757575"),
        ]:
            y_vals = [v if s == status else None for v, s in zip(post_vals, statuses)]
            if all(v is None for v in y_vals):
                continue
            custom = [
                [s, g] if s == status else [None, None]
                for s, g in zip(statuses, gaps)
            ]
            fig.add_trace(go.Bar(
                name=label,
                x=fuels,
                y=y_vals,
                marker_color=colour,
                customdata=custom,
                hovertemplate=(
                    "%{x}<br>Energy=%{y:.2f} PJ"
                    "<br>Status=%{customdata[0]}"
                    "<br>Gap=%{customdata[1]:.1f}%<extra></extra>"
                ),
            ))

        fig.update_layout(
            **_layout("Module 6 — Post-reconciliation vs ESTO target (status-coloured post bars)"),
            barmode="group", xaxis_title="Fuel", yaxis_title="Energy (PJ)",
        )
        figs.append((
            "Post-reconciliation vs ESTO target",
            fig,
            "Shows previous model energy (pre-reconciliation), ESTO target, and post-reconciliation values. Post-reconciliation bars are colour-coded by reconciliation outcome so failures are immediately visible.",
        ))

    scalar_cols = [c for c in ["stock_scalar", "mileage_scalar", "efficiency_scalar"]
                   if not t9.empty and c in t9.columns]
    if scalar_cols:
        fig = make_subplots(rows=1, cols=len(scalar_cols), subplot_titles=scalar_cols)
        for i, col in enumerate(scalar_cols, 1):
            vals = _safe_numeric(t9[col])
            if not vals.empty:
                change_pct = (vals - 1.0) * 100.0
                fig.add_trace(
                    go.Histogram(
                        x=change_pct.tolist(),
                        name=col,
                        marker_color="#3949AB",
                        showlegend=False,
                        customdata=vals.tolist(),
                        hovertemplate=(
                            "Change from original=%{x:.1f}%"
                            "<br>Scalar=%{customdata:.3f}<extra></extra>"
                        ),
                    ),
                    row=1, col=i,
                )
            fig.update_xaxes(title_text="Change from original (%)", row=1, col=i)
            fig.update_yaxes(title_text="Branch count", row=1, col=i)
        fig.update_layout(**_layout("Module 6 — Reconciliation scalar distributions"))
        figs.append((
            "Scalar distributions",
            fig,
            True,
            "Distribution of scalar-driven branch changes. Zero means unchanged; negative values reduce the original branch value and positive values increase it. Hover shows the actual scalar.",
        ))

    # Scalar dashboard (faceted bars): stock / mileage / efficiency / energy correction
    scalar_specs = [
        ("stock_scalar", "Stock scalar"),
        ("mileage_scalar", "Mileage scalar"),
        ("efficiency_scalar", "Efficiency scalar"),
        ("energy_correction_factor", "Energy correction factor"),
    ]
    scalar_cols_for_chart = [col for col, _label in scalar_specs if col in t9.columns]
    required_scalar_cols = {"vehicle_type", "drive_type", "fuel", *scalar_cols_for_chart}
    if scalar_cols_for_chart and not t9.empty and required_scalar_cols.issubset(t9.columns):
        scalar_df = t9.copy()
        scalar_df["branch_key"] = (
            scalar_df["vehicle_type"].fillna("unknown")
            + "|"
            + scalar_df["drive_type"].fillna("unknown")
            + "|"
            + scalar_df["fuel"].fillna("unknown")
        )
        for col in scalar_cols_for_chart:
            scalar_df[col] = pd.to_numeric(scalar_df[col], errors="coerce")

        agg = (
            scalar_df.groupby("branch_key")[scalar_cols_for_chart]
            .median()
            .replace([pd.NA, float("inf"), float("-inf")], pd.NA)
            .dropna(how="all")
        )
        if not agg.empty:
            ranking = (agg.sub(1.0).abs().sum(axis=1)).sort_values(ascending=False)
            agg = agg.loc[ranking.head(8).index.tolist()]
            subplot_specs = [(col, label) for col, label in scalar_specs if col in scalar_cols_for_chart]
            fig = make_subplots(
                rows=2, cols=2,
                subplot_titles=tuple(label for _col, label in subplot_specs),
                horizontal_spacing=0.28,
                vertical_spacing=0.55,
            )
            for i, (metric_col, _label) in enumerate(subplot_specs, start=1):
                r = 1 if i <= 2 else 2
                c = 1 if i % 2 == 1 else 2
                fig.add_trace(
                    go.Bar(
                        x=agg.index.tolist(),
                        y=agg[metric_col].tolist(),
                        marker_color=_COLOURS[(i - 1) % len(_COLOURS)],
                        showlegend=False,
                        hovertemplate="%{x}<br>Scalar=%{y:.3f}<extra></extra>",
                    ),
                    row=r,
                    col=c,
                )
                fig.update_xaxes(title_text="Branch (vehicle|drive|fuel)", tickangle=-55, row=r, col=c)
                fig.update_yaxes(title_text="Scalar (1 = unchanged)", row=r, col=c)

            fig.update_layout(
                **_layout("Module 6 - Adjustment scalars by branch (top changing branches)"),
                height=1430,
                margin=dict(l=78, r=36, t=72, b=260),
            )
            for r in (1, 2):
                for c in (1, 2):
                    fig.add_hline(y=1.0, line_dash="dot", line_color="#616161", row=r, col=c)
            figs.append((
                "Adjustment scalars by branch",
                fig,
                True,
                "Shows the scalar used to move each branch from original to final values. A scalar of 1 means unchanged; below 1 reduces the value and above 1 increases it.",
            ))

    if not t9.empty and {"fuel", "energy_correction_factor"}.issubset(t9.columns):
        stats = t9.groupby("fuel")["energy_correction_factor"].mean().sort_values(ascending=False)
        if not stats.empty:
            fig = go.Figure(go.Bar(
                x=stats.index.tolist(), y=stats.tolist(), marker_color="#00897B",
            ))
            yaxis: dict[str, Any] = {"title": "Average correction factor"}
            positive = stats[stats > 0]
            if not positive.empty and positive.max() / positive.min() > 20:
                min_power = int(math.floor(math.log10(positive.min())))
                max_power = int(math.ceil(math.log10(positive.max())))
                tickvals = [10 ** p for p in range(min_power, max_power + 1)]
                yaxis.update({
                    "type": "log",
                    "title": "Average correction factor (log scale)",
                    "tickmode": "array",
                    "tickvals": tickvals,
                    "ticktext": [f"{v:g}" for v in tickvals],
                })
            fig.update_layout(
                **_layout("Module 6 - Average correction factor by fuel"),
                yaxis=yaxis,
            )
            figs.append((
                "Average correction factor by fuel",
                fig,
                "Average energy correction factor by fuel. Values near 1 imply low correction pressure; values far from 1 imply a larger pre-reconciliation mismatch.",
            ))

    if not t12_phev.empty and {
        "vehicle_type", "provided_phev_utilisation_rate",
        "backcalculated_phev_utilisation_rate", "utilisation_status",
    }.issubset(t12_phev.columns):
        chart = t12_phev.copy()
        chart["branch"] = (
            chart["vehicle_type"].fillna("unknown")
            + " | "
            + chart["drive_type"].fillna("unknown")
        )
        if "size" in chart.columns:
            chart["branch"] = chart["branch"] + chart["size"].fillna("").map(lambda x: f" | {x}" if x else "")
        for col in [
            "provided_phev_utilisation_rate", "diagnostic_lower_rate",
            "diagnostic_upper_rate", "backcalculated_phev_utilisation_rate",
            "electric_energy_share",
        ]:
            if col in chart.columns:
                chart[col] = pd.to_numeric(chart[col], errors="coerce")

        status_colours = {
            "ok": "#43A047",
            "below_range": "#E53935",
            "above_range": "#E53935",
            "no_phev_energy": "#757575",
        }
        fig = go.Figure()
        fig.add_trace(go.Bar(
            name="Back-calculated electric-km share",
            x=chart["branch"].tolist(),
            y=(chart["backcalculated_phev_utilisation_rate"] * 100.0).tolist(),
            marker_color=[
                status_colours.get(str(status), "#757575")
                for status in chart["utilisation_status"].tolist()
            ],
            customdata=chart[[
                "provided_phev_utilisation_rate",
                "electric_energy_share",
                "utilisation_status",
            ]].to_numpy(),
            hovertemplate=(
                "%{x}<br>Back-calculated=%{y:.1f}%"
                "<br>Provided=%{customdata[0]:.1%}"
                "<br>Energy share=%{customdata[1]:.1%}"
                "<br>Status=%{customdata[2]}<extra></extra>"
            ),
        ))
        fig.add_trace(go.Scatter(
            name="Provided utilisation rate",
            x=chart["branch"].tolist(),
            y=(chart["provided_phev_utilisation_rate"] * 100.0).tolist(),
            mode="markers",
            marker=dict(color="#1565C0", size=10, symbol="diamond"),
            hovertemplate="%{x}<br>Provided=%{y:.1f}%<extra></extra>",
        ))
        if {"diagnostic_lower_rate", "diagnostic_upper_rate"}.issubset(chart.columns):
            fig.add_trace(go.Scatter(
                name="Diagnostic lower bound",
                x=chart["branch"].tolist(),
                y=(chart["diagnostic_lower_rate"] * 100.0).tolist(),
                mode="lines",
                line=dict(color="#9E9E9E", dash="dot"),
                hovertemplate="%{x}<br>Lower=%{y:.1f}%<extra></extra>",
            ))
            fig.add_trace(go.Scatter(
                name="Diagnostic upper bound",
                x=chart["branch"].tolist(),
                y=(chart["diagnostic_upper_rate"] * 100.0).tolist(),
                mode="lines",
                line=dict(color="#9E9E9E", dash="dot"),
                hovertemplate="%{x}<br>Upper=%{y:.1f}%<extra></extra>",
            ))
        fig.update_layout(
            **_layout("Module 6 - PHEV utilisation back-check"),
            yaxis_title="Electric-mode utilisation (%)",
            xaxis_title="Plug-in hybrid branch",
            yaxis_range=[0, 100],
        )
        figs.append((
            "Plug-in hybrid utilisation back-check",
            fig,
            True,
            "Back-calculates plug-in hybrid electric-km share from final electricity and liquid energy using adjusted efficiencies, then compares it with the supplied utilisation rate.",
        ))

    if not t10.empty and {"drive_type", "fuel", "device_share"}.issubset(t10.columns):
        sub = t10[t10["drive_type"].isin(["ICE", "PHEV"])].copy()
        if not sub.empty:
            ds = sub.groupby(["drive_type", "fuel"])["device_share"].mean().reset_index()
            labels = (ds["drive_type"] + "|" + ds["fuel"]).tolist()
            fig = go.Figure(go.Bar(x=labels, y=ds["device_share"].tolist(), marker_color="#6D4C41"))
            fig.update_layout(
                **_layout("Module 6 — Mean device share by drive/fuel"),
                yaxis_title="Device share",
            )
            figs.append((
                "Device share by drive/fuel",
                fig,
                "Average fuel split used inside multi-fuel drive types (mainly ICE/PHEV branches).",
            ))

    allocation_cols = {"vehicle_type", "drive_type", "fuel", "final_branch_fuel_pj"}
    if not t9.empty and allocation_cols.issubset(t9.columns):
        alloc = t9.copy()
        alloc["final_branch_fuel_pj"] = pd.to_numeric(
            alloc["final_branch_fuel_pj"], errors="coerce"
        ).fillna(0.0)
        alloc["vehicle_drive"] = (
            alloc["vehicle_type"].fillna("unknown")
            + " | "
            + alloc["drive_type"].fillna("unknown")
        )
        heat = (
            alloc.groupby(["vehicle_drive", "fuel"])["final_branch_fuel_pj"]
            .sum()
            .unstack(fill_value=0.0)
        )
        if not heat.empty:
            row_totals = heat.sum(axis=1)
            heat = heat.loc[row_totals[row_totals > 0].sort_values(ascending=False).index]
            row_totals = heat.sum(axis=1)
        if not heat.empty:
            share = heat.div(row_totals, axis=0) * 100.0
            fuel_order = heat.sum(axis=0).sort_values(ascending=False).index.tolist()
            fig = go.Figure()
            for i, fuel in enumerate(fuel_order):
                fig.add_trace(go.Bar(
                    x=share.index.tolist(),
                    y=share[fuel].tolist(),
                    name=str(fuel),
                    marker_color=_fuel_colour(str(fuel), i),
                    customdata=heat[fuel].tolist(),
                    hovertemplate=(
                        "Vehicle/drive=%{x}<br>Fuel=" + str(fuel)
                        + "<br>Share=%{y:.1f}%"
                        + "<br>Energy=%{customdata:.2f} PJ<extra></extra>"
                    ),
                ))
            fig.update_layout(
                **_layout("Module 6 - Final fuel allocation share by vehicle type and drive (2022)"),
                barmode="stack",
                height=620,
                xaxis_title="Vehicle type | drive",
                yaxis_title="Share of final allocated fuel energy (%)",
                yaxis_range=[0, 100],
                legend_title_text="Fuel",
            )
            figs.append((
                "Final fuel allocation share by vehicle type and drive (2022)",
                fig,
                True,
                "Final allocated fuel energy mix after reconciliation. Each bar sums to 100%; fuels with the largest total allocation are stacked from the bottom.",
            ))

    energy_cols = {"vehicle_type", "drive_type", "fuel", "final_branch_fuel_pj"}
    if not t9.empty and energy_cols.issubset(t9.columns):
        energy = t9.copy()
        energy["final_branch_fuel_pj"] = pd.to_numeric(
            energy["final_branch_fuel_pj"], errors="coerce"
        ).fillna(0.0)
        energy["initial_branch_energy_pj"] = pd.to_numeric(
            energy.get("initial_branch_energy_pj", pd.Series(0.0, index=energy.index)),
            errors="coerce",
        ).fillna(0.0)
        energy["vehicle_drive"] = (
            energy["vehicle_type"].fillna("unknown")
            + " | "
            + energy["drive_type"].fillna("unknown")
        )
        grouped = (
            energy.groupby(["vehicle_drive", "fuel"], dropna=False)
            .agg(
                final_energy_pj=("final_branch_fuel_pj", "sum"),
                initial_energy_pj=("initial_branch_energy_pj", "sum"),
            )
            .reset_index()
        )
        grouped = grouped[grouped["final_energy_pj"] > 0].copy()
        if not grouped.empty:
            branch_totals = (
                grouped.groupby("vehicle_drive")["final_energy_pj"]
                .sum()
                .sort_values(ascending=False)
            )
            fuel_order = (
                grouped.groupby("fuel")["final_energy_pj"]
                .sum()
                .sort_values(ascending=False)
                .index
                .tolist()
            )
            x_order = branch_totals.index.tolist()
            fig = go.Figure()
            for i, fuel in enumerate(fuel_order):
                fuel_rows = (
                    grouped[grouped["fuel"].eq(fuel)]
                    .set_index("vehicle_drive")
                    .reindex(x_order)
                    .reset_index()
                )
                fig.add_trace(go.Bar(
                    x=x_order,
                    y=fuel_rows["final_energy_pj"].fillna(0.0).tolist(),
                    name=str(fuel),
                    marker_color=_fuel_colour(str(fuel), i),
                    customdata=fuel_rows[["initial_energy_pj"]].fillna(0.0).to_numpy(),
                    hovertemplate=(
                        "Vehicle/drive=%{x}<br>Fuel=" + str(fuel)
                        + "<br>Final energy=%{y:.2f} PJ"
                        + "<br>Initial energy=%{customdata[0]:.2f} PJ<extra></extra>"
                    ),
                ))
            fig.update_layout(
                **_layout("Module 6 - Final fuel energy by vehicle type and drive (2022)"),
                barmode="stack",
                height=660,
                xaxis_title="Vehicle type | drive",
                yaxis_title="Final reconciled energy use (PJ)",
                legend_title_text="Fuel",
            )
            figs.append((
                "Final fuel energy by vehicle type and drive (2022)",
                fig,
                True,
                "Absolute post-reconciliation energy use from T9, grouped by vehicle type and drive type and stacked by fuel. This shows where the 2022 fuel energy actually sits after reconciliation.",
            ))

    return figs


# ---------------------------------------------------------------------------
# Module 7 — interactive dropdown helpers
# ---------------------------------------------------------------------------


def _area_chart_with_dropdown(
    t13: pd.DataFrame,
    metric_col: str,
    yaxis_title: str,
    title: str,
    t13_fuel: pd.DataFrame | None = None,
    fuel_metric_col: str | None = None,
) -> "go.Figure | None":
    """Stacked area chart with a Plotly dropdown to switch between groupings.

    Groupings: vehicle type, drive type, transport type,
    drive × vehicle type, drive × transport type.
    When t13_fuel and fuel_metric_col are provided, a 'By fuel' option is added.
    """
    if t13 is None or t13.empty or metric_col not in t13.columns or "year" not in t13.columns:
        return None

    grouping_defs: list[tuple] = []
    if "vehicle_type" in t13.columns:
        grouping_defs.append(("By vehicle type", t13, "vehicle_type", _vehicle_type_colour, metric_col))
    if "drive_type" in t13.columns:
        grouping_defs.append(("By drive type", t13, "drive_type", _drive_colour, metric_col))
    if "transport_type" in t13.columns:
        grouping_defs.append(("By transport type", t13, "transport_type", _transport_mode_colour, metric_col))
    if {"drive_type", "vehicle_type"}.issubset(t13.columns):
        _tmp = t13.copy()
        _tmp["_dv"] = _tmp["drive_type"].astype(str) + " × " + _tmp["vehicle_type"].astype(str)
        grouping_defs.append(("By drive × vehicle type", _tmp, "_dv", None, metric_col))
    if {"drive_type", "transport_type"}.issubset(t13.columns):
        _tmp = t13.copy()
        _tmp["_dt"] = _tmp["drive_type"].astype(str) + " × " + _tmp["transport_type"].astype(str)
        grouping_defs.append(("By drive × transport type", _tmp, "_dt", None, metric_col))
    if (
        t13_fuel is not None
        and not t13_fuel.empty
        and fuel_metric_col is not None
        and "fuel" in t13_fuel.columns
        and fuel_metric_col in t13_fuel.columns
        and "year" in t13_fuel.columns
    ):
        grouping_defs.append(("By fuel", t13_fuel, "fuel", _fuel_colour, fuel_metric_col))

    if not grouping_defs:
        return None

    fig = go.Figure()
    trace_groups: list[tuple[str, int, int]] = []
    n_traces = 0

    for grp_idx, (grp_label, src_df, grp_col, colour_fn, m_col) in enumerate(grouping_defs):
        g = src_df.groupby(["year", grp_col])[m_col].sum().unstack(fill_value=0.0).sort_index()
        if g.empty:
            trace_groups.append((grp_label, n_traces, 0))
            continue
        cats = sorted(g.columns.tolist(), key=lambda c: float(g[c].sum()), reverse=True)
        is_first = grp_idx == 0
        for j, cat in enumerate(cats):
            _c = colour_fn(str(cat), j) if colour_fn else _COLOURS[j % len(_COLOURS)]
            fig.add_trace(go.Scatter(
                x=g.index.tolist(),
                y=g[cat].tolist(),
                name=str(cat),
                stackgroup=grp_label,
                mode="lines",
                line=dict(color=_c, width=0.7),
                fillcolor=_c,
                visible=is_first,
                showlegend=is_first,
                legendgroup=f"{grp_label}::{cat}",
            ))
        trace_groups.append((grp_label, n_traces, len(cats)))
        n_traces += len(cats)

    if n_traces == 0:
        return None

    total = n_traces
    buttons = []
    for grp_label, start, count in trace_groups:
        if count == 0:
            continue
        vis = [False] * total
        sleg = [False] * total
        for i in range(start, start + count):
            vis[i] = True
            sleg[i] = True
        buttons.append(dict(
            label=grp_label,
            method="update",
            args=[{"visible": vis, "showlegend": sleg}],
        ))

    if not buttons:
        return None

    fig.update_layout(
        **_layout(title),
        xaxis_title="Year",
        yaxis_title=yaxis_title,
        margin=dict(t=90),
        updatemenus=[dict(
            type="dropdown",
            direction="down",
            x=0.0,
            y=1.22,
            xanchor="left",
            yanchor="top",
            buttons=buttons,
            showactive=True,
            bgcolor="white",
            bordercolor="#cccccc",
            font=dict(size=12),
        )],
    )
    return fig


def _distribution_chart_with_dropdown(
    df: pd.DataFrame,
    metric_col: str,
    metric_label: str,
    title: str,
) -> "go.Figure | None":
    """Box/dot plots for a metric distribution with a dropdown to switch grouping.

    Groups by vehicle type, drive type, and transport type (whichever are present),
    sorted by median value so the most extreme categories are easiest to read.
    """
    if df is None or df.empty or metric_col not in df.columns:
        return None

    grouping_defs: list[tuple[str, str, Any]] = []
    if "vehicle_type" in df.columns:
        grouping_defs.append(("By vehicle type", "vehicle_type", _vehicle_type_colour))
    if "drive_type" in df.columns:
        grouping_defs.append(("By drive type", "drive_type", _drive_colour))
    if "transport_type" in df.columns:
        grouping_defs.append(("By transport type", "transport_type", _transport_mode_colour))

    if not grouping_defs:
        return None

    tmp = df.copy()
    if tmp.columns.duplicated().any():
        tmp = tmp.loc[:, ~tmp.columns.duplicated(keep="last")]
    tmp[metric_col] = pd.to_numeric(tmp[metric_col], errors="coerce")
    tmp = tmp.dropna(subset=[metric_col])
    if tmp.empty:
        return None

    fig = go.Figure()
    trace_groups: list[tuple[str, int, int]] = []
    n_traces = 0

    for grp_idx, (grp_label, grp_col, colour_fn) in enumerate(grouping_defs):
        if grp_col not in tmp.columns:
            trace_groups.append((grp_label, n_traces, 0))
            continue
        order = tmp.groupby(grp_col)[metric_col].median().sort_values(ascending=False).index.tolist()
        is_first = grp_idx == 0
        for j, cat in enumerate(order):
            vals = tmp.loc[tmp[grp_col] == cat, metric_col].tolist()
            _c = colour_fn(str(cat), j)
            fig.add_trace(go.Box(
                y=vals,
                name=str(cat),
                marker_color=_c,
                line_color=_c,
                boxpoints="all",
                jitter=0.4,
                pointpos=0,
                visible=is_first,
                showlegend=False,
            ))
        count = len(order)
        trace_groups.append((grp_label, n_traces, count))
        n_traces += count

    if n_traces == 0:
        return None

    total = n_traces
    buttons = []
    for grp_label, start, count in trace_groups:
        if count == 0:
            continue
        vis = [False] * total
        for i in range(start, start + count):
            vis[i] = True
        buttons.append(dict(
            label=grp_label,
            method="update",
            args=[{"visible": vis}],
        ))

    if not buttons:
        return None

    fig.update_layout(
        **_layout(title),
        yaxis_title=metric_label,
        margin=dict(t=90),
        updatemenus=[dict(
            type="dropdown",
            direction="down",
            x=0.0,
            y=1.22,
            xanchor="left",
            yanchor="top",
            buttons=buttons,
            showactive=True,
            bgcolor="white",
            bordercolor="#cccccc",
            font=dict(size=12),
        )],
    )
    return fig


_PRE_RECONCILIATION_COLOUR = "#1565C0"
_POST_RECONCILIATION_COLOUR = "#E53935"


_BRANCH_KEY_COLS = ["economy", "scenario", "transport_type", "vehicle_type", "drive_type", "fuel", "size"]


def _spread_pre_vs_post_chart(t4: pd.DataFrame, t9: pd.DataFrame) -> "go.Figure | None":
    """Pre- vs post-reconciliation dot plot, one panel per metric.

    Each branch (a unique vehicle/drive/transport/fuel combination) contributes
    two dots — its pre-reconciliation value (T4, blue) and its post-reconciliation
    value (T9's adjusted_* columns, red) — offset slightly so both are visible,
    so the effect of reconciliation is visible per branch rather than only as an
    aggregate distribution. A dropdown switches the grouping used to position and
    order branches along the x-axis (vehicle type / drive type / transport type).
    """
    if t4 is None or t4.empty or t9 is None or t9.empty:
        return None

    pre = t4.copy()
    post = t9.drop(
        columns=[c for c in ("stock", "mileage_km_per_year", "efficiency_km_per_gj") if c in t9.columns],
    ).rename(columns={
        "adjusted_stock": "stock",
        "adjusted_mileage_km_per_year": "mileage_km_per_year",
        "adjusted_efficiency_km_per_gj": "efficiency_km_per_gj",
    }).copy()

    metrics = [
        ("stock", "Stock"),
        ("mileage_km_per_year", "Mileage (km/year)"),
        ("efficiency_km_per_gj", "Efficiency (km/GJ)"),
    ]
    metrics = [(c, l) for c, l in metrics if c in pre.columns and c in post.columns]
    if not metrics:
        return None

    key_cols = [c for c in _BRANCH_KEY_COLS if c in pre.columns and c in post.columns]
    if not key_cols:
        return None

    grouping_defs: list[tuple[str, str]] = []
    for grp_label, grp_col in [
        ("By vehicle type", "vehicle_type"),
        ("By drive type", "drive_type"),
        ("By transport type", "transport_type"),
    ]:
        if grp_col in key_cols:
            grouping_defs.append((grp_label, grp_col))

    if not grouping_defs:
        return None

    fig = make_subplots(
        rows=1,
        cols=len(metrics),
        subplot_titles=tuple(label for _col, label in metrics),
        horizontal_spacing=0.07,
    )

    # Branch-level pairing of pre/post values, shared across all groupings/metrics.
    paired_by_metric: dict[str, pd.DataFrame] = {}
    for col, _label in metrics:
        p = pre[key_cols + [col]].rename(columns={col: "pre_val"})
        q = post[key_cols + [col]].rename(columns={col: "post_val"})
        paired = p.merge(q, on=key_cols, how="inner")
        paired["pre_val"] = pd.to_numeric(paired["pre_val"], errors="coerce")
        paired["post_val"] = pd.to_numeric(paired["post_val"], errors="coerce")
        paired = paired.dropna(subset=["pre_val", "post_val"], how="all").reset_index(drop=True)
        paired_by_metric[col] = paired

    trace_groups: list[tuple[str, list[int], dict[str, Any]]] = []
    initial_axis_updates: dict[str, Any] = {}
    n_traces = 0

    for grp_idx, (grp_label, grp_col) in enumerate(grouping_defs):
        is_first = grp_idx == 0
        indices: list[int] = []
        relayout: dict[str, Any] = {}
        for j, (col, label) in enumerate(metrics, start=1):
            paired = paired_by_metric[col]
            if paired.empty:
                continue
            branch = paired.copy()
            branch[grp_col] = branch[grp_col].astype(str)

            order_val = branch["post_val"].where(branch["post_val"].notna(), branch["pre_val"])
            order = (
                branch.assign(_order=order_val)
                .groupby(grp_col)["_order"]
                .median()
                .sort_values(ascending=False)
                .index.tolist()
            )
            cat_pos = {cat: i for i, cat in enumerate(order)}

            # Spread branches that share a category across a small x-band so
            # individual pre->post segments don't overlap.
            rank_in_cat = branch.groupby(grp_col).cumcount()
            n_in_cat = branch.groupby(grp_col)[grp_col].transform("count")
            span = np.where(n_in_cat > 1, 0.64 * rank_in_cat / (n_in_cat - 1).clip(lower=1) - 0.32, 0.0)
            branch["_x"] = branch[grp_col].map(cat_pos) + span

            hover = (
                branch[key_cols].fillna("").astype(str).agg(" / ".join, axis=1)
                if key_cols else [""] * len(branch)
            )

            # Offset pre/post dots slightly either side of each branch's x slot
            # so both are visible without a connecting line.
            fig.add_trace(
                go.Scatter(
                    x=branch["_x"] - 0.08,
                    y=branch["pre_val"],
                    mode="markers",
                    name="Pre-reconciliation",
                    legendgroup="pre",
                    showlegend=(j == 1),
                    marker=dict(color=_PRE_RECONCILIATION_COLOUR, size=6),
                    customdata=hover,
                    hovertemplate="%{customdata}<br>Pre: %{y:,.3g}<extra></extra>",
                    visible=is_first,
                ),
                row=1,
                col=j,
            )
            indices.append(n_traces)
            n_traces += 1

            fig.add_trace(
                go.Scatter(
                    x=branch["_x"] + 0.08,
                    y=branch["post_val"],
                    mode="markers",
                    name="Post-reconciliation",
                    legendgroup="post",
                    showlegend=(j == 1),
                    marker=dict(color=_POST_RECONCILIATION_COLOUR, size=6),
                    customdata=hover,
                    hovertemplate="%{customdata}<br>Post: %{y:,.3g}<extra></extra>",
                    visible=is_first,
                ),
                row=1,
                col=j,
            )
            indices.append(n_traces)
            n_traces += 1

            xkey = "xaxis" if j == 1 else f"xaxis{j}"
            axis_update = dict(
                tickmode="array",
                tickvals=list(range(len(order))),
                ticktext=order,
                range=[-0.5, len(order) - 0.5],
            )
            relayout[f"{xkey}.tickmode"] = axis_update["tickmode"]
            relayout[f"{xkey}.tickvals"] = axis_update["tickvals"]
            relayout[f"{xkey}.ticktext"] = axis_update["ticktext"]
            relayout[f"{xkey}.range"] = axis_update["range"]
            if is_first:
                initial_axis_updates[xkey] = axis_update
            fig.update_yaxes(title_text=label, row=1, col=j)

        trace_groups.append((grp_label, indices, relayout))

    if n_traces == 0:
        return None

    total = n_traces
    buttons = []
    for grp_label, indices, relayout in trace_groups:
        if not indices:
            continue
        vis = [False] * total
        for i in indices:
            vis[i] = True
        buttons.append(dict(label=grp_label, method="update", args=[{"visible": vis}, relayout]))

    if not buttons:
        return None

    fig.update_layout(
        **_layout("Spread of stock, mileage and efficiency — pre vs post reconciliation"),
        legend=dict(orientation="h", x=0.0, y=1.18),
        margin=dict(t=130),
        updatemenus=[dict(
            type="dropdown",
            direction="down",
            x=0.0,
            y=1.3,
            xanchor="left",
            yanchor="top",
            buttons=buttons,
            showactive=True,
            bgcolor="white",
            bordercolor="#cccccc",
            font=dict(size=12),
        )],
        **initial_axis_updates,
    )
    return fig


def _spread_dot_chart(df: pd.DataFrame, title: str) -> "go.Figure | None":
    """Dot-plot spread of stock, mileage and efficiency for a single dataset.

    One subplot per metric; branches are jittered horizontally within their
    category (coloured by category, like the grouping it belongs to) so
    individual values are visible. This is the single-dataset counterpart to
    :func:`_spread_pre_vs_post_chart` — used where there's no pre/post pairing
    to draw, e.g. base-year input data straight from T4.
    """
    if df is None or df.empty:
        return None

    metrics = [
        ("stock", "Stock"),
        ("mileage_km_per_year", "Mileage (km/year)"),
        ("efficiency_km_per_gj", "Efficiency (km/GJ)"),
    ]
    metrics = [(c, l) for c, l in metrics if c in df.columns]
    if not metrics:
        return None

    grouping_defs: list[tuple[str, str, Any]] = []
    for grp_label, grp_col, colour_fn in [
        ("By vehicle type", "vehicle_type", _vehicle_type_colour),
        ("By drive type", "drive_type", _drive_colour),
        ("By transport type", "transport_type", _transport_mode_colour),
    ]:
        if grp_col in df.columns:
            grouping_defs.append((grp_label, grp_col, colour_fn))
    if not grouping_defs:
        return None

    tmp = df.copy()
    if tmp.columns.duplicated().any():
        tmp = tmp.loc[:, ~tmp.columns.duplicated(keep="last")]
    for col, _label in metrics:
        tmp[col] = pd.to_numeric(tmp[col], errors="coerce")

    # Build a per-row hover string from all available branch attributes.
    _hover_field_labels = [
        ("vehicle_type", "Vehicle"),
        ("drive_type", "Drive"),
        ("transport_type", "Transport"),
        ("fuel", "Fuel"),
        ("size", "Size"),
        ("scenario", "Scenario"),
        ("economy", "Economy"),
    ]
    _hover_fields = [(c, lbl) for c, lbl in _hover_field_labels if c in tmp.columns]
    if _hover_fields:
        tmp["_hover"] = tmp.apply(
            lambda r: "<br>".join(f"{lbl}: {r[c]}" for c, lbl in _hover_fields if pd.notna(r[c]) and str(r[c]) != ""),
            axis=1,
        )
    else:
        tmp["_hover"] = ""

    fig = make_subplots(
        rows=1,
        cols=len(metrics),
        subplot_titles=tuple(label for _col, label in metrics),
        horizontal_spacing=0.07,
    )

    trace_groups: list[tuple[str, list[int], dict[str, Any]]] = []
    initial_axis_updates: dict[str, Any] = {}
    n_traces = 0

    for grp_idx, (grp_label, grp_col, colour_fn) in enumerate(grouping_defs):
        is_first = grp_idx == 0
        indices: list[int] = []
        relayout: dict[str, Any] = {}
        for j, (col, label) in enumerate(metrics, start=1):
            sub = tmp.dropna(subset=[col]).copy()
            if sub.empty:
                continue
            sub[grp_col] = sub[grp_col].astype(str)
            order = sub.groupby(grp_col)[col].median().sort_values(ascending=False).index.tolist()
            cat_pos = {cat: i for i, cat in enumerate(order)}

            # Spread branches that share a category across a small x-band so
            # individual points don't overlap.
            rank_in_cat = sub.groupby(grp_col).cumcount()
            n_in_cat = sub.groupby(grp_col)[grp_col].transform("count")
            span = np.where(n_in_cat > 1, 0.64 * rank_in_cat / (n_in_cat - 1).clip(lower=1) - 0.32, 0.0)
            sub["_x"] = sub[grp_col].map(cat_pos) + span

            for k, cat in enumerate(order):
                cat_rows = sub[sub[grp_col] == cat]
                if cat_rows.empty:
                    continue
                _c = colour_fn(str(cat), k)
                fig.add_trace(
                    go.Scatter(
                        x=cat_rows["_x"],
                        y=cat_rows[col],
                        mode="markers",
                        name=str(cat),
                        marker=dict(color=_c, size=7),
                        showlegend=False,
                        visible=is_first,
                        customdata=cat_rows["_hover"].tolist(),
                        hovertemplate="%{customdata}<br>" + f"{label}: " + "%{y:,.3g}<extra></extra>",
                    ),
                    row=1,
                    col=j,
                )
                indices.append(n_traces)
                n_traces += 1

            xkey = "xaxis" if j == 1 else f"xaxis{j}"
            axis_update = dict(
                tickmode="array",
                tickvals=list(range(len(order))),
                ticktext=order,
                range=[-0.5, len(order) - 0.5],
            )
            relayout[f"{xkey}.tickmode"] = axis_update["tickmode"]
            relayout[f"{xkey}.tickvals"] = axis_update["tickvals"]
            relayout[f"{xkey}.ticktext"] = axis_update["ticktext"]
            relayout[f"{xkey}.range"] = axis_update["range"]
            if is_first:
                initial_axis_updates[xkey] = axis_update
            fig.update_yaxes(title_text=label, row=1, col=j)

        trace_groups.append((grp_label, indices, relayout))

    if n_traces == 0:
        return None

    total = n_traces
    buttons = []
    for grp_label, indices, relayout in trace_groups:
        if not indices:
            continue
        vis = [False] * total
        for i in indices:
            vis[i] = True
        buttons.append(dict(label=grp_label, method="update", args=[{"visible": vis}, relayout]))

    if not buttons:
        return None

    fig.update_layout(
        **_layout(title),
        margin=dict(t=110),
        updatemenus=[dict(
            type="dropdown",
            direction="down",
            x=0.0,
            y=1.22,
            xanchor="left",
            yanchor="top",
            buttons=buttons,
            showactive=True,
            bgcolor="white",
            bordercolor="#cccccc",
            font=dict(size=12),
        )],
        **initial_axis_updates,
    )
    return fig


# ---------------------------------------------------------------------------
# Share-based interactive charts (used in Module 7)
# ---------------------------------------------------------------------------

def _stacked_share_chart_with_dropdown(
    t13: pd.DataFrame,
    metric_col: str,
    yaxis_title: str,
    title: str,
) -> "go.Figure | None":
    """Stacked 100% area chart of shares with a dropdown to switch groupings.

    For each grouping dimension the metric values are summed by (year, category),
    then expressed as a percentage of the yearly total so each view sums to 100%.
    """
    if t13 is None or t13.empty or metric_col not in t13.columns or "year" not in t13.columns:
        return None

    grouping_defs: list[tuple[str, Any, str, Any]] = []
    if "drive_type" in t13.columns:
        grouping_defs.append(("By drive type", t13, "drive_type", _drive_colour))
    if "vehicle_type" in t13.columns:
        grouping_defs.append(("By vehicle type", t13, "vehicle_type", _vehicle_type_colour))
    if "transport_type" in t13.columns:
        grouping_defs.append(("By transport type", t13, "transport_type", _transport_mode_colour))
    if {"drive_type", "vehicle_type"}.issubset(t13.columns):
        _tmp = t13.copy()
        _tmp["_dv"] = _tmp["drive_type"].astype(str) + " × " + _tmp["vehicle_type"].astype(str)
        grouping_defs.append(("By drive × vehicle type", _tmp, "_dv", None))
    if {"drive_type", "transport_type"}.issubset(t13.columns):
        _tmp = t13.copy()
        _tmp["_dt"] = _tmp["drive_type"].astype(str) + " × " + _tmp["transport_type"].astype(str)
        grouping_defs.append(("By drive × transport type", _tmp, "_dt", None))

    if not grouping_defs:
        return None

    fig = go.Figure()
    trace_groups: list[tuple[str, int, int]] = []
    n_traces = 0

    for grp_idx, (grp_label, src_df, grp_col, colour_fn) in enumerate(grouping_defs):
        g = src_df.groupby(["year", grp_col])[metric_col].sum().unstack(fill_value=0.0).sort_index()
        if g.empty:
            trace_groups.append((grp_label, n_traces, 0))
            continue
        totals = g.sum(axis=1).replace(0.0, float("nan"))
        share = g.div(totals, axis=0).fillna(0.0)
        cats = share.sum(axis=0).sort_values(ascending=False).index.tolist()
        is_first = grp_idx == 0
        for j, cat in enumerate(cats):
            _c = colour_fn(str(cat), j) if colour_fn else _COLOURS[j % len(_COLOURS)]
            fig.add_trace(go.Scatter(
                x=share.index.tolist(),
                y=(share[cat] * 100).tolist(),
                name=str(cat),
                stackgroup=grp_label,
                mode="lines",
                line=dict(color=_c, width=0.7),
                fillcolor=_c,
                visible=is_first,
                showlegend=is_first,
                legendgroup=f"{grp_label}::{cat}",
            ))
        trace_groups.append((grp_label, n_traces, len(cats)))
        n_traces += len(cats)

    if n_traces == 0:
        return None

    total = n_traces
    buttons = []
    for grp_label, start, count in trace_groups:
        if count == 0:
            continue
        vis = [False] * total
        sleg = [False] * total
        for i in range(start, start + count):
            vis[i] = True
            sleg[i] = True
        buttons.append(dict(
            label=grp_label,
            method="update",
            args=[{"visible": vis, "showlegend": sleg}],
        ))

    if not buttons:
        return None

    fig.update_layout(
        **_layout(title),
        xaxis_title="Year",
        yaxis_title=yaxis_title,
        yaxis=dict(range=[0, 105]),
        margin=dict(t=90),
        updatemenus=[dict(
            type="dropdown",
            direction="down",
            x=0.0, y=1.22,
            xanchor="left", yanchor="top",
            buttons=buttons,
            showactive=True,
            bgcolor="white",
            bordercolor="#cccccc",
            font=dict(size=12),
        )],
    )
    return fig


def _sales_share_with_dropdown(t7f: pd.DataFrame, title: str) -> "go.Figure | None":
    """Sales share by drive type with a dropdown to filter by vehicle type.

    The default view shows the fleet-average drive-type sales mix. Each subsequent
    dropdown option shows the drive-type trajectory for a single vehicle type.
    """
    if t7f is None or t7f.empty:
        return None
    if not {"year", "drive_type", "sales_share"}.issubset(t7f.columns):
        return None

    grouping_defs: list[tuple[str, pd.DataFrame]] = []

    fleet_avg = (
        t7f.groupby(["year", "vehicle_type", "drive_type"])["sales_share"]
        .mean()
        .unstack("drive_type", fill_value=0.0)
        .groupby(level="year")
        .mean()
        .sort_index()
    )
    if not fleet_avg.empty:
        grouping_defs.append(("All vehicles (fleet avg)", fleet_avg))

    if "vehicle_type" in t7f.columns:
        for vt in sorted(t7f["vehicle_type"].dropna().unique(), key=str):
            sub = t7f[t7f["vehicle_type"] == vt]
            vt_data = (
                sub.groupby(["year", "drive_type"])["sales_share"]
                .mean()
                .unstack("drive_type", fill_value=0.0)
                .sort_index()
            )
            if not vt_data.empty:
                grouping_defs.append((str(vt), vt_data))

    if not grouping_defs:
        return None

    fig = go.Figure()
    trace_groups: list[tuple[str, int, int]] = []
    n_traces = 0

    for grp_idx, (label, df_view) in enumerate(grouping_defs):
        drive_order = df_view.mean(axis=0).sort_values(ascending=False).index.tolist()
        is_first = grp_idx == 0
        for j, dt in enumerate(drive_order):
            _c = _drive_colour(str(dt), j)
            fig.add_trace(go.Scatter(
                x=df_view.index.tolist(),
                y=(df_view[dt] * 100).tolist(),
                name=str(dt),
                stackgroup=label,
                mode="lines",
                line=dict(color=_c, width=0.7),
                fillcolor=_c,
                visible=is_first,
                showlegend=is_first,
                legendgroup=f"{label}::{dt}",
            ))
        trace_groups.append((label, n_traces, len(drive_order)))
        n_traces += len(drive_order)

    if n_traces == 0:
        return None

    total = n_traces
    buttons = []
    for grp_label, start, count in trace_groups:
        if count == 0:
            continue
        vis = [False] * total
        sleg = [False] * total
        for i in range(start, start + count):
            vis[i] = True
            sleg[i] = True
        buttons.append(dict(
            label=grp_label,
            method="update",
            args=[{"visible": vis, "showlegend": sleg}],
        ))

    if not buttons:
        return None

    fig.update_layout(
        **_layout(title),
        xaxis_title="Year",
        yaxis_title="Share of new sales (%)",
        yaxis=dict(range=[0, 105]),
        margin=dict(t=90),
        updatemenus=[dict(
            type="dropdown",
            direction="down",
            x=0.0, y=1.22,
            xanchor="left", yanchor="top",
            buttons=buttons,
            showactive=True,
            bgcolor="white",
            bordercolor="#cccccc",
            font=dict(size=12),
        )],
    )
    return fig


# ---------------------------------------------------------------------------
# Module 7 — mirror model
# ---------------------------------------------------------------------------

_MODULE7_NOTE_HTML = (
    '<div class="intro-card">'
    '<h3>About these outputs</h3>'
    '<p>This page shows a <strong>Python simulation</strong> of what LEAP might produce given the road model assumptions. '
    'These are not LEAP outputs — they are a mirror calculation run in Python to validate that the model logic produces '
    'sensible results before the data is handed off to LEAP. Use them for QA and sanity-checking, not as final results.</p>'
    '</div>'
)


def module7_figures(
    module7_outputs: dict[str, Any],
    t7f: pd.DataFrame | None = None,
    t4: pd.DataFrame | None = None,
    t9: pd.DataFrame | None = None,
) -> list[tuple[str, Any]]:
    """Interactive QA figures for Module 7 mirror outputs (T13, T13_fuel).

    Args:
        module7_outputs: dict with T13 and T13_fuel DataFrames.
        t7f: Optional T7f future sales shares DataFrame (for sales share by drive type).
        t4: Optional T4 base-year branches DataFrame (for mileage/efficiency distributions,
            used as a fallback if t9 is not available).
        t9: Optional T9 reconciliation scalars DataFrame (adjusted_mileage_km_per_year /
            adjusted_efficiency_km_per_gj), used for post-reconciliation distributions.
    """
    if not _can_plot() or not module7_outputs:
        return []

    figs: list[tuple[str, Any]] = []
    _t13 = module7_outputs.get("T13"); t13 = _t13 if isinstance(_t13, pd.DataFrame) else pd.DataFrame()
    _t13f = module7_outputs.get("T13_fuel"); t13_fuel = _t13f if isinstance(_t13f, pd.DataFrame) else pd.DataFrame()

    # --- Drive-type charts ---

    if not t13.empty and {"year", "drive_type", "mirror_stock"}.issubset(t13.columns):
        stock_share_fig = _stacked_share_chart_with_dropdown(
            t13,
            metric_col="mirror_stock",
            yaxis_title="Share of fleet (%)",
            title="Stock share",
        )
        if stock_share_fig is not None:
            figs.append((
                "Stock share",
                stock_share_fig,
                "half",
                "Use the dropdown to switch between: share by drive type, vehicle type, transport type, or compound categories.",
            ))

    if t7f is not None and not t7f.empty and {"year", "drive_type", "sales_share"}.issubset(t7f.columns):
        sales_share_fig = _sales_share_with_dropdown(t7f, "Sales share")
        if sales_share_fig is not None:
            figs.append((
                "Sales share",
                sales_share_fig,
                "half",
                "Use the dropdown to view the drive-type mix for all vehicles (fleet average) or a specific vehicle type.",
            ))

    if not t13.empty and {"mirror_energy_pj", "leap_energy_pj", "year"}.issubset(t13.columns):
        comp = t13.dropna(subset=["leap_energy_pj"]).copy()
        if not comp.empty:
            comp["energy_diff"] = (
                pd.to_numeric(comp["mirror_energy_pj"], errors="coerce")
                - pd.to_numeric(comp["leap_energy_pj"], errors="coerce")
            )
            diff = comp.groupby("year")["energy_diff"].sum().sort_index()
            fig = go.Figure()
            fig.add_hline(y=0.0, line_dash="dash", line_color="#333333")
            fig.add_trace(go.Bar(x=diff.index.tolist(), y=diff.tolist(), marker_color="#D81B60"))
            fig.update_layout(
                **_layout("Simulation minus LEAP energy"),
                xaxis_title="Year", yaxis_title="Energy difference (PJ)",
            )
            figs.append(("Simulation minus LEAP energy", fig))

    # --- Interactive dropdown area charts ---

    if not t13.empty and "mirror_energy_pj" in t13.columns:
        en_dropdown = _area_chart_with_dropdown(
            t13,
            metric_col="mirror_energy_pj",
            yaxis_title="Energy (PJ)",
            title="Energy",
            t13_fuel=t13_fuel if not t13_fuel.empty else None,
            fuel_metric_col="mirror_fuel_energy_pj",
        )
        if en_dropdown is not None:
            figs.append((
                "Energy",
                en_dropdown,
                True,
                "Use the dropdown (top-left of chart) to switch between groupings: vehicle type, drive type, transport type, fuel, or compound categories.",
            ))

    if not t13.empty and "mirror_stock" in t13.columns:
        stock_dropdown = _area_chart_with_dropdown(
            t13,
            metric_col="mirror_stock",
            yaxis_title="Vehicles",
            title="Stock",
        )
        if stock_dropdown is not None:
            figs.append((
                "Stock",
                stock_dropdown,
                True,
                "Use the dropdown to switch between groupings: vehicle type, drive type, transport type, or compound categories.",
            ))

    if not t13.empty and "mirror_vehicle_km" in t13.columns:
        vkm_dropdown = _area_chart_with_dropdown(
            t13,
            metric_col="mirror_vehicle_km",
            yaxis_title="Vehicle-km",
            title="Vehicle-km",
        )
        if vkm_dropdown is not None:
            figs.append((
                "Vehicle-km",
                vkm_dropdown,
                True,
                "Use the dropdown to switch between groupings: vehicle type, drive type, transport type, or compound categories.",
            ))

    return figs


# ---------------------------------------------------------------------------
# Workflow summary figures
# ---------------------------------------------------------------------------

def workflow_summary_figures(workflow_outputs: dict[str, Any]) -> list[tuple[str, Any]]:
    """Summary figures spanning the whole workflow (Module 6 reconciliation + Module 7)."""
    if not _can_plot() or not workflow_outputs:
        return []

    timings = workflow_outputs.get("timings") or {}

    # Module 2 figures — base-year branch spread (stock/mileage/efficiency distributions).
    m2_raw = module2_figures(workflow_outputs.get("T4"))
    m2_by_title = {item[0]: item for item in m2_raw}

    # Module 7's mileage/efficiency distribution charts are superseded by the
    # pre-vs-post spread comparison chart (module2_figures), so they are excluded here.
    m7_by_title: dict[str, Any] = {}

    # Module 3 figures — Passenger X-LPV, freight stock growth, and target stocks.
    _t5_post = workflow_outputs.get("T5_post_reconciliation")
    _t5_pre = workflow_outputs.get("T5_pre_reconciliation")
    t5 = (
        _t5_post if isinstance(_t5_post, pd.DataFrame) and not _t5_post.empty
        else _t5_pre if isinstance(_t5_pre, pd.DataFrame) and not _t5_pre.empty
        else workflow_outputs.get("T5")
    )
    t5_is_post_reconciliation = isinstance(_t5_post, pd.DataFrame) and not _t5_post.empty
    m3_raw = (
        module3_figures(
            t5,
            population=workflow_outputs.get("population"),
            show_freight_energy_context=t5_is_post_reconciliation,
            t13=workflow_outputs.get("T13"),
            show_passenger_energy_context=t5_is_post_reconciliation,
            gdp=workflow_outputs.get("gdp"),
            esto_road_energy_pj=workflow_outputs.get("esto_road_energy_pj"),
        )
        if isinstance(t5, pd.DataFrame) and not t5.empty
        else []
    )
    m3_by_title = {item[0]: item for item in m3_raw}

    # Module 4 figures — new sales, stock trajectories, vintage and survival profiles.
    _t6_post = workflow_outputs.get("T6_post_reconciliation")
    _t6_pre = workflow_outputs.get("T6_pre_reconciliation")
    t6 = (
        _t6_post if isinstance(_t6_post, pd.DataFrame) and not _t6_post.empty
        else _t6_pre if isinstance(_t6_pre, pd.DataFrame) and not _t6_pre.empty
        else workflow_outputs.get("T6")
    )
    _t6v_post = workflow_outputs.get("T6v_post_reconciliation")
    _t6v_pre = workflow_outputs.get("T6v_pre_reconciliation")
    t6v = (
        _t6v_post if isinstance(_t6v_post, pd.DataFrame) and not _t6v_post.empty
        else _t6v_pre if isinstance(_t6v_pre, pd.DataFrame) and not _t6v_pre.empty
        else workflow_outputs.get("T6v")
    )
    m4_raw = module4_figures(t6, t6v) if isinstance(t6, pd.DataFrame) and not t6.empty else []
    m4_by_title = {item[0]: item for item in m4_raw}

    # Module 5 figures — base-year and projected drive-type sales shares.
    m5_raw = module5_figures(workflow_outputs.get("T7"), workflow_outputs.get("T7f"))
    m5_by_title = {item[0]: item for item in m5_raw}

    # Module 6 figures — reconciliation scalars and fuel allocation.
    m6_sub = {k: workflow_outputs.get(k) for k in ("T4", "T8", "T9", "T10", "T12", "T12_phev")}
    m6_raw = module6_figures(m6_sub)
    m6_by_title = {item[0]: item for item in m6_raw}

    # Correction factors: only include if any ECF deviates meaningfully from 1.0.
    _t9 = workflow_outputs.get("T9")
    _ecf_col = "energy_correction_factor"
    _include_ecf = (
        isinstance(_t9, pd.DataFrame)
        and _ecf_col in _t9.columns
        and (_t9[_ecf_col].dropna() - 1.0).abs().max() > 0.01
    )

    # Post-reconciliation vs ESTO figure.
    _t12 = workflow_outputs.get("T12")
    t12 = _t12 if isinstance(_t12, pd.DataFrame) else pd.DataFrame()
    esto_fig: tuple | None = None
    if not t12.empty and {
        "fuel", "remaining_esto_pj", "post_reconciliation_model_pj",
    }.issubset(t12.columns):
        g = t12.copy()
        if "reconciliation_status" not in g.columns:
            g["reconciliation_status"] = "unknown"
        fuels = g["fuel"].tolist()
        statuses = g["reconciliation_status"].fillna("unknown").astype(str).tolist()
        post_vals = g["post_reconciliation_model_pj"].tolist()
        fig = go.Figure()
        if "pre_reconciliation_model_pj" in g.columns:
            fig.add_trace(go.Bar(
                name="Previous model energy (pre-reconciliation)",
                x=fuels,
                y=g["pre_reconciliation_model_pj"].tolist(),
                marker_color="#8E24AA",
            ))
        fig.add_trace(go.Bar(
            name="ESTO target",
            x=fuels,
            y=g["remaining_esto_pj"].tolist(),
            marker_color="#1565C0",
        ))
        for status, label, colour in [
            ("ok", "Post-reconciliation model (OK)", "#43A047"),
            ("large_adjustment", "Post-reconciliation model (Large adjustment)", "#FFA000"),
            ("failed", "Post-reconciliation model (FAILED reconciliation)", "#E53935"),
            ("unknown", "Post-reconciliation model (Status unknown)", "#757575"),
        ]:
            y_vals = [v if s == status else None for v, s in zip(post_vals, statuses)]
            if all(v is None for v in y_vals):
                continue
            fig.add_trace(go.Bar(name=label, x=fuels, y=y_vals, marker_color=colour))
        fig.update_layout(
            **_layout("Post-reconciliation vs ESTO targets (status-coloured post bars)"),
            barmode="group", xaxis_title="Fuel", yaxis_title="Energy (PJ)",
        )
        esto_fig = ("Post-reconciliation vs ESTO", fig, True)

    # Workflow timing figure.
    timing_fig: tuple | None = None
    if isinstance(timings, dict) and timings:
        modules = [k.replace("_seconds", "").replace("_", " ") for k in timings if k.endswith("_seconds")]
        secs = [timings[k] for k in timings if k.endswith("_seconds")]
        if modules:
            fig = go.Figure(go.Bar(x=modules, y=secs, marker_color="#1E88E5"))
            fig.update_layout(
                **_layout("Workflow timing by module"),
                xaxis_title="Module", yaxis_title="Seconds",
            )
            timing_fig = ("Workflow timing", fig)

    # Assemble in desired row order, then ESTO second-to-last, timing at the bottom.
    # Each title is looked up across all module dicts; first match wins.
    _ALL = {**m2_by_title, **m3_by_title, **m4_by_title, **m5_by_title, **m6_by_title, **m7_by_title}
    _DESIRED_ORDER = [
        # Stock & sales outputs sent to LEAP
        "Target stock trajectories",
        "New sales by vehicle type",
        "Passenger X-LPV-equivalent vehicles vs saturation",
        "Freight stock growth assumption",
        "Passenger energy growth context",
        # Drive-type technology mix
        "Sales shares (base-year)",
        "Sales shares (projected)",
        # Fleet composition inputs
        "Base-year vintage profiles",
        "Base-year survival curves",
        # Reconciliation outputs
        "Scalar distributions",
        "Final fuel allocation share by vehicle type and drive (2022)",
        # Base-year distributions
        "Spread of stock / mileage / efficiency — pre vs post reconciliation",
    ]
    figs: list[tuple[str, Any]] = []
    for title in _DESIRED_ORDER:
        item = _ALL.get(title)
        if item is None:
            # prefix match for dynamic titles (e.g. "Sales shares (base-year) 2022")
            item = next((v for k, v in _ALL.items() if k.startswith(title)), None)
        if item is not None:
            figs.append(item)

    # Correction factors only if non-trivial
    if _include_ecf:
        ecf_item = m6_by_title.get("Average correction factor by fuel")
        if ecf_item is not None:
            figs.append(ecf_item)

    if esto_fig is not None:
        figs.append(esto_fig)
    if timing_fig is not None:
        figs.append(timing_fig)

    return figs


# ---------------------------------------------------------------------------
# Alert banner helper
# ---------------------------------------------------------------------------

def _reconciliation_alert_html(t12: pd.DataFrame | None) -> str:
    """Return an HTML alert banner summarising reconciliation status from T12."""
    if t12 is None or not isinstance(t12, pd.DataFrame) or t12.empty:
        return ""
    if "reconciliation_status" not in t12.columns or "fuel" not in t12.columns:
        return ""

    failed = t12.loc[t12["reconciliation_status"] == "failed", "fuel"].tolist()
    large  = t12.loc[t12["reconciliation_status"] == "large_adjustment", "fuel"].tolist()

    if not failed and not large:
        return '<div class="alert alert--ok">&#10003; All fuels reconciled within tolerance.</div>'

    parts: list[str] = []
    if failed:
        parts.append(f"<b>Failed reconciliation:</b> {', '.join(failed)}")
    if large:
        parts.append(f"<b>Large adjustment (&gt;2%):</b> {', '.join(large)}")

    detail = " &nbsp;|&nbsp; ".join(parts)
    level = "alert--fail" if failed else "alert--warn"
    return f'<div class="alert {level}">&#9888; Reconciliation issues &mdash; {detail}</div>'


def _transport_split_alert_html(t13: pd.DataFrame | None, tol: float = 0.75) -> str:
    """Return an HTML alert banner checking the freight/passenger energy split.

    The base-year share of the *smaller* transport type (usually freight) is used
    as the reference.  If any projected year has that type's share outside
    [base × (1-tol), base × (1+tol)] the banner shows a warning or failure.

    Args:
        t13: T13 mirror outputs DataFrame with columns year, transport_type,
            mirror_energy_pj.
        tol: Fractional tolerance (default 0.75 = ±75 %).
    """
    if t13 is None or not isinstance(t13, pd.DataFrame) or t13.empty:
        return ""
    req = {"year", "transport_type", "mirror_energy_pj"}
    if not req.issubset(t13.columns):
        return ""

    energy = (
        t13.groupby(["year", "transport_type"])["mirror_energy_pj"]
        .sum().unstack(fill_value=0.0).sort_index()
    )
    if energy.empty or energy.shape[1] < 2:
        return ""

    base_year = int(energy.index.min())
    base_row = energy.loc[base_year]
    base_total = base_row.sum()
    if base_total <= 0:
        return ""

    base_share = base_row / base_total
    # The smaller transport type (typically freight) defines the bound.
    min_type = str(base_share.idxmin())
    base_min_share = float(base_share[min_type])
    lower = base_min_share * (1.0 - tol)
    upper = base_min_share * (1.0 + tol)

    total = energy.sum(axis=1)
    share_series = energy[min_type].div(total.replace(0.0, float("nan"))).dropna()
    violations = share_series[(share_series < lower) | (share_series > upper)]

    base_pct = f"{base_min_share * 100:.1f}%"
    bound_lo = f"{lower * 100:.1f}%"
    bound_hi = f"{upper * 100:.1f}%"
    base_info = (
        f"{min_type.capitalize()} share at base year {base_year}: <b>{base_pct}</b> "
        f"&mdash; expected range: <b>{bound_lo}&ndash;{bound_hi}</b>"
    )

    if violations.empty:
        return (
            f'<div class="alert alert--ok">&#10003; Freight/passenger energy split within bounds. '
            f'{base_info}.</div>'
        )

    viol_min = float(violations.min())
    viol_max = float(violations.max())
    viol_years = sorted(violations.index.tolist())
    first_year = viol_years[0]
    first_val = float(violations.loc[first_year])
    first_rule = (
        f"exceeds upper bound ({bound_hi})" if first_val > upper
        else f"falls below lower bound ({bound_lo})"
    )
    year_range = (
        f"{first_year}&ndash;{viol_years[-1]}"
        if len(viol_years) > 1 else str(first_year)
    )
    detail = (
        f"First breach: <b>{first_year}</b> ({min_type} share {first_val * 100:.1f}% {first_rule}). "
        f"Continues for {len(viol_years)} year(s) ({year_range}); "
        f"observed range {viol_min * 100:.1f}%&ndash;{viol_max * 100:.1f}% "
        f"vs allowed {bound_lo}&ndash;{bound_hi}. "
        f"{base_info}. "
        f"<i>Note: this is an indicator only &mdash; a genuine rapid shift in one transport "
        f"type&apos;s energy use will also trigger this.</i>"
    )
    # fail if any year drops the smaller type below 10 % absolute share
    severe = violations[violations < 0.10]
    return f'<div class="alert alert--warn">&#9888; Freight/passenger split out of bounds &mdash; {detail}</div>'


# ---------------------------------------------------------------------------
# HTML page builder
# ---------------------------------------------------------------------------

_NAV_LINKS: list[tuple[str, str]] = [
    ("index.html", "Overview"),
    ("module1.html", "Inputs & branches"),
    ("module3.html", "Stocks, sales & turnover"),
    ("module6.html", "Reconciliation"),
    ("module3_post_reconciliation.html", "Post-reconciliation stocks"),
    ("module7.html", "Simulated outputs"),
    ("workflow_summary.html", "Summary"),
]

# ---------------------------------------------------------------------------
# Data density index
# ---------------------------------------------------------------------------
# Maps chart title → minimum density level at which it appears.
# Inclusiveness rule: "less" = show at all levels; "more" = more + ultra only;
# "ultra" = ultra only. Unknown titles default to "more".
# Prefix matching is used for dynamic titles (e.g. "Sales shares (base-year) 2022").

_CHART_DENSITY: dict[str, str] = {
    # --- Module 2 (shown on module1.html) ---
    "Rows with missing branch values": "more",
    # --- Module 1 (inputs QA) ---
    "Default and researcher-provided values by branch/measure": "more",
    "Rows with missing year value": "more",
    "Input data table": "ultra",
    # --- Module 3 / 4 / 5 (module3.html) ---
    "Target stock trajectories": "less",  # module3.html + summary
    "New sales by vehicle type": "less",
    "Stock trajectory by vehicle type": "more",
    "Passenger X-LPV-equivalent vehicles vs saturation": "more",
    "Freight stock growth assumption": "more",
    "Passenger energy growth context": "more",
    "Population": "more",
    "Sales shares (base-year)": "more",   # prefix-matched (title includes year)
    "Sales shares (projected)": "more",   # prefix-matched
    "Retirements by type": "more",
    "Sales / stock ratio": "more",
    "Passenger X-LPV weight calibration": "ultra",
    "Base-year vintage profiles": "more",
    "Base-year survival curves": "more",
    "Stock above target events": "ultra",
    "Stock above target event table": "ultra",
    # --- Module 6 (reconciliation) ---
    "Post-reconciliation vs ESTO target": "less",
    "Spread of stock / mileage / efficiency — pre vs post reconciliation": "less",
    "Average correction factor by fuel": "less",
    "Scalar distributions": "less",
    "Device share by drive/fuel": "more",
    "Final fuel allocation share by vehicle type and drive": "more",  # prefix-matched
    "Final fuel energy by vehicle type and drive": "ultra",           # prefix-matched
    "Adjustment scalars by branch": "ultra",
    "Plug-in hybrid utilisation back-check": "ultra",
    # --- Module 7 (simulated outputs) ---
    "Energy": "less",
    "Stock share": "less",
    "Sales share": "more",
    "Stock": "more",
    "Vehicle-km": "more",
    "Simulation minus LEAP energy": "ultra",
    # --- Workflow summary ---
    "Workflow timing": "ultra",
}


def _chart_density_level(title: str) -> str:
    """Return the density level for a chart title (exact match, then prefix match)."""
    if title in _CHART_DENSITY:
        return _CHART_DENSITY[title]
    for key, level in _CHART_DENSITY.items():
        if title.startswith(key):
            return level
    return "more"

_ROAD_MODEL_OVERVIEW_HREF = "/road-model-docs/road_transport_model_overview.md"
_ROAD_MODEL_GUIDE_HREF = "/road-model-docs/road_transport_model_methodology.md"
_ROAD_MODEL_DETAILED_HREF = "/road-model-docs/road_transport_model_modeller_guide.md"

_CSS = """
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;margin:0;padding:0;background:#f5f5f5;color:#333}
header{background:#1a237e;color:white;padding:12px 24px;display:flex;align-items:center;gap:20px;flex-wrap:wrap}
header h1{margin:0;font-size:1.1rem;font-weight:600;white-space:nowrap}
nav{display:flex;gap:5px;flex-wrap:wrap}
nav a{color:#bbdefb;text-decoration:none;padding:4px 10px;border-radius:4px;font-size:.82rem}
nav a:hover,nav a.active{background:rgba(255,255,255,.2);color:white}
.page-wrap{max-width:1760px;margin:0 auto}
.page-title{padding:20px 24px 4px;font-size:1.35rem;font-weight:600;color:#1a237e}
.page-desc{padding:0 24px 16px;color:#666;font-size:.9rem}
.scenario-control{display:flex;align-items:center;gap:8px;margin:0 20px 16px;padding:10px 12px;background:white;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,.1);width:max-content;max-width:calc(100% - 40px)}
.scenario-control label{font-size:.82rem;font-weight:700;color:#1a237e;white-space:nowrap}
.scenario-select{font-size:.86rem;border:1px solid #d7dbe7;border-radius:6px;background:white;color:#263238;padding:5px 28px 5px 8px;min-width:150px}
.scenario-hidden{display:none!important}
.intro-card{background:white;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,.12);margin:8px 20px 18px;padding:16px}
.intro-card h3{margin:0 0 10px 0;color:#1a237e;font-size:1rem}
.intro-card p,.intro-card li{font-size:.9rem;color:#4a4a4a;line-height:1.55}
.intro-card ul{margin:8px 0 0 18px;padding:0}
.module-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:14px;padding:0 20px 22px}
.module-card{background:white;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,.12);padding:14px}
.module-btn{display:inline-block;background:#1a237e;color:white;text-decoration:none;padding:7px 11px;border-radius:6px;font-size:.88rem;font-weight:600;margin-bottom:8px}
.module-btn:hover{background:#2a3796}
.module-desc{font-size:.88rem;color:#555;line-height:1.45}
.doc-link{display:inline-block;margin-top:10px;color:#1a237e;font-size:.88rem;font-weight:600;text-decoration:none}
.doc-link:hover{text-decoration:underline}
.diagram-grid{display:grid;grid-template-columns:minmax(0,1fr);gap:16px;padding:0 20px 40px;max-width:1680px;margin:0 auto}
.diagram-card{background:white;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,.12);padding:16px}
.diagram-card--wide{width:100%}
.diagram-title{font-size:.9rem;font-weight:600;color:#444;margin-bottom:8px}
.diagram-caption{font-size:.85rem;color:#666;line-height:1.45;margin-top:8px;font-style:italic}
.diagram-card img{display:block;width:100%;height:auto;border-radius:6px;border:1px solid #e5e5e5}
.charts-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:20px;padding:0 20px 40px}
.chart-card{background:white;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,.12);padding:14px;overflow:hidden;min-width:0}
.chart-card--wide{grid-column:1/-1}
.charts-pair{grid-column:1/-1;display:grid;grid-template-columns:1fr 1fr;gap:20px}
.chart-title{font-size:1.15rem;font-weight:700;color:#1a237e;margin-bottom:6px;text-align:center}
.chart-caption{font-size:.84rem;color:#666;line-height:1.45;margin:4px 0 8px}
.chart-caption p{margin:4px 0 8px}
.chart-subtitle{font-size:.98rem!important;color:#263238!important;font-weight:700;text-align:center;margin:2px 0 8px!important}
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:10px 0 4px}
.kpi-item{border:1px solid #e4e7ef;border-radius:8px;background:#fafbff;padding:9px 10px;min-width:0}
.kpi-item span{display:block;font-size:.76rem;color:#667085;line-height:1.25;margin-bottom:4px}
.kpi-item strong{display:block;font-size:1rem;color:#263238;font-weight:700;line-height:1.2}
.interpretation-note{font-size:.88rem;line-height:1.5;color:#3f4d5a;background:#f8fafc;border-left:4px solid #1a237e;border-radius:6px;margin:10px 0 12px;padding:10px 12px}
.details-panel{border:1px solid #e0e4ec;border-radius:8px;background:#fbfcff;margin-top:10px;padding:10px 12px}
.details-panel summary{cursor:pointer;color:#1a237e;font-weight:700;font-size:.9rem}
.details-panel p{font-size:.86rem;color:#555;line-height:1.45;margin:10px 0}
.chart-card .plotly-graph-div,.chart-card .js-plotly-plot,.chart-card .plot-container,.chart-card .svg-container{width:100%!important;max-width:100%!important}
.chart-card .plotly-graph-div{min-height:340px}
.chart-card--wide .plotly-graph-div{min-height:400px}
.no-data{padding:40px 24px;color:#999;font-style:italic}
.alert{padding:12px 20px;margin:0 20px 16px;border-radius:6px;font-size:.9rem;line-height:1.5}
.alert--ok{background:#e8f5e9;color:#1b5e20;border-left:4px solid #4caf50}
.alert--warn{background:#fff3e0;color:#e65100;border-left:4px solid #ff6d00}
.alert--fail{background:#ffebee;color:#b71c1c;border-left:4px solid #e53935}
footer{text-align:center;padding:20px;color:#aaa;font-size:.78rem}
.module-grid--overview{grid-template-columns:repeat(6,1fr)}
@media (max-width:1200px){
.module-grid--overview{grid-template-columns:repeat(3,1fr)}
}
@media (max-width:900px){
.charts-grid{grid-template-columns:minmax(0,1fr);gap:16px;padding:0 16px 28px}
.charts-pair{grid-template-columns:minmax(0,1fr)}
.module-grid{grid-template-columns:minmax(0,1fr);gap:12px;padding:0 16px 16px}
.module-grid--overview{grid-template-columns:minmax(0,1fr)}
.diagram-grid{grid-template-columns:minmax(0,1fr);gap:12px;padding:0 16px 28px}
.intro-card{margin:8px 16px 14px;padding:14px}
.page-title{padding:18px 16px 4px}
.page-desc,.alert{margin-left:16px;margin-right:16px;padding-left:0;padding-right:0}
.scenario-control{margin-left:16px;margin-right:16px;max-width:calc(100% - 32px)}
}
.density-toggle{display:flex;align-items:center;gap:4px;margin-left:auto}
.density-label{font-size:.78rem;color:#bbdefb;margin-right:2px;white-space:nowrap}
.density-btn{padding:3px 11px;border:1px solid rgba(255,255,255,.3);border-radius:4px;background:rgba(255,255,255,.1);color:#bbdefb;cursor:pointer;font-size:.78rem;line-height:1.4}
.density-btn:hover{background:rgba(255,255,255,.2);color:white}
.density-btn.is-active{background:rgba(255,255,255,.9);color:#1a237e;border-color:rgba(255,255,255,.9);font-weight:600}
"""

_RESIZE_SCRIPT = """
<script>
(function(){
    var resizeTimer = null;
    var rafHandle = null;
    var resizeObserver = null;

    function getPlotlyGraphDivs() {
        return Array.prototype.slice.call(document.querySelectorAll('.chart-card .plotly-graph-div'));
    }

    function resizeAllPlots() {
        if (!window.Plotly || !window.Plotly.Plots || !window.Plotly.Plots.resize) {
            return;
        }
        getPlotlyGraphDivs().forEach(function(el){
            if (!el || !el.isConnected) return;
            if (el.offsetParent === null) return;
            try {
                window.Plotly.Plots.resize(el);
            } catch (_err) {
                // no-op: chart may still be initializing
            }
        });
    }

    function scheduleResize(delayMs) {
        if (resizeTimer) {
            window.clearTimeout(resizeTimer);
        }
        resizeTimer = window.setTimeout(function(){
            if (rafHandle) {
                window.cancelAnimationFrame(rafHandle);
            }
            rafHandle = window.requestAnimationFrame(function(){
                resizeAllPlots();
            });
        }, delayMs || 0);
    }

    function setupObservers() {
        if (!('ResizeObserver' in window) || resizeObserver) return;
        resizeObserver = new ResizeObserver(function(){
            scheduleResize(20);
        });

        document.querySelectorAll('.chart-card').forEach(function(card){
            resizeObserver.observe(card);
        });
    }

    window.addEventListener('load', function(){
        scheduleResize(0);
        scheduleResize(120);
        scheduleResize(400);
        scheduleResize(1000);
        setupObservers();
    });

    window.addEventListener('resize', function(){ scheduleResize(50); });
    window.addEventListener('orientationchange', function(){ scheduleResize(80); });
    window.addEventListener('pageshow', function(){ scheduleResize(50); });

    document.addEventListener('visibilitychange', function(){
        if (!document.hidden) {
            scheduleResize(40);
        }
    });

    if (document.fonts && document.fonts.ready) {
        document.fonts.ready.then(function(){ scheduleResize(80); });
    }
})();
</script>
"""

_DENSITY_SCRIPT = """
<script>
(function () {
    var KEY = 'road_dashboard_density';
    var DEFAULT = 'less';
    var LEVELS = ['less', 'more', 'ultra'];

    function applyDensity(level) {
        var levelIdx = LEVELS.indexOf(level);
        document.querySelectorAll('[data-density]').forEach(function (el) {
            var elIdx = LEVELS.indexOf(el.getAttribute('data-density'));
            el.style.display = elIdx <= levelIdx ? '' : 'none';
        });
        document.querySelectorAll('.charts-pair').forEach(function (pair) {
            var anyVisible = Array.from(pair.children).some(function (c) {
                return c.style.display !== 'none' && !c.classList.contains('scenario-hidden');
            });
            pair.style.display = anyVisible ? '' : 'none';
        });
        document.querySelectorAll('.density-btn').forEach(function (btn) {
            btn.classList.toggle('is-active', btn.dataset.level === level);
        });
        try { localStorage.setItem(KEY, level); } catch (e) {}
    }

    document.addEventListener('DOMContentLoaded', function () {
        var saved;
        try { saved = localStorage.getItem(KEY); } catch (e) {}
        applyDensity(saved && LEVELS.indexOf(saved) !== -1 ? saved : DEFAULT);
        document.querySelectorAll('.density-btn').forEach(function (btn) {
            btn.addEventListener('click', function () { applyDensity(btn.dataset.level); });
        });
    });
})();
</script>
"""

_SCENARIO_SCRIPT = """
<script>
(function () {
    function resizeVisiblePlots() {
        if (!window.Plotly || !window.Plotly.Plots || !window.Plotly.Plots.resize) return;
        document.querySelectorAll('.chart-card .plotly-graph-div').forEach(function (el) {
            if (el.offsetParent === null) return;
            try { window.Plotly.Plots.resize(el); } catch (_err) {}
        });
    }

    function updatePairs() {
        document.querySelectorAll('.charts-pair').forEach(function (pair) {
            var anyVisible = Array.from(pair.children).some(function (card) {
                return !card.classList.contains('scenario-hidden') && card.style.display !== 'none';
            });
            pair.style.display = anyVisible ? '' : 'none';
        });
    }

    function applyScenario(scenario) {
        document.querySelectorAll('[data-scenario]').forEach(function (card) {
            card.classList.toggle('scenario-hidden', card.getAttribute('data-scenario') !== scenario);
        });
        updatePairs();
        window.setTimeout(resizeVisiblePlots, 40);
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('.scenario-select').forEach(function (select) {
            if (!select.value && select.options.length) select.value = select.options[0].value;
            applyScenario(select.value);
            select.addEventListener('change', function () { applyScenario(select.value); });
        });
    });
})();
</script>
"""

_MODULE_META: dict[str, tuple[str, str]] = {
    "index": ("Overview", ""),
    "module1": ("Inputs & base-year branches", "Module 1 and 2 diagnostics: default/original input counts, branch coverage and base-year metric distributions."),
    "module2": ("Module 2 — Base-year branches", "Branch count heatmap and metric distributions for the base-year branch table (T4)."),
    "module3": ("Stocks, sales & turnover", "Module 3, 4 and 5 diagnostics: stock target pathways, motorisation envelope, sales and turnover flows, vintages and drive-type sales shares."),
    "module3_post_reconciliation": ("Post-reconciliation stocks & turnover", "Charts whose stock-target or turnover values change after Module 6 re-anchors stock trajectories to reconciled base-year stock."),
    "module4": ("Module 4 — Sales & turnover", "New sales, stock trajectories, vehicle retirements and base-year vintage profiles from the fleet turnover module."),
    "module5": ("Module 5 — Sales shares", "Drive-type sales shares over the projection horizon by vehicle type, showing technology transition trajectories."),
    "module6": ("Module 6 — LEAP handoff & reconciliation", "Fuel reconciliation diagnostics (ESTO vs model), reconciliation scalars, ECF by fuel, device shares and allocation concentration."),
    "module7": ("Module 7 — Simulated outputs", "Python simulation of what LEAP might produce: stock, vehicle-km, energy by transport type, fuel energy mix, drive-type breakdowns, and comparison with LEAP energy."),
    "workflow_summary": ("Model outputs — what the road model sends to LEAP", "Key road model outputs sent directly to LEAP: new sales, stock trajectories, reconciliation scalars, and base-year fuel allocation. These are the actual model results. Module 7 projections are excluded — they simulate what LEAP might produce using additional assumptions about sales shares and fleet turnover that are not the same as what LEAP uses."),
}


def _dashboard_diagram_source(filename: str) -> Path | None:
    """Return the Path to a diagram under docs/new model, if present."""
    repo_root = Path(__file__).resolve().parents[2]
    diagram = repo_root / "docs" / "new model" / filename
    return diagram if diagram.exists() else None


def _default_shared_dashboard_assets_dir(dashboard_dir: Path) -> Path:
    """Return the common asset directory for economy dashboard pages."""
    if dashboard_dir.name.startswith("dashboard") and dashboard_dir.parent.name == "diagnostics":
        return dashboard_dir.parents[2] / "shared" / "dashboard_assets"
    return dashboard_dir / "shared_assets"


def _html_relative_path(from_dir: Path, to_path: Path) -> str:
    """Return a browser-friendly relative path between two local paths."""
    return Path(os.path.relpath(to_path, start=from_dir)).as_posix()


_INDEX_CARD_DESCS: dict[str, str] = {
    "module1": "Check the base-year inputs, defaults, branch coverage, and key source data.",
    "module3": "Review stock pathways, sales, retirements, vintages, and drive-type transitions.",
    "module6": "Compare modelled fuel use with ESTO and inspect the reconciliation adjustments.",
    "module3_post_reconciliation": "Check how stock and stock growth changed after the model was re-anchored to reconciled base-year stock levels.",
    "module7": "Review the Python simulation of likely LEAP outputs: stock, travel, energy, fuels, and drive types.",
    "workflow_summary": "Review the actual road model outputs sent to LEAP: sales, stocks, reconciliation scalars, and fuel allocation. No Module 7 simulations.",
}


def _index_extra_html(
    out_dir: Path | None = None,
    shared_assets_dir: Path | None = None,
) -> str:
    """Build rich overview content for index page (module guide + system diagrams).

    If *shared_assets_dir* is provided, diagram PNGs are copied there once and
    referenced from each economy page with relative paths.
    """
    import shutil

    module_cards: list[str] = []
    for href, label in _NAV_LINKS[1:]:
        key = href.replace(".html", "")
        desc = _INDEX_CARD_DESCS.get(key, _MODULE_META.get(key, (label, ""))[1])
        module_cards.append(
            f'<div class="module-card">'
            f'<a class="module-btn" href="{href}">{label}</a>'
            f'<div class="module-desc">{desc}</div>'
            f'</div>'
        )

    _DIAGRAMS = [
        (
            "End-to-end road model workflow 8062026.png",
            "end_to_end_road_model_workflow.png",
            "Road model workflow & systems",
            "Primary reference for the full end-to-end workflow. Some implementation detail is not shown.",
        ),
        (
            "Road transport model — researcher detail.png",
            "road_transport_model_researcher_detail.png",
            "Simplified illustration of the Road transport model",
            "More simplified illustration of the modelling workflow.",
        ),
    ]

    diagrams: list[str] = []
    for src_name, dest_name, title, caption in _DIAGRAMS:
        src = _dashboard_diagram_source(src_name)
        if src is None:
            continue
        if shared_assets_dir is not None:
            shared_assets_dir.mkdir(parents=True, exist_ok=True)
            dest = shared_assets_dir / dest_name
            shutil.copy2(src, dest)
            img_src = _html_relative_path(out_dir, dest) if out_dir is not None else dest.resolve().as_uri()
        elif out_dir is not None:
            img_src = _html_relative_path(out_dir, src)
        else:
            img_src = src.resolve().as_uri()
        diagrams.append(
            '<div class="diagram-card diagram-card--wide">'
            f'<div class="diagram-title">{title}</div>'
            f'<img src="{img_src}" alt="{title} diagram">'
            f'<div class="diagram-caption">{caption}</div>'
            '</div>'
        )

    overview = (
        '<div class="intro-card">'
        '<h3>Overview</h3>'
        '<p>This dashboard is a quality-check guide for the road model. It helps you move through the modelling outputs in the same order that it is completed, to help you better understand the model itself too.</p>'
        '<p style="margin:8px 0 4px 0;font-size:.9rem;color:#4a4a4a"><b>Recommended review order:</b> '
        'Inputs &amp; branches → Stocks &amp; sales → Reconciliation → Post-Reconciliation stocks → Outputs → Summary</p>'
        f'<div style="display:flex;flex-wrap:wrap;gap:12px 16px;align-items:center;margin-top:10px">'
        f'<a class="doc-link" href="{_ROAD_MODEL_OVERVIEW_HREF}" target="_blank" rel="noopener">Open road model overview</a>'
        f'<a class="doc-link" href="{_ROAD_MODEL_GUIDE_HREF}" target="_blank" rel="noopener">Open methodology guide</a>'
        f'<a class="doc-link" href="{_ROAD_MODEL_DETAILED_HREF}" target="_blank" rel="noopener">Open modeller guide</a>'
        f'</div>'
        '</div>'
    )

    module_section = f'<div class="module-grid module-grid--overview">{"".join(module_cards)}</div>'
    diagrams_section = f'<div class="diagram-grid">{"".join(diagrams)}</div>' if diagrams else ""
    return overview + module_section + diagrams_section


def _nav_html(active_page: str = "") -> str:
    items = [
        f'<a href="{href}"{"  class=\"active\"" if href == active_page else ""}>{label}</a>'
        for href, label in _NAV_LINKS
    ]
    return "\n".join(items)


def _build_html_page(
    page_title: str,
    page_desc: str,
    figures: list[tuple[str, Any]],
    economy: str = "",
    active_page: str = "",
    extra_body: str = "",
) -> str:
    """Build a full standalone HTML page with embedded Plotly charts."""
    economy_label = f" — {economy}" if economy else ""

    if figures:
        rendered: list[str] = []
        half_buffer: list[str] = []
        scenario_labels: list[str] = []
        seen_scenarios: set[str] = set()
        for idx, item in enumerate(figures):
            title, fig = item[0], item[1]
            metadata = item[-1] if len(item) > 2 and isinstance(item[-1], dict) else {}
            scenario_label = str(metadata.get("scenario", "")).strip()
            scenario_attr = f' data-scenario="{escape(scenario_label)}"' if scenario_label else ""
            if scenario_label and scenario_label not in seen_scenarios:
                seen_scenarios.add(scenario_label)
                scenario_labels.append(scenario_label)
            half = False
            explicit_wide = False
            caption = ""
            after_html = ""
            if len(item) > 2:
                if isinstance(item[2], bool):
                    explicit_wide = bool(item[2])
                    if len(item) > 3 and isinstance(item[3], str):
                        caption = item[3]
                    if len(item) > 4 and isinstance(item[4], str):
                        after_html = item[4]
                elif item[2] == "half":
                    half = True
                    if len(item) > 3 and isinstance(item[3], str):
                        caption = item[3]
                    if len(item) > 4 and isinstance(item[4], str):
                        after_html = item[4]
                elif isinstance(item[2], str):
                    caption = item[2]
                    if len(item) > 3 and isinstance(item[3], str):
                        after_html = item[3]

            wide = not half and _should_render_wide(fig, explicit_wide=explicit_wide)
            fig = _apply_dashboard_layout(fig, wide=wide)
            include_js: Any = "cdn" if idx == 0 else False
            fig_html = pio.to_html(
                fig, full_html=False,
                include_plotlyjs=include_js,
                config={"responsive": True, "displaylogo": False},
            )
            caption_html = f'<div class="chart-caption">{caption}</div>' if caption else ""
            density = _chart_density_level(title)
            title_html = escape(str(title))
            card_html = f'<div class="chart-card" data-density="{density}"{scenario_attr}><div class="chart-title">{title_html}</div>{caption_html}{fig_html}{after_html}</div>'

            if half:
                half_buffer.append(card_html)
                if len(half_buffer) == 2:
                    rendered.append(f'<div class="charts-pair">{"".join(half_buffer)}</div>')
                    half_buffer = []
            else:
                if half_buffer:
                    rendered.append(f'<div class="charts-pair">{"".join(half_buffer)}</div>')
                    half_buffer = []
                css = "chart-card chart-card--wide" if wide else "chart-card"
                rendered.append(
                    f'<div class="{css}" data-density="{density}"{scenario_attr}><div class="chart-title">{title_html}</div>{caption_html}{fig_html}{after_html}</div>'
                )

        if half_buffer:
            rendered.append(f'<div class="charts-pair">{"".join(half_buffer)}</div>')

        scenario_control = ""
        if len(scenario_labels) > 1:
            options = "".join(
                f'<option value="{escape(label)}">{escape(label)}</option>'
                for label in scenario_labels
            )
            scenario_control = (
                '<div class="scenario-control">'
                '<label for="scenario-select">Scenario</label>'
                f'<select id="scenario-select" class="scenario-select">{options}</select>'
                '</div>'
            )
        charts_section = scenario_control + f'<div class="charts-grid">{"".join(rendered)}</div>'
    else:
        charts_section = ""

    body_content = extra_body + charts_section if (extra_body or charts_section) else (
        '<p class="no-data">No data available for this module in the current workflow run.</p>'
    )

    return (
        f'<!DOCTYPE html><html lang="en">\n'
        f'<head><meta charset="UTF-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{page_title}{economy_label}</title>'
        f'<style>{_CSS}</style></head>\n'
        f'<body>\n'
        f'<header><h1>Road Model QA Dashboard{economy_label}</h1>'
        f'<nav>{_nav_html(active_page)}</nav>'
        f'<div class="density-toggle">'
        f'<span class="density-label">Detail:</span>'
        f'<button class="density-btn" data-level="less">Less</button>'
        f'<button class="density-btn" data-level="more">More</button>'
        f'<button class="density-btn" data-level="ultra">Ultra</button>'
        f'</div></header>\n'
        + f'<div class="page-wrap">'
        + f'<div class="page-title">{page_title}</div>'
        + (f'<div class="page-desc">{page_desc}</div>\n' if page_desc else "")
        + f'{body_content}\n'
        + f'<footer>Generated by leap_road_model — road_workflow diagnostic dashboard</footer>\n'
        + f'{_RESIZE_SCRIPT}\n'
        + f'{_DENSITY_SCRIPT}\n'
        + f'{_SCENARIO_SCRIPT}\n'
        + f'</div>'
        + f'</body></html>'
    )


def _scenario_sort_key(label: str) -> tuple[int, str]:
    """Keep Target first, then sort the remaining configured scenario labels."""
    return (0 if label == "Target" else 1, label)


def _scenario_labels_from_frames(*frames: Any) -> list[str]:
    """Collect projection scenario labels from output frames."""
    labels: set[str] = set()
    for frame in frames:
        if not isinstance(frame, pd.DataFrame) or "scenario" not in frame.columns:
            continue
        values = frame["scenario"].dropna().astype(str).str.strip()
        labels.update(label for label in values if label and label != "Current Accounts")
    return sorted(labels, key=_scenario_sort_key)


def _filter_frame_scenario(frame: Any, scenario: str) -> Any:
    """Return one scenario slice when the frame has a scenario column."""
    if not isinstance(frame, pd.DataFrame) or "scenario" not in frame.columns:
        return frame
    return frame[frame["scenario"].astype(str) == str(scenario)].copy()


def _with_scenario(
    figures: list[tuple[str, Any]],
    scenario: str,
) -> list[tuple[str, Any]]:
    """Attach dashboard-only scenario metadata to figure tuples."""
    tagged: list[tuple[str, Any]] = []
    for item in figures:
        if len(item) > 2 and isinstance(item[-1], dict):
            metadata = dict(item[-1])
            metadata["scenario"] = scenario
            tagged.append((*item[:-1], metadata))
        else:
            tagged.append((*item, {"scenario": scenario}))
    return tagged


def _filter_outputs_scenario(workflow_outputs: dict[str, Any], scenario: str) -> dict[str, Any]:
    """Return a workflow output dict where scenario-aware frames are sliced."""
    filtered: dict[str, Any] = {}
    for key, value in workflow_outputs.items():
        filtered[key] = _filter_frame_scenario(value, scenario)
    return filtered


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def write_module_pages(
    workflow_outputs: dict[str, Any],
    dashboard_dir: str | Path,
    economy: str = "",
    shared_assets_dir: str | Path | None = None,
) -> list[Path]:
    """Write workflow-stage interactive HTML dashboard pages plus an index page.

    Args:
        workflow_outputs: dict returned by ``run_with_config()`` (or a subset).
            Keys used: ``module1_merged``, ``T4``–``T12``, ``T13``, ``T13_fuel``,
            ``timings``.
        dashboard_dir: Directory to write HTML files into (created if absent).
        economy: Economy code shown in the page header (e.g. ``"12_NZ"``).
        shared_assets_dir: Optional common directory for non-economy-specific
            dashboard assets. Defaults to ``results/shared/dashboard_assets``
            when dashboard_dir follows ``results/<economy>/diagnostics/dashboard``.

    Returns:
        List of :class:`~pathlib.Path` objects for the written HTML files.
    """
    if not _can_plot():
        return []

    out = Path(dashboard_dir)
    out.mkdir(parents=True, exist_ok=True)
    shared_assets = Path(shared_assets_dir) if shared_assets_dir is not None else _default_shared_dashboard_assets_dir(out)
    for old_page in ("module2.html", "module4.html", "module5.html"):
        (out / old_page).unlink(missing_ok=True)
    written: list[Path] = []

    def _filter_figures_by_title(figs: list[tuple[str, Any]], titles: set[str]) -> list[tuple[str, Any]]:
        return [item for item in figs if item and item[0] in titles]

    def _write(filename: str, figs: list[tuple[str, Any]], extra: str = "") -> None:
        key = filename.replace(".html", "")
        title, desc = _MODULE_META.get(key, (key, ""))
        html = _build_html_page(title, desc, figs, economy=economy,
                                active_page=filename, extra_body=extra)
        p = out / filename
        p.write_text(html, encoding="utf-8")
        written.append(p)

    # Combined workflow-stage pages
    m1_df = workflow_outputs.get("module1_merged")
    m1_raw = workflow_outputs.get("module1_raw_df")
    input_figures = module1_figures(m1_df, raw_df=m1_raw) if m1_df is not None else []
    input_figures.extend(module2_figures(workflow_outputs.get("T4")))
    m1_summary = _module1_summary_html(m1_df, raw_df=m1_raw) if m1_df is not None else ""
    _write("module1.html", input_figures, extra=m1_summary)

    t5_pre = workflow_outputs.get("T5_pre_reconciliation")
    t5_post = workflow_outputs.get("T5_post_reconciliation")
    t6_pre = workflow_outputs.get("T6_pre_reconciliation")
    t6_post = workflow_outputs.get("T6_post_reconciliation")
    t6v_pre = workflow_outputs.get("T6v_pre_reconciliation")
    t6v_post = workflow_outputs.get("T6v_post_reconciliation")

    t5_for_main = t5_pre if isinstance(t5_pre, pd.DataFrame) and not t5_pre.empty else workflow_outputs.get("T5")
    t6 = t6_pre if isinstance(t6_pre, pd.DataFrame) and not t6_pre.empty else workflow_outputs.get("T6")
    t6v = t6v_pre if isinstance(t6v_pre, pd.DataFrame) and not t6v_pre.empty else workflow_outputs.get("T6v")
    t7 = workflow_outputs.get("T7")
    t7f = workflow_outputs.get("T7f")
    stock_sales_scenarios = _scenario_labels_from_frames(t5_for_main, t6, t6v, t7, t7f)
    stock_sales_figures: list[tuple[str, Any]] = []
    if stock_sales_scenarios:
        for scenario in stock_sales_scenarios:
            scenario_figures = module3_figures(
                _filter_frame_scenario(t5_for_main, scenario),
                population=workflow_outputs.get("population"),
            )
            scenario_figures.extend(module4_figures(
                _filter_frame_scenario(t6, scenario),
                _filter_frame_scenario(t6v, scenario),
            ))
            scenario_figures.extend(module5_figures(
                _filter_frame_scenario(t7, scenario),
                _filter_frame_scenario(t7f, scenario),
            ))
            stock_sales_figures.extend(_with_scenario(scenario_figures, scenario))
    else:
        stock_sales_figures = module3_figures(
            t5_for_main,
            population=workflow_outputs.get("population"),
        )
        stock_sales_figures.extend(module4_figures(t6, t6v))
        stock_sales_figures.extend(module5_figures(t7, t7f))
    _write("module3.html", stock_sales_figures)

    post_stock_figures: list[tuple[str, Any]] = []
    post_stock_scenarios = _scenario_labels_from_frames(t5_post, t6_post, t6v_post, workflow_outputs.get("T13"))
    post_titles = {
        "Target stock trajectories",
        "Freight stock growth assumption",
        "Passenger X-LPV-equivalent vehicles vs saturation",
        "Passenger X-LPV weight calibration",
        "Passenger energy growth context",
    }
    if post_stock_scenarios:
        for scenario in post_stock_scenarios:
            scenario_figures: list[tuple[str, Any]] = []
            t5_post_s = _filter_frame_scenario(t5_post, scenario)
            if isinstance(t5_post_s, pd.DataFrame) and not t5_post_s.empty:
                scenario_figures.extend(_filter_figures_by_title(
                    module3_figures(
                        t5_post_s,
                        population=workflow_outputs.get("population"),
                        show_freight_energy_context=True,
                        t13=_filter_frame_scenario(workflow_outputs.get("T13"), scenario),
                        show_passenger_energy_context=True,
                        gdp=workflow_outputs.get("gdp"),
                        esto_road_energy_pj=workflow_outputs.get("esto_road_energy_pj"),
                    ),
                    post_titles,
                ))
            t6_post_s = _filter_frame_scenario(t6_post, scenario)
            if isinstance(t6_post_s, pd.DataFrame) and not t6_post_s.empty:
                scenario_figures.extend(module4_figures(
                    t6_post_s,
                    _filter_frame_scenario(t6v_post, scenario) if isinstance(t6v_post, pd.DataFrame) else pd.DataFrame(),
                ))
            post_stock_figures.extend(_with_scenario(scenario_figures, scenario))
    else:
        if isinstance(t5_post, pd.DataFrame) and not t5_post.empty:
            post_stock_figures.extend(_filter_figures_by_title(
                module3_figures(
                    t5_post,
                    population=workflow_outputs.get("population"),
                    show_freight_energy_context=True,
                    t13=workflow_outputs.get("T13"),
                    show_passenger_energy_context=True,
                    gdp=workflow_outputs.get("gdp"),
                    esto_road_energy_pj=workflow_outputs.get("esto_road_energy_pj"),
                ),
                post_titles,
            ))
        if isinstance(t6_post, pd.DataFrame) and not t6_post.empty:
            post_stock_figures.extend(module4_figures(
                t6_post,
                t6v_post if isinstance(t6v_post, pd.DataFrame) else pd.DataFrame(),
            ))
    _write("module3_post_reconciliation.html", post_stock_figures)

    t12 = workflow_outputs.get("T12")
    recon_alert = _reconciliation_alert_html(t12)

    m6_sub = {k: workflow_outputs.get(k) for k in ("T4", "T8", "T9", "T10", "T12", "T12_phev")}
    m6_scenarios = _scenario_labels_from_frames(*m6_sub.values())
    if m6_scenarios:
        m6_figures: list[tuple[str, Any]] = []
        for scenario in m6_scenarios:
            m6_sub_scenario = {k: _filter_frame_scenario(v, scenario) for k, v in m6_sub.items()}
            m6_figures.extend(_with_scenario(module6_figures(m6_sub_scenario), scenario))
    else:
        m6_figures = module6_figures(m6_sub)
    _write("module6.html", m6_figures, extra=recon_alert)

    m7_sub = {k: workflow_outputs.get(k) for k in ("T13", "T13_fuel")}
    split_alert = _transport_split_alert_html(workflow_outputs.get("T13"))
    m7_scenarios = _scenario_labels_from_frames(*m7_sub.values(), workflow_outputs.get("T7f"))
    if m7_scenarios:
        m7_figures: list[tuple[str, Any]] = []
        for scenario in m7_scenarios:
            m7_sub_scenario = {k: _filter_frame_scenario(v, scenario) for k, v in m7_sub.items()}
            scenario_figures = module7_figures(
                m7_sub_scenario,
                t7f=_filter_frame_scenario(workflow_outputs.get("T7f"), scenario),
                t4=workflow_outputs.get("T4"),
                t9=_filter_frame_scenario(workflow_outputs.get("T9"), scenario),
            )
            m7_figures.extend(_with_scenario(scenario_figures, scenario))
    else:
        m7_figures = module7_figures(
            m7_sub,
            t7f=workflow_outputs.get("T7f"),
            t4=workflow_outputs.get("T4"),
            t9=workflow_outputs.get("T9"),
        )
    _write(
        "module7.html",
        m7_figures,
        extra=_MODULE7_NOTE_HTML + split_alert,
    )

    summary_scenarios = _scenario_labels_from_frames(
        t5_for_main, t5_post, t6, t6v, t7, t7f,
        *m6_sub.values(),
        *m7_sub.values(),
    )
    if summary_scenarios:
        summary_figures: list[tuple[str, Any]] = []
        for scenario in summary_scenarios:
            scenario_outputs = _filter_outputs_scenario(workflow_outputs, scenario)
            scenario_outputs["T4"] = workflow_outputs.get("T4")
            summary_figures.extend(_with_scenario(workflow_summary_figures(scenario_outputs), scenario))
    else:
        summary_figures = workflow_summary_figures(workflow_outputs)
    _write("workflow_summary.html", summary_figures, extra=recon_alert)

    # Index page — module guide + system diagrams
    index_extra = _index_extra_html(out_dir=out, shared_assets_dir=shared_assets)
    _write("index.html", [], extra=index_extra)

    return written
