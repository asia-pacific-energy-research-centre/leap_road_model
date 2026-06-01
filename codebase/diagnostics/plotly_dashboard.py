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

import math
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

_COLOURS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
]
_TEMPLATE = "plotly_white"

# Fuel colours aligned with the leap_dashboard product_color_legend (v3 JSON).
_FUEL_COLOURS: dict[str, str] = {
    "Motor gasoline": "#842482",
    "Gas and diesel oil": "#DB4F29",
    "Petroleum products": "#842482",
    "Hydrogen": "#F67AA3",
    "Hydrogen-based fuels": "#D46FA0",
    "Electricity": "#FFD757",
    "Biogasoline": "#f09417",
    "Biodiesel": "#304A1E",
    "Biojet kerosene": "#9ACD32",
    "Natural gas": "#0070C0",
    "Gas": "#0070C0",
    "LNG": "#A20042",
    "LPG": "#4AA8A1",
    "Biogas": "#00FE73",
    "Efuel": "#8A8A8A",
    "Coal": "#0D0D0D",
    "Nuclear": "#C6188C",
    "Hydro": "#B0D6F0",
    "Solar": "#FFD700",
    "Wind": "#000099",
    "Biomass": "#2E8B57",
    "Others": "#8A8A8A",
}

# Drive-type colours: fossil-grey for ICE, technology colours for ZEVs.
_DRIVE_COLOURS: dict[str, str] = {
    "ICE": "#A6A6A6",
    "BEV": "#FFD757",
    "FCEV": "#F67AA3",
    "PHEV": "#f09417",
    "HEV": "#2E8B57",
}


def _fuel_colour(fuel: str, idx: int) -> str:
    return _FUEL_COLOURS.get(str(fuel), _COLOURS[idx % len(_COLOURS)])


def _drive_colour(drive: str, idx: int) -> str:
    return _DRIVE_COLOURS.get(str(drive), _COLOURS[idx % len(_COLOURS)])


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
        return "Original LEAP export"
    if source_type == "default_input_workbook" or input_source in {"default", "default_filled"}:
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
    for col in ["Default value", "Original LEAP export", "Other model input"]:
        if col not in count_table.columns:
            count_table[col] = 0

    medians = (
        df.groupby(["major_branch", "variable", "source_category"])["value"].median()
        .unstack()
        .reset_index()
    )
    if {"Default value", "Original LEAP export"}.issubset(medians.columns):
        original = pd.to_numeric(medians["Original LEAP export"], errors="coerce")
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
        + table_df["Original LEAP export"]
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
                "Original values",
                "Other inputs",
                "Default vs original median",
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
                table_df["Original LEAP export"].astype(int).tolist(),
                table_df["Other model input"].astype(int).tolist(),
                table_df["default_vs_original_median"].map(_format_pct).tolist(),
            ],
            fill_color="white",
            align="left",
            height=24,
        ),
        columnwidth=[2.0, 1.2, 0.9, 0.9, 0.9, 0.8, 1.2],
    )])
    fig.update_layout(**_layout("Module 1 - Default and original values by branch/measure"))
    return fig


def _missing_rows_table(
    df: pd.DataFrame,
    check_cols: list[str],
    display_cols: list[str],
    max_rows: int = 50,
) -> Any | None:
    """Return a table listing rows with missing checked fields."""
    cols_to_check = [c for c in check_cols if c in df.columns]
    if not cols_to_check:
        return None

    missing_mask = df[cols_to_check].isna().any(axis=1)
    missing = df.loc[missing_mask].copy()
    if missing.empty:
        return None

    missing["missing_fields"] = missing[cols_to_check].apply(
        lambda row: ", ".join([col for col, value in row.items() if pd.isna(value)]),
        axis=1,
    )
    shown = missing.head(max_rows)
    cols = [c for c in display_cols if c in shown.columns] + ["missing_fields"]

    fig = go.Figure(data=[go.Table(
        header=dict(values=cols, fill_color="#E8EDF7", align="left"),
        cells=dict(
            values=[shown[col].fillna("").astype(str).tolist() for col in cols],
            fill_color="white",
            align="left",
            height=24,
        ),
    )])
    fig.update_layout(**_layout("Rows with missing required fields"))
    return fig


