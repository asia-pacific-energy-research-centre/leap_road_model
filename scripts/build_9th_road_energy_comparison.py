"""Build a Plotly comparison of 9th-edition and new road-model energy."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


ECONOMIES = [
    "01_AUS", "02_BD", "03_CDA", "04_CHL", "05_PRC", "06_HKC", "07_INA",
    "08_JPN", "09_ROK", "10_MAS", "11_MEX", "12_NZ", "13_PNG", "14_PE",
    "15_PHL", "16_RUS", "17_SGP", "18_CT", "19_THA", "20_USA", "21_VN",
]
SCENARIOS = ["reference", "target"]
YEARS = list(range(2022, 2061))

FUEL_MAP = {
    "07_01_motor_gasoline": "Motor gasoline",
    "07_07_gas_diesel_oil": "Gas and diesel oil",
    "07_09_lpg": "LPG",
    "08_01_natural_gas": "Natural gas",
    "16_01_biogas": "Biogas",
    "16_05_biogasoline": "Biogasoline",
    "16_06_biodiesel": "Biodiesel",
    "16_x_efuel": "Efuel",
    "16_x_hydrogen": "Hydrogen",
    "17_electricity": "Electricity",
}
FUEL_ORDER = [
    "Motor gasoline", "Gas and diesel oil", "LPG", "Natural gas", "Biogasoline",
    "Biodiesel", "Biogas", "Electricity", "Hydrogen", "Efuel", "Other",
]
COLORS = [
    "#4C78A8", "#F58518", "#E45756", "#72B7B2", "#54A24B", "#EECA3B",
    "#B279A2", "#FF9DA6", "#9D755D", "#2CA02C", "#BAB0AC",
]


def _scenario_name(value: str) -> str:
    return str(value).strip().lower()


def load_ninth_energy(path: Path) -> pd.DataFrame:
    year_columns = [str(year) for year in YEARS]
    columns = [
        "scenarios", "economy", "sub1sectors", "sub2sectors", "sub3sectors",
        "sub4sectors", "fuels", "subfuels", "subtotal_layout", *year_columns,
    ]
    raw = pd.read_csv(path, usecols=columns, low_memory=False)
    road = raw[
        (raw["sub1sectors"] == "15_02_road")
        & (raw["sub2sectors"] == "x")
        & (raw["sub3sectors"] == "x")
        & (raw["sub4sectors"] == "x")
        & (~raw["subtotal_layout"].fillna(False).astype(bool))
        & ((raw["subfuels"] != "x") | (raw["fuels"] == "17_electricity"))
        & raw["economy"].isin(ECONOMIES)
        & raw["scenarios"].isin(SCENARIOS)
    ].copy()
    road["fuel"] = road["subfuels"].map(FUEL_MAP).fillna("Other")
    long = road.melt(
        id_vars=["economy", "scenarios", "fuel"],
        value_vars=year_columns,
        var_name="year",
        value_name="energy_pj",
    )
    long["scenario"] = long["scenarios"].map(_scenario_name)
    long["year"] = long["year"].astype(int)
    long["energy_pj"] = pd.to_numeric(long["energy_pj"], errors="coerce").fillna(0.0)
    return (
        long.groupby(["economy", "scenario", "year", "fuel"], as_index=False)["energy_pj"]
        .sum()
    )


def load_new_model_energy(root: Path) -> pd.DataFrame:
    frames = []
    for economy in ECONOMIES:
        path = root / economy / "module7" / "T13_mirror_fuel_outputs.csv"
        frame = pd.read_csv(path)
        frame = frame[frame["year"].isin(YEARS)].copy()
        frame["scenario"] = frame["scenario"].map(_scenario_name)
        frame["fuel"] = frame["fuel"].replace({"Efuel": "Efuel"})
        frame["energy_pj"] = pd.to_numeric(frame["mirror_fuel_energy_pj"], errors="coerce").fillna(0.0)
        frames.append(frame[["economy", "scenario", "year", "fuel", "energy_pj"]])
    return (
        pd.concat(frames, ignore_index=True)
        .groupby(["economy", "scenario", "year", "fuel"], as_index=False)["energy_pj"]
        .sum()
    )


def _series(frame: pd.DataFrame, economy: str, scenario: str, fuel: str) -> list[float]:
    subset = frame[
        (frame["economy"] == economy)
        & (frame["scenario"] == scenario)
        & (frame["fuel"] == fuel)
    ].set_index("year")["energy_pj"]
    return [round(float(subset.get(year, 0.0)), 4) for year in YEARS]


def _total_series(frame: pd.DataFrame, economy: str, scenario: str) -> list[float]:
    subset = frame[
        (frame["economy"] == economy)
        & (frame["scenario"] == scenario)
        & (frame["year"].isin(YEARS))
    ]
    totals = subset.groupby("year")["energy_pj"].sum()
    return [round(float(totals.get(year, 0.0)), 4) for year in YEARS]


def _add_stacked_area(
    fig: go.Figure,
    frame: pd.DataFrame,
    economy: str,
    scenario: str,
    row: int,
    col: int,
    showlegend: bool,
    comparison_frame: pd.DataFrame,
    comparison_label: str,
    comparison_color: str,
) -> None:
    for index, fuel in enumerate(FUEL_ORDER):
        fig.add_trace(
            go.Scatter(
                x=YEARS,
                y=_series(frame, economy, scenario, fuel),
                name=fuel,
                legendgroup=fuel,
                stackgroup=f"{economy}-{scenario}-{col}",
                mode="lines",
                line={"width": 0.4, "color": COLORS[index]},
                fillcolor=COLORS[index],
                hovertemplate=f"{fuel}: %{{y:.2f}} PJ<extra></extra>",
                showlegend=showlegend,
            ),
            row=row,
            col=col,
        )
    fig.add_trace(
        go.Scatter(
            x=YEARS,
            y=_total_series(comparison_frame, economy, scenario),
            name=comparison_label,
            legendgroup=comparison_label,
            mode="lines",
            line={"width": 2.4, "dash": "dash", "color": comparison_color},
            hovertemplate=f"{comparison_label}: %{{y:.2f}} PJ<extra></extra>",
            showlegend=showlegend,
        ),
        row=row,
        col=col,
    )


def build_dashboard(ninth: pd.DataFrame, model: pd.DataFrame, output: Path) -> None:
    titles = []
    for economy in ECONOMIES:
        for scenario in SCENARIOS:
            titles.extend([f"{economy} — {scenario.title()} — 9th edition", f"{economy} — {scenario.title()} — new model"])
    fig = make_subplots(
        rows=len(ECONOMIES) * len(SCENARIOS),
        cols=2,
        shared_xaxes=False,
        shared_yaxes="rows",
        vertical_spacing=0.002,
        horizontal_spacing=0.04,
        subplot_titles=titles,
    )
    row = 1
    for economy in ECONOMIES:
        for scenario in SCENARIOS:
            _add_stacked_area(
                fig, ninth, economy, scenario, row, 1, showlegend=row == 1,
                comparison_frame=model, comparison_label="New model total", comparison_color="#111827",
            )
            _add_stacked_area(
                fig, model, economy, scenario, row, 2, showlegend=False,
                comparison_frame=ninth, comparison_label="9th edition total", comparison_color="#C2410C",
            )
            row += 1

    fig.update_xaxes(range=[2022, 2060], dtick=10, showgrid=True, gridcolor="rgba(120,120,120,0.18)")
    fig.update_yaxes(title_text="PJ", rangemode="tozero", showgrid=True, gridcolor="rgba(120,120,120,0.18)")
    fig.update_layout(
        title={"text": "Road energy comparison — 9th edition versus new road model", "x": 0.5},
        height=360 * len(ECONOMIES) * len(SCENARIOS),
        width=1500,
        template="plotly_white",
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.01, "x": 0.0},
        margin={"l": 70, "r": 30, "t": 110, "b": 45},
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(
        output,
        include_plotlyjs="cdn",
        full_html=True,
        config={"responsive": True, "displaylogo": False},
    )


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    ninth_path = Path(r"C:\Users\Work\APERC\Outlook 10 - LEAP modelling_2026\esto data files\9th merged_file_energy_ALL_20251106.csv")
    model_root = repo_root / "results" / "qa_9th_comparison" / "new_model_all_scenarios"
    output_root = repo_root / "results" / "qa_9th_comparison"
    ninth = load_ninth_energy(ninth_path)
    model = load_new_model_energy(model_root)
    dashboard = output_root / "road_energy_9th_vs_new_model.html"
    build_dashboard(ninth, model, dashboard)
    summary = {
        "economies": ECONOMIES,
        "scenarios": [scenario.title() for scenario in SCENARIOS],
        "years": [min(YEARS), max(YEARS)],
        "ninth_rows": int(len(ninth)),
        "new_model_rows": int(len(model)),
        "fuel_categories": FUEL_ORDER,
        "dashboard": str(dashboard),
    }
    (output_root / "comparison_manifest.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