def module1_figures(merged_inputs: pd.DataFrame) -> list[tuple[str, Any]]:
    """Interactive QA figures for Module 1 LEAP-format base-year inputs."""
    if not _can_plot() or merged_inputs is None or merged_inputs.empty:
        return []

    figs: list[tuple[str, Any]] = []

    source_table = _module1_default_original_table(merged_inputs)
    if source_table is not None:
        figs.append((
            "Default and original values by branch/measure",
            source_table,
            True,
            "Counts base-year values by branch and measure. When both default and original values exist in a group, the last column compares their medians.",
        ))

    missing_table = _missing_rows_table(
        merged_inputs,
        check_cols=[
            "economy", "scenario", "year", "transport_type", "vehicle_type",
            "variable", "value", "unit", "source_type", "source_name",
        ],
        display_cols=[
            "economy", "scenario", "year", "transport_type", "vehicle_type",
            "drive_type", "size", "fuel", "variable",
        ],
    )
    if missing_table is not None:
        figs.append((
            "Rows with missing required input fields",
            missing_table,
            True,
            "Lists input rows missing required fields. Structural blanks such as size/fuel on aggregate rows are not treated as missing here.",
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

    # 2) Source provenance (Module 1 defaults vs researcher-provided rows)
    flag_cols = [c for c in ["stock_source_flag", "mileage_source_flag", "efficiency_source_flag"]
                 if c in t4.columns]
    if flag_cols:
        rows = []
        for col in flag_cols:
            vc = t4[col].fillna("missing").value_counts()
            for flag, count in vc.items():
                rows.append({"metric": col.replace("_source_flag", ""), "source_flag": str(flag), "count": int(count)})
        ff = pd.DataFrame(rows)
        if not ff.empty:
            p = ff.pivot_table(index="metric", columns="source_flag", values="count", aggfunc="sum", fill_value=0)
            fig = go.Figure()
            for flag in p.columns:
                fig.add_trace(go.Bar(name=str(flag), x=p.index.tolist(), y=p[flag].tolist()))
            fig.update_layout(
                **_layout("Module 2 - Value source by metric"),
                barmode="stack", xaxis_title="Metric", yaxis_title="Row count",
            )
            figs.append((
                "Value source by metric",
                fig,
                "Shows the original source category for each metric. Branch-level transformations such as size splitting or vehicle-type broadcasts are shown separately below.",
            ))

    granularity_cols = [c for c in ["stock_granularity", "mileage_granularity", "efficiency_granularity"]
                        if c in t4.columns]
    if granularity_cols:
        rows = []
        for col in granularity_cols:
            metric = col.replace("_granularity", "")
            vc = t4[col].fillna("unknown").value_counts()
            for method, count in vc.items():
                rows.append({"metric": metric, "fill_method": str(method), "count": int(count)})
        gf = pd.DataFrame(rows)
        if not gf.empty:
            p = gf.pivot_table(index="metric", columns="fill_method", values="count", aggfunc="sum", fill_value=0)
            fig = go.Figure()
            for method in p.columns:
                fig.add_trace(go.Bar(name=str(method), x=p.index.tolist(), y=p[method].tolist()))
            fig.update_layout(
                **_layout("Module 2 - Value fill method by metric"),
                barmode="stack", xaxis_title="Metric", yaxis_title="Row count",
            )
            figs.append((
                "Value fill method by metric",
                fig,
                "Shows whether values matched a branch directly, were split across size classes, or were broadcast from a vehicle-type-level input. This is transformation detail, not source provenance.",
            ))

    # 3) Spread of key values, grouped and sorted by vehicle type median
    num_cols = [c for c in ["stock", "mileage_km_per_year", "efficiency_km_per_gj"] if c in t4.columns]
    if num_cols and "vehicle_type" in t4.columns:
        fig = make_subplots(
            rows=1,
            cols=len(num_cols),
            subplot_titles=tuple(num_cols),
            horizontal_spacing=0.07,
        )
        has_any = False
        for i, col in enumerate(num_cols, 1):
            tmp = t4[["vehicle_type", col]].copy()
            tmp[col] = pd.to_numeric(tmp[col], errors="coerce")
            tmp = tmp.dropna(subset=[col])
            if tmp.empty:
                continue
            order = (
                tmp.groupby("vehicle_type")[col]
                .median()
                .sort_values(ascending=False)
                .index
                .tolist()
            )
            for vt in order:
                vals = tmp.loc[tmp["vehicle_type"] == vt, col].tolist()
                if vals:
                    has_any = True
                    fig.add_trace(
                        go.Box(
                            x=[vt] * len(vals),
                            y=vals,
                            name=str(vt),
                            boxpoints=False,
                            showlegend=False,
                            marker_color=_COLOURS[(i - 1) % len(_COLOURS)],
                        ),
                        row=1,
                        col=i,
                    )
            fig.update_xaxes(title_text="Vehicle type (sorted)", tickangle=-30, row=1, col=i)
            fig.update_yaxes(title_text="Value", row=1, col=i)

        if has_any:
            fig.update_layout(**_layout("Module 2 — Spread of stock, mileage and efficiency across branches"))
            figs.append((
                "Spread of stock / mileage / efficiency",
                fig,
                True,
                "Each panel is grouped by vehicle type and sorted by median value (highest to lowest), so branch-level spread is easier to compare.",
            ))

    return figs


# ---------------------------------------------------------------------------
# Module 3 — stock targets
# ---------------------------------------------------------------------------

def module3_figures(t5: pd.DataFrame) -> list[tuple[str, Any]]:
    """Interactive QA figures for Module 3 stock targets (T5)."""
    if not _can_plot() or t5 is None or t5.empty:
        return []

    figs: list[tuple[str, Any]] = []

    req = {"year", "transport_type", "vehicle_type", "target_stock"}
    if req.issubset(t5.columns):
        fig = make_subplots(rows=1, cols=2, subplot_titles=["Passenger", "Freight"])
        for col_idx, tt in enumerate(["passenger", "freight"], 1):
            sub = t5[t5["transport_type"] == tt]
            if sub.empty:
                continue
            for i, (vt, grp) in enumerate(sub.groupby("vehicle_type")):
                series = grp.groupby("year")["target_stock"].sum().sort_index()
                fig.add_trace(
                    go.Scatter(
                        x=series.index.tolist(), y=series.values.tolist(),
                        name=str(vt), mode="lines",
                        line=dict(color=_COLOURS[i % len(_COLOURS)]),
                        legendgroup=str(vt), showlegend=(col_idx == 1),
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
            fig.update_layout(
                **_layout("Module 3 - Passenger X-LPV-equivalent vehicles per 1,000 people"),
                xaxis_title="Year", yaxis_title="X-LPV-equivalent vehicles per 1,000 people",
            )
            figs.append((
                "Passenger X-LPV-equivalent vehicles vs saturation",
                fig,
                "Projected passenger stock converted to X-LPV-equivalent vehicles per 1,000 people, compared with the saturation level.",
            ))

    if {"vehicle_type", "gdp_elasticity_used"}.issubset(t5.columns):
        el = t5[["vehicle_type", "gdp_elasticity_used"]].dropna().drop_duplicates()
        if not el.empty:
            fig = go.Figure(go.Bar(
                x=el["vehicle_type"].tolist(), y=el["gdp_elasticity_used"].tolist(),
                marker_color="#00897B",
            ))
            fig.update_layout(
                **_layout("Module 3 — Freight GDP elasticity by vehicle type"),
                yaxis_title="Elasticity",
            )
            figs.append(("Freight elasticity by vehicle type", fig))

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
            fig.add_trace(go.Scatter(
                x=s.index.tolist(), y=s.values.tolist(), name=str(vt), mode="lines",
                line=dict(color=_COLOURS[i % len(_COLOURS)]),
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
                line=dict(color=_COLOURS[i % len(_COLOURS)]),
            ))
        fig.update_layout(
            **_layout("Module 4 — Stock trajectory by vehicle type"),
            xaxis_title="Year", yaxis_title="Stock",
        )
        figs.append(("Stock trajectory by vehicle type", fig))

    if t6 is not None and not t6.empty and {"year", "natural_retirements", "additional_retirements"}.issubset(t6.columns):
        rr = t6.groupby("year")[["natural_retirements", "additional_retirements"]].sum().sort_index()
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=rr.index.tolist(), y=rr["natural_retirements"].tolist(),
            name="natural", stackgroup="ret", mode="lines",
        ))
        fig.add_trace(go.Scatter(
            x=rr.index.tolist(), y=rr["additional_retirements"].tolist(),
            name="additional", stackgroup="ret", mode="lines",
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
                line=dict(color=_COLOURS[i % len(_COLOURS)]),
            ))
        fig.update_layout(
            **_layout("Module 4 — Base-year vintage profiles"),
            xaxis_title="Age", yaxis_title="Vintage share",
        )
        figs.append(("Base-year vintage profiles", fig))

    if t6 is not None and not t6.empty and {"new_sales", "target_stock", "year"}.issubset(t6.columns):
        tmp = t6.groupby("year")[["new_sales", "target_stock"]].sum().sort_index()
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

        pvt = base_df.pivot_table(
            index="vehicle_type", columns="drive_type",
            values="sales_share", aggfunc="mean", fill_value=0,
        )
        if not pvt.empty:
            non_ice_cols = [c for c in pvt.columns if str(c).upper() != "ICE"]
            order_key = pvt[non_ice_cols].sum(axis=1) if non_ice_cols else pvt.sum(axis=1)
            pvt = pvt.loc[order_key.sort_values(ascending=False).index]

            fig = go.Figure()
            for j, col in enumerate(pvt.columns):
                fig.add_trace(go.Bar(
                    name=str(col), x=pvt.index.tolist(), y=pvt[col].tolist(),
                    marker_color=_COLOURS[j % len(_COLOURS)],
                ))
            fig.update_layout(
                **_layout(f"Module 5 — Sales shares (base-year){base_year_label}"),
                barmode="stack", xaxis_title="Vehicle type", yaxis_title="Sales share",
                yaxis=dict(range=[0, 1.05]),
            )
            figs.append((
                f"Sales shares (base-year){base_year_label}",
                fig,
                True,
                "Vehicle types are sorted by non-ICE share (highest to lowest) so minor transition shares are easier to compare.",
            ))

    # Projected chart (only show when true multi-year projected data exists)
    if t7f is not None and not t7f.empty and {"drive_type", "sales_share", "year"}.issubset(t7f.columns):
        years = pd.to_numeric(t7f["year"], errors="coerce").dropna().astype(int)
        unique_years = sorted(years.unique().tolist())
        if len(unique_years) > 1:
            traj = (
                t7f.pivot_table(
                    index="year", columns="drive_type",
                    values="sales_share", aggfunc="mean", fill_value=0,
                )
                .sort_index()
            )
            if not traj.empty:
                fig = go.Figure()
                for j, col in enumerate(traj.columns):
                    fig.add_trace(go.Scatter(
                        x=traj.index.tolist(), y=traj[col].tolist(),
                        name=str(col), stackgroup="share", mode="lines",
                        line=dict(color=_COLOURS[j % len(_COLOURS)]),
                    ))
                year_range = f" ({unique_years[0]}-{unique_years[-1]})"
                fig.update_layout(
                    **_layout(f"Module 5 — Sales shares (projected){year_range}"),
                    xaxis_title="Year", yaxis_title="Sales share",
                    yaxis=dict(range=[0, 1.05]),
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
    _t8 = module6_outputs.get("T8"); t8 = _t8 if isinstance(_t8, pd.DataFrame) else pd.DataFrame()
    _t9 = module6_outputs.get("T9"); t9 = _t9 if isinstance(_t9, pd.DataFrame) else pd.DataFrame()
    _t10 = module6_outputs.get("T10"); t10 = _t10 if isinstance(_t10, pd.DataFrame) else pd.DataFrame()
    _t12 = module6_outputs.get("T12"); t12 = _t12 if isinstance(_t12, pd.DataFrame) else pd.DataFrame()

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
            agg = agg.loc[ranking.head(14).index.tolist()]
            subplot_specs = [(col, label) for col, label in scalar_specs if col in scalar_cols_for_chart]
            fig = make_subplots(
                rows=2, cols=2,
                subplot_titles=tuple(label for _col, label in subplot_specs),
                horizontal_spacing=0.08,
                vertical_spacing=0.18,
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
                fig.update_xaxes(title_text="Branch (vehicle|drive|fuel)", tickangle=-35, row=r, col=c)
                fig.update_yaxes(title_text="Scalar (1 = unchanged)", row=r, col=c)

            fig.update_layout(
                **_layout("Module 6 - Adjustment scalars by branch (top changing branches)"),
                height=720,
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

    allocation_cols = {"vehicle_type", "drive_type", "fuel", "allocated_branch_fuel_pj"}
    if not t8.empty and allocation_cols.issubset(t8.columns):
        alloc = t8.copy()
        alloc["allocated_branch_fuel_pj"] = pd.to_numeric(
            alloc["allocated_branch_fuel_pj"], errors="coerce"
        ).fillna(0.0)
        alloc["vehicle_drive"] = (
            alloc["vehicle_type"].fillna("unknown")
            + " | "
            + alloc["drive_type"].fillna("unknown")
        )
        heat = (
            alloc.groupby(["vehicle_drive", "fuel"])["allocated_branch_fuel_pj"]
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
                    marker_color=_COLOURS[i % len(_COLOURS)],
                    customdata=heat[fuel].tolist(),
                    hovertemplate=(
                        "Vehicle/drive=%{x}<br>Fuel=" + str(fuel)
                        + "<br>Share=%{y:.1f}%"
                        + "<br>Energy=%{customdata:.2f} PJ<extra></extra>"
                    ),
                ))
            fig.update_layout(
                **_layout("Module 6 - Final fuel allocation share by vehicle type and drive"),
                barmode="stack",
                height=620,
                xaxis_title="Vehicle type | drive",
                yaxis_title="Share of final allocated fuel energy (%)",
                yaxis_range=[0, 100],
                legend_title_text="Fuel",
            )
            figs.append((
                "Final fuel allocation share by vehicle type and drive",
                fig,
                True,
                "Final allocated fuel energy mix after reconciliation. Each bar sums to 100%; fuels with the largest total allocation are stacked from the bottom.",
            ))

    return figs


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
) -> list[tuple[str, Any]]:
    """Interactive QA figures for Module 7 mirror outputs (T13, T13_fuel).

    Args:
        module7_outputs: dict with T13 and T13_fuel DataFrames.
        t7f: Optional T7f future sales shares DataFrame (for sales share by drive type).
    """
    if not _can_plot() or not module7_outputs:
        return []

    figs: list[tuple[str, Any]] = []
    _t13 = module7_outputs.get("T13"); t13 = _t13 if isinstance(_t13, pd.DataFrame) else pd.DataFrame()
    _t13f = module7_outputs.get("T13_fuel"); t13_fuel = _t13f if isinstance(_t13f, pd.DataFrame) else pd.DataFrame()

    if not t13.empty and {"year", "vehicle_type", "mirror_stock"}.issubset(t13.columns):
        fig = go.Figure()
        for i, (vt, grp) in enumerate(t13.groupby("vehicle_type")):
            s = grp.groupby("year")["mirror_stock"].sum().sort_index()
            fig.add_trace(go.Scatter(
                x=s.index.tolist(), y=s.values.tolist(), name=str(vt), mode="lines",
                line=dict(color=_COLOURS[i % len(_COLOURS)]),
            ))
        fig.update_layout(
            **_layout("Stock by vehicle type"),
            xaxis_title="Year", yaxis_title="Vehicles",
        )
        figs.append(("Stock by vehicle type", fig))

    if not t13.empty and {"year", "vehicle_type", "mirror_vehicle_km"}.issubset(t13.columns):
        fig = go.Figure()
        for i, (vt, grp) in enumerate(t13.groupby("vehicle_type")):
            s = grp.groupby("year")["mirror_vehicle_km"].sum().sort_index()
            fig.add_trace(go.Scatter(
                x=s.index.tolist(), y=s.values.tolist(), name=str(vt), mode="lines",
                line=dict(color=_COLOURS[i % len(_COLOURS)]),
            ))
        fig.update_layout(
            **_layout("Vehicle-km by vehicle type"),
            xaxis_title="Year", yaxis_title="Vehicle-km",
        )
        figs.append(("Vehicle-km by vehicle type", fig))

    if not t13.empty and {"year", "transport_type", "mirror_energy_pj"}.issubset(t13.columns):
        energy = (
            t13.groupby(["year", "transport_type"])["mirror_energy_pj"]
            .sum().unstack(fill_value=0.0).sort_index()
        )
        if not energy.empty:
            fig = go.Figure()
            for i, col in enumerate(energy.columns):
                fig.add_trace(go.Scatter(
                    x=energy.index.tolist(), y=energy[col].tolist(),
                    name=str(col), stackgroup="en", mode="lines",
                ))
            fig.update_layout(
                **_layout("Energy by transport type"),
                xaxis_title="Year", yaxis_title="Energy (PJ)",
            )
            figs.append(("Energy by transport type", fig))

    if not t13_fuel.empty and {"year", "fuel", "mirror_fuel_energy_pj"}.issubset(t13_fuel.columns):
        fe = (
            t13_fuel.groupby(["year", "fuel"])["mirror_fuel_energy_pj"]
            .sum().unstack(fill_value=0.0).sort_index()
        )
        if not fe.empty:
            # Order fuels by total energy descending so the largest fuel is at the bottom.
            fuel_order = fe.sum(axis=0).sort_values(ascending=False).index.tolist()
            # Drop fuels with zero total so the legend stays clean.
            fuel_order = [f for f in fuel_order if fe[f].sum() > 0]
            fig = go.Figure()
            for i, fuel in enumerate(fuel_order):
                fig.add_trace(go.Scatter(
                    x=fe.index.tolist(), y=fe[fuel].tolist(),
                    name=str(fuel), stackgroup="fuel_en", mode="lines",
                    line=dict(color=_fuel_colour(fuel, i)),
                ))
            fig.update_layout(
                **_layout("Fuel energy mix"),
                xaxis_title="Year", yaxis_title="Fuel energy (PJ)",
            )
            figs.append(("Fuel energy mix", fig))

    # --- Drive-type charts ---

    if not t13.empty and {"year", "drive_type", "mirror_stock"}.issubset(t13.columns):
        stock_by_dt = (
            t13.groupby(["year", "drive_type"])["mirror_stock"]
            .sum().unstack(fill_value=0.0).sort_index()
        )
        if not stock_by_dt.empty:
            total = stock_by_dt.sum(axis=1)
            share_dt = stock_by_dt.div(total.replace(0, float("nan")), axis=0).fillna(0.0)
            # Order: ICE first (largest), then ZEVs ascending by final-year share.
            dt_order = share_dt.iloc[-1].sort_values(ascending=False).index.tolist()
            fig = go.Figure()
            for i, dt in enumerate(dt_order):
                fig.add_trace(go.Scatter(
                    x=share_dt.index.tolist(),
                    y=(share_dt[dt] * 100).tolist(),
                    name=str(dt), stackgroup="stock_share", mode="lines",
                    line=dict(color=_drive_colour(dt, i)),
                ))
            fig.update_layout(
                **_layout("Stock share by drive type"),
                xaxis_title="Year", yaxis_title="Share of fleet (%)",
            )
            figs.append((
                "Stock share by drive type",
                fig,
                "Share of total vehicle stock by drive type over the projection. ICE dominates in the base year; shares shift as ZEVs enter the fleet.",
            ))

    if t7f is not None and not t7f.empty and {"year", "drive_type", "sales_share"}.issubset(t7f.columns):
        ss = (
            t7f.groupby(["year", "drive_type"])["sales_share"]
            .mean().unstack(fill_value=0.0).sort_index()
        )
        if not ss.empty:
            dt_order = ss.iloc[-1].sort_values(ascending=False).index.tolist()
            fig = go.Figure()
            for i, dt in enumerate(dt_order):
                fig.add_trace(go.Scatter(
                    x=ss.index.tolist(),
                    y=(ss[dt] * 100).tolist(),
                    name=str(dt), stackgroup="sales_share", mode="lines",
                    line=dict(color=_drive_colour(dt, i)),
                ))
            fig.update_layout(
                **_layout("Sales share by drive type"),
                xaxis_title="Year", yaxis_title="Share of new sales (%)",
            )
            figs.append((
                "Sales share by drive type",
                fig,
                "New vehicle sales mix by drive type. This is the technology transition pathway input — stock shares follow with a lag as older vehicles retire.",
            ))

    if not t13.empty and {"year", "drive_type", "mirror_energy_pj"}.issubset(t13.columns):
        en_by_dt = (
            t13.groupby(["year", "drive_type"])["mirror_energy_pj"]
            .sum().unstack(fill_value=0.0).sort_index()
        )
        if not en_by_dt.empty:
            dt_order = en_by_dt.sum(axis=0).sort_values(ascending=False).index.tolist()
            fig = go.Figure()
            for i, dt in enumerate(dt_order):
                fig.add_trace(go.Scatter(
                    x=en_by_dt.index.tolist(), y=en_by_dt[dt].tolist(),
                    name=str(dt), stackgroup="en_dt", mode="lines",
                    line=dict(color=_drive_colour(dt, i)),
                ))
            fig.update_layout(
                **_layout("Energy use by drive type"),
                xaxis_title="Year", yaxis_title="Energy (PJ)",
            )
            figs.append((
                "Energy use by drive type",
                fig,
                "Total energy demand split by drive type. ICE energy may decline as ZEVs grow; BEV/FCEV energy reflects electricity and hydrogen demand.",
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

    return figs


# ---------------------------------------------------------------------------
# Workflow summary figures
# ---------------------------------------------------------------------------

def workflow_summary_figures(workflow_outputs: dict[str, Any]) -> list[tuple[str, Any]]:
    """Summary figures spanning the whole workflow (Module 6 reconciliation + Module 7)."""
    if not _can_plot() or not workflow_outputs:
        return []

    figs: list[tuple[str, Any]] = []
    _t12 = workflow_outputs.get("T12"); t12 = _t12 if isinstance(_t12, pd.DataFrame) else pd.DataFrame()
    timings = workflow_outputs.get("timings") or {}

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
            fig.add_trace(go.Bar(
                name=label,
                x=fuels,
                y=y_vals,
                marker_color=colour,
            ))

        fig.update_layout(
            **_layout("Post-reconciliation vs ESTO targets (status-coloured post bars)"),
            barmode="group", xaxis_title="Fuel", yaxis_title="Energy (PJ)",
        )
        figs.append(("Post-reconciliation vs ESTO", fig, True))

    if isinstance(timings, dict) and timings:
        modules = [k.replace("_seconds", "").replace("_", " ") for k in timings if k.endswith("_seconds")]
        secs = [timings[k] for k in timings if k.endswith("_seconds")]
        if modules:
            fig = go.Figure(go.Bar(x=modules, y=secs, marker_color="#1E88E5"))
            fig.update_layout(
                **_layout("Workflow timing by module"),
                xaxis_title="Module", yaxis_title="Seconds",
            )
            figs.append(("Workflow timing", fig))

    # Append Module 7 figures if available
    m7_sub = {k: workflow_outputs.get(k) for k in ("T13", "T13_fuel")}
    if any(v is not None for v in m7_sub.values()):
        figs.extend(module7_figures(m7_sub, t7f=workflow_outputs.get("T7f")))

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


# ---------------------------------------------------------------------------
# HTML page builder
# ---------------------------------------------------------------------------

_NAV_LINKS: list[tuple[str, str]] = [
    ("index.html", "Overview"),
    ("module1.html", "Inputs & branches"),
    ("module3.html", "Stocks, sales & turnover"),
    ("module6.html", "Reconciliation"),
    ("module7.html", "Simulated outputs"),
    ("workflow_summary.html", "Summary"),
]

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
.intro-card{background:white;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,.12);margin:8px 20px 18px;padding:16px}
.intro-card h3{margin:0 0 10px 0;color:#1a237e;font-size:1rem}
.intro-card p,.intro-card li{font-size:.9rem;color:#4a4a4a;line-height:1.55}
.intro-card ul{margin:8px 0 0 18px;padding:0}
.module-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:14px;padding:0 20px 22px}
.module-card{background:white;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,.12);padding:14px}
.module-btn{display:inline-block;background:#1a237e;color:white;text-decoration:none;padding:7px 11px;border-radius:6px;font-size:.88rem;font-weight:600;margin-bottom:8px}
.module-btn:hover{background:#2a3796}
.module-desc{font-size:.88rem;color:#555;line-height:1.45}
.diagram-grid{display:grid;grid-template-columns:minmax(0,1fr);gap:16px;padding:0 20px 40px;max-width:1680px;margin:0 auto}
.diagram-card{background:white;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,.12);padding:16px}
.diagram-card--wide{width:100%}
.diagram-title{font-size:.9rem;font-weight:600;color:#444;margin-bottom:8px}
.diagram-caption{font-size:.85rem;color:#666;line-height:1.45;margin-top:8px}
.diagram-card img{display:block;width:100%;height:auto;border-radius:6px;border:1px solid #e5e5e5}
.charts-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:20px;padding:0 20px 40px}
.chart-card{background:white;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,.12);padding:14px;overflow:hidden;min-width:0}
.chart-card--wide{grid-column:1/-1}
.chart-title{font-size:.9rem;font-weight:600;color:#444;margin-bottom:8px}
.chart-caption{font-size:.84rem;color:#666;line-height:1.45;margin:4px 0 8px}
.chart-card .plotly-graph-div,.chart-card .js-plotly-plot,.chart-card .plot-container,.chart-card .svg-container{width:100%!important;max-width:100%!important}
.chart-card .plotly-graph-div{min-height:340px}
.chart-card--wide .plotly-graph-div{min-height:400px}
.no-data{padding:40px 24px;color:#999;font-style:italic}
.alert{padding:12px 20px;margin:0 20px 16px;border-radius:6px;font-size:.9rem;line-height:1.5}
.alert--ok{background:#e8f5e9;color:#1b5e20;border-left:4px solid #4caf50}
.alert--warn{background:#fff8e1;color:#e65100;border-left:4px solid #ffa000}
.alert--fail{background:#ffebee;color:#b71c1c;border-left:4px solid #e53935}
footer{text-align:center;padding:20px;color:#aaa;font-size:.78rem}
@media (max-width:900px){
.charts-grid{grid-template-columns:minmax(0,1fr);gap:16px;padding:0 16px 28px}
.module-grid{grid-template-columns:minmax(0,1fr);gap:12px;padding:0 16px 16px}
.diagram-grid{grid-template-columns:minmax(0,1fr);gap:12px;padding:0 16px 28px}
.intro-card{margin:8px 16px 14px;padding:14px}
.page-title{padding:18px 16px 4px}
.page-desc,.alert{margin-left:16px;margin-right:16px;padding-left:0;padding-right:0}
}
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

_MODULE_META: dict[str, tuple[str, str]] = {
    "index": ("Overview", "Road model workflow QA dashboard. Choose a module from the navigation."),
    "module1": ("Inputs & base-year branches", "Module 1 and 2 diagnostics: default/original input counts, source provenance, value fill methods, branch coverage and base-year metric distributions."),
    "module2": ("Module 2 — Base-year branches", "Branch count heatmap, source flag coverage and metric distributions for the base-year branch table (T4)."),
    "module3": ("Stocks, sales & turnover", "Module 3, 4 and 5 diagnostics: stock target pathways, motorisation envelope, sales and turnover flows, vintages and drive-type sales shares."),
    "module4": ("Module 4 — Sales & turnover", "New sales, stock trajectories, vehicle retirements and base-year vintage profiles from the fleet turnover module."),
    "module5": ("Module 5 — Sales shares", "Drive-type sales shares over the projection horizon by vehicle type, showing technology transition trajectories."),
    "module6": ("Module 6 — LEAP handoff & reconciliation", "Fuel reconciliation diagnostics (ESTO vs model), reconciliation scalars, ECF by fuel, device shares and allocation concentration."),
    "module7": ("Module 7 — Simulated outputs", "Python simulation of what LEAP might produce: stock, vehicle-km, energy by transport type, fuel energy mix, drive-type breakdowns, and comparison with LEAP energy."),
    "workflow_summary": ("Workflow summary", "End-of-process summary: post-reconciliation vs ESTO targets, workflow timing by module and Module 7 aggregate outputs."),
}


def _dashboard_diagram_uri(filename: str) -> str:
    """Return file:// URI for a dashboard diagram under docs/new model, if present."""
    repo_root = Path(__file__).resolve().parents[2]
    diagram = repo_root / "docs" / "new model" / filename
    return diagram.resolve().as_uri() if diagram.exists() else ""


def _index_extra_html() -> str:
    """Build rich overview content for index page (module guide + system diagrams)."""
    module_cards: list[str] = []
    for href, label in _NAV_LINKS[1:]:
        key = href.replace(".html", "")
        title, desc = _MODULE_META.get(key, (label, ""))
        module_cards.append(
            f'<div class="module-card">'
            f'<a class="module-btn" href="{href}">{label}</a>'
            f'<div class="module-desc"><b>{title}</b><br>{desc}</div>'
            f'</div>'
        )

    quick_view_uri = _dashboard_diagram_uri("Road transport model — quick view.png")
    researcher_uri = _dashboard_diagram_uri("Road transport model — researcher detail.png")

    diagrams: list[str] = []
    if quick_view_uri:
        diagrams.append(
            '<div class="diagram-card diagram-card--wide">'
            '<div class="diagram-title">Road transport model — quick view</div>'
            f'<img src="{quick_view_uri}" alt="Road transport model quick view diagram">'
            '<div class="diagram-caption">High-level map of data flow from default inputs, through core modules, into reconciliation and LEAP-ready outputs.</div>'
            '</div>'
        )
    if researcher_uri:
        diagrams.append(
            '<div class="diagram-card diagram-card--wide">'
            '<div class="diagram-title">Road transport model — researcher detail</div>'
            f'<img src="{researcher_uri}" alt="Road transport model researcher detail diagram">'
            '<div class="diagram-caption">Detailed view of module internals, intermediate tables, and dependency paths used for deeper QA and method tracing.</div>'
            '</div>'
        )

    overview = (
        '<div class="intro-card">'
        '<h3>How this system works</h3>'
        '<p>This dashboard tracks the full road-transport modelling pipeline: base-year inputs are assembled and cleaned, stock and turnover trajectories are projected, sales shares are applied, then energy is reconciled to ESTO targets before producing LEAP-ready handoff tables.</p>'
        '<ul>'
        '<li><b>Inputs & branches:</b> check base-year source inputs, defaults and branch-level metrics.</li>'
        '<li><b>Stocks, sales & turnover:</b> inspect target stock pathways, sales flows, retirements, vintages and drive transitions.</li>'
        '<li><b>Reconciliation:</b> compare model fuel totals to ESTO and inspect scaling quality.</li>'
        '<li><b>Mirror model + summary:</b> check end-to-end outputs and Python mirror calculations.</li>'
        '</ul>'
        '</div>'
    )

    module_section = f'<div class="module-grid">{"".join(module_cards)}</div>'
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
        chart_divs: list[str] = []
        for idx, item in enumerate(figures):
            title, fig = item[0], item[1]
            explicit_wide = False
            caption = ""
            if len(item) > 2:
                if isinstance(item[2], bool):
                    explicit_wide = bool(item[2])
                    if len(item) > 3 and isinstance(item[3], str):
                        caption = item[3]
                elif isinstance(item[2], str):
                    caption = item[2]

            wide = _should_render_wide(fig, explicit_wide=explicit_wide)
            fig = _apply_dashboard_layout(fig, wide=wide)
            include_js: Any = "cdn" if idx == 0 else False
            fig_html = pio.to_html(
                fig, full_html=False,
                include_plotlyjs=include_js,
                config={"responsive": True, "displaylogo": False},
            )
            css = "chart-card chart-card--wide" if wide else "chart-card"
            caption_html = f'<div class="chart-caption">{caption}</div>' if caption else ""
            chart_divs.append(
                f'<div class="{css}"><div class="chart-title">{title}</div>{caption_html}{fig_html}</div>'
            )
        charts_section = f'<div class="charts-grid">{"".join(chart_divs)}</div>'
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
        f'<nav>{_nav_html(active_page)}</nav></header>\n'
        f'<div class="page-wrap">'
        f'<div class="page-title">{page_title}</div>'
        f'<div class="page-desc">{page_desc}</div>\n'
        f'{body_content}\n'
        f'<footer>Generated by leap_road_model — road_workflow diagnostic dashboard</footer>\n'
        f'{_RESIZE_SCRIPT}\n'
        f'</div>'
        f'</body></html>'
    )


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def write_module_pages(
    workflow_outputs: dict[str, Any],
    dashboard_dir: str | Path,
    economy: str = "",
) -> list[Path]:
    """Write workflow-stage interactive HTML dashboard pages plus an index page.

    Args:
        workflow_outputs: dict returned by ``run_with_config()`` (or a subset).
            Keys used: ``module1_merged``, ``T4``–``T12``, ``T13``, ``T13_fuel``,
            ``timings``.
        dashboard_dir: Directory to write HTML files into (created if absent).
        economy: Economy code shown in the page header (e.g. ``"12_NZ"``).

    Returns:
        List of :class:`~pathlib.Path` objects for the written HTML files.
    """
    if not _can_plot():
        return []

    out = Path(dashboard_dir)
    out.mkdir(parents=True, exist_ok=True)
    for old_page in ("module2.html", "module4.html", "module5.html"):
        (out / old_page).unlink(missing_ok=True)
    written: list[Path] = []

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
    input_figures = module1_figures(m1_df) if m1_df is not None else []
    input_figures.extend(module2_figures(workflow_outputs.get("T4")))
    _write("module1.html", input_figures)

    t6 = workflow_outputs.get("T6")
    t6v = workflow_outputs.get("T6v")
    t7 = workflow_outputs.get("T7")
    t7f = workflow_outputs.get("T7f")
    stock_sales_figures = module3_figures(workflow_outputs.get("T5"))
    stock_sales_figures.extend(module4_figures(t6, t6v))
    stock_sales_figures.extend(module5_figures(t7, t7f))
    _write("module3.html", stock_sales_figures)

    t12 = workflow_outputs.get("T12")
    recon_alert = _reconciliation_alert_html(t12)

    m6_sub = {k: workflow_outputs.get(k) for k in ("T8", "T9", "T10", "T12")}
    _write("module6.html", module6_figures(m6_sub), extra=recon_alert)

    m7_sub = {k: workflow_outputs.get(k) for k in ("T13", "T13_fuel")}
    _write("module7.html", module7_figures(m7_sub, t7f=workflow_outputs.get("T7f")),
           extra=_MODULE7_NOTE_HTML)

    _write("workflow_summary.html", workflow_summary_figures(workflow_outputs),
           extra=recon_alert)

    # Index page — module guide + system diagrams
    index_extra = _index_extra_html()
    _write("index.html", [], extra=index_extra)

    return written
