"""Add fresh road-model comparison lines to the released 9th dashboard pages.

The downloaded 9th-edition dashboard is a self-contained HTML release.  This
script keeps those pages and their original data intact, appending comparable
new-model rows to each page's embedded payload and making the existing Plotly
chart distinguish the two sources by line style.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd


DEFAULT_SOURCE = Path(r"C:\Users\Work\Downloads\9th_transport_model_dashboards\transport_dashboards")
DEFAULT_MODEL_ROOT = Path(__file__).resolve().parents[1] / "results/qa_9th_comparison/new_model_all_scenarios"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "results/qa_9th_dashboard_comparison"
DEFAULT_MERGED_ENERGY = Path(r"C:\Users\Work\github\leap_initialisation\data\merged_file_energy_ALL_20251106.csv")

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

VEHICLE_MAP = {
    "Motorcycles": "2w",
    "Buses": "bus",
    "LCVs": "lcv",
    "Medium trucks": "mt",
    "Heavy trucks": "ht",
}


def _model_vehicle_key(vehicle: object, size: object = None) -> str:
    vehicle_name = str(vehicle)
    size_name = str(size).lower() if pd.notna(size) else ""
    if vehicle_name == "LPVs":
        return f"lpv_{size_name}" if size_name else "lpv"
    if vehicle_name == "Trucks":
        return {"medium": "mt", "heavy": "ht"}.get(size_name, "trucks")
    return VEHICLE_MAP.get(vehicle_name, "all")


def _payload_from_html(html: str) -> dict:
    match = re.search(r"const PAYLOAD = (\{.*?\});\s*\n\s*const DATA", html, flags=re.S)
    if not match:
        raise ValueError("Could not locate embedded dashboard PAYLOAD")
    return json.loads(match.group(1))


def _row(dataset: str, scenario: str, transport: str, vehicle: str, drive: str,
         fuel: str, measure: str, year: int, value: float) -> list[object]:
    return [dataset, scenario, transport, vehicle, drive, fuel, measure, int(year), float(value)]


def _load_merged_energy(path: Path) -> pd.DataFrame:
    years = [str(year) for year in range(2023, 2061)]
    usecols = ["scenarios", "economy", "sectors", "sub1sectors", "sub2sectors", "fuels", "subfuels", "subtotal_results", *years]
    # Keep the exact source filter requested for projected detailed rows.
    raw = pd.read_csv(path, usecols=usecols, low_memory=False)
    mask = (
        raw["sectors"].eq("15_transport_sector")
        & raw["sub1sectors"].eq("15_02_road")
        & raw["subtotal_results"].eq(False)
        & raw["sub2sectors"].isin(["15_02_01_passenger", "15_02_02_freight"])
        & ((raw["subfuels"] != "x") | raw["fuels"].eq("17_electricity"))
        & raw["scenarios"].isin(["reference", "target"])
    )
    selected = raw.loc[mask].copy()
    selected["scenario"] = selected["scenarios"].map({"reference": "Reference", "target": "Target"})
    selected["transport_type"] = selected["sub2sectors"].map({"15_02_01_passenger": "passenger", "15_02_02_freight": "freight"})
    selected["fuel"] = selected["subfuels"].map(FUEL_MAP)
    selected.loc[selected["fuels"].eq("17_electricity"), "fuel"] = "Electricity"
    selected["fuel"] = selected["fuel"].fillna("Other")
    long = selected.melt(
        id_vars=["economy", "scenario", "transport_type", "fuel"],
        value_vars=years, var_name="year", value_name="value",
    )
    long["year"] = long["year"].astype(int)
    long["value"] = pd.to_numeric(long["value"], errors="coerce").fillna(0.0)
    detail = long.groupby(["economy", "scenario", "transport_type", "fuel", "year"], as_index=False)["value"].sum()
    totals = detail.groupby(["economy", "scenario", "transport_type", "year"], as_index=False)["value"].sum()
    totals["fuel"] = "Total"
    return pd.concat([detail, totals], ignore_index=True)


def _merged_energy_rows(energy: pd.DataFrame, economy: str) -> list[list[object]]:
    rows = []
    for _, item in energy[energy["economy"].eq(economy)].iterrows():
        rows.append(_row("outcome", item["scenario"], item["transport_type"], "all", "all", item["fuel"], "energy", item["year"], item["value"]))
    return rows


def _model_rows(model_root: Path, economy: str, payload: dict) -> list[list[object]]:
    fuel_path = model_root / economy / "module7" / "T13_mirror_fuel_outputs.csv"
    t13_path = model_root / economy / "module7" / "T13_mirror_outputs.csv"
    t6_path = model_root / economy / "module4" / "T6_sales_turnover.csv"
    t7_path = model_root / economy / "module5" / "T7_sales_shares.csv"
    fuel = pd.read_csv(fuel_path)
    t13 = pd.read_csv(t13_path)
    t6 = pd.read_csv(t6_path)
    t7 = pd.read_csv(t7_path)
    fuel["scenario"] = fuel["scenario"].replace({"reference": "Reference", "target": "Target"})
    t13["scenario"] = t13["scenario"].replace({"reference": "Reference", "target": "Target"})
    t6["scenario"] = t6["scenario"].replace({"reference": "Reference", "target": "Target"})
    t7["scenario"] = t7["scenario"].replace({"reference": "Reference", "target": "Target"})
    fuel["allocated_stock"] = pd.to_numeric(fuel["mirror_stock"], errors="coerce") * pd.to_numeric(fuel["device_share"], errors="coerce")
    fuel["allocated_km"] = pd.to_numeric(fuel["mirror_vehicle_km"], errors="coerce") * pd.to_numeric(fuel["device_share"], errors="coerce")
    fuel["energy_pj"] = pd.to_numeric(fuel["mirror_fuel_energy_pj"], errors="coerce").fillna(0.0)
    rows: list[list[object]] = []

    # Outcome measures use the same fuel and transport dimensions as the old dashboard.
    keys = ["scenario", "transport_type", "fuel", "year"]
    grouped = fuel.groupby(keys, dropna=False)
    for key, g in grouped:
        scenario, transport, fuel_name, year = key
        stock = g["allocated_stock"].sum()
        km = g["allocated_km"].sum()
        energy = g["energy_pj"].sum()
        values = {
            "energy": energy,
            "stock": stock / 1_000_000,
            "mileage": km / stock if stock else float("nan"),
            # PJ / km -> thousand MJ / 100 km.
            "efficiency": energy * 100_000_000 / km if km else float("nan"),
        }
        for measure, value in values.items():
            if pd.notna(value):
                rows.append(_row("new_model", scenario, transport, "all", "all", fuel_name, measure, year, value))

    # Match the existing 9th-edition Total fuel rows with equivalent totals.
    for (scenario, transport, year), g in fuel.groupby(["scenario", "transport_type", "year"]):
        stock = g["allocated_stock"].sum()
        km = g["allocated_km"].sum()
        energy = g["energy_pj"].sum()
        totals = {
            "energy": energy,
            "stock": stock / 1_000_000,
            "mileage": km / stock if stock else float("nan"),
            "efficiency": energy * 100_000_000 / km if km else float("nan"),
        }
        for measure, value in totals.items():
            if pd.notna(value):
                rows.append(_row("new_model", scenario, transport, "all", "all", "Total", measure, year, value))

    # Fleet measures: physical stock and retirement/turnover are intentionally
    # emitted at the all-vehicle level because LPVs do not map to the old
    # car/SUV/light-truck taxonomy. Fuel/drive diagnostics remain available.
    for (scenario, transport, year), g in t13.groupby(["scenario", "transport_type", "year"]):
        rows.append(_row("new_model_fleet", scenario, transport, "all", "all", "all", "vehicle_stock", year, g["mirror_stock"].sum() / 1_000_000))
    for (scenario, transport, vehicle, size, year), g in t13.groupby(["scenario", "transport_type", "vehicle_type", "size", "year"], dropna=False):
        rows.append(_row("new_model_fleet", scenario, transport, _model_vehicle_key(vehicle, size), "all", "all", "vehicle_stock", year, g["mirror_stock"].sum() / 1_000_000))
    for (scenario, transport, drive, fuel_name, year), g in fuel.groupby(["scenario", "transport_type", "drive_type", "fuel", "year"], dropna=False):
        rows.append(_row("new_model_fleet", scenario, transport, "all", drive, fuel_name, "fuel_allocated_stock", year, g["allocated_stock"].sum() / 1_000_000))

    if not t7.empty:
        sales = t6.merge(
            t7[["scenario", "vehicle_type", "drive_type", "sales_share", "year"]],
            on=["scenario", "vehicle_type", "year"], how="left",
        )
        sales["value"] = pd.to_numeric(sales["new_sales"], errors="coerce").fillna(0) * pd.to_numeric(sales["sales_share"], errors="coerce").fillna(0) / 1_000_000
        for (scenario, transport, drive, year), g in sales.groupby(["scenario", "transport_type", "drive_type", "year"], dropna=False):
            rows.append(_row("new_model_fleet", scenario, transport, "all", drive, "all", "fuel_allocated_sales", year, g["value"].sum()))

    t6["stock_num"] = pd.to_numeric(t6["stock"], errors="coerce")
    t6["turnover"] = pd.to_numeric(t6["total_retirements"], errors="coerce") / t6["stock_num"].replace(0, pd.NA)
    t6["retirement"] = pd.to_numeric(t6["natural_retirements"], errors="coerce") / t6["stock_num"].replace(0, pd.NA)
    for _, r in t6.iterrows():
        vehicle = _model_vehicle_key(r["vehicle_type"])
        for measure, value in (("turnover_rate", r["turnover"]), ("retirement_rate", r["retirement"])):
            if pd.notna(value):
                rows.append(_row("new_model_fleet", r["scenario"], r["transport_type"], vehicle, "all", "all", measure, r["year"], value))

    # Add a comparable old-dashboard aggregate for physical stock alongside
    # the new-model aggregate; the original detailed rows remain untouched.
    old_rows = payload["data_rows"]
    cols = payload["data_columns"]
    old = pd.DataFrame(old_rows, columns=cols)
    old = old[old["dataset"].eq("fleet") & old["measure"].eq("vehicle_stock")]
    for (scenario, transport, year), g in old.groupby(["scenario", "transport_type", "year"]):
        rows.append(_row("fleet", scenario, transport, "all", "all", "all", "vehicle_stock", year, pd.to_numeric(g["value"]).sum()))
    return rows


def _normalise_released_outcome_units(payload: dict) -> list[dict[str, object]]:
    """Correct two scale mismatches in the released dashboard payload.

    The released 9th dashboard labels energy as PJ and mileage as km, but its
    embedded outcome values are respectively EJ-sized and thousand-km-sized.
    The comparison copy uses the labels shown by the dashboard and therefore
    converts those two measures to PJ and km. Stock and efficiency are left
    unchanged except where the 2022 fuel-allocated stock total is clearly in
    raw vehicles rather than millions. That check uses the physical fleet
    total, so it is not economy-specific.
    """
    columns = payload["data_columns"]
    dataset_i = columns.index("dataset")
    scenario_i = columns.index("scenario")
    measure_i = columns.index("measure")
    transport_i = columns.index("transport_type")
    fuel_i = columns.index("fuel")
    year_i = columns.index("year")
    value_i = columns.index("value")
    frame = pd.DataFrame(payload["data_rows"], columns=columns)
    physical = frame[
        (frame["dataset"] == "fleet")
        & (frame["measure"] == "vehicle_stock")
        & (frame["year"] == 2022)
    ]
    physical_totals = physical.groupby("transport_type")["value"].sum().to_dict()
    outcome_totals = frame[
        (frame["dataset"] == "outcome")
        & (frame["measure"] == "stock")
        & (frame["fuel"] == "Total")
        & (frame["year"] == 2022)
    ]
    raw_stock_transports = {}
    for row in outcome_totals.itertuples(index=False, name=None):
        transport = str(row[transport_i])
        physical_total = float(physical_totals.get(transport, 0))
        if physical_total > 0 and float(row[value_i]) / physical_total > 100:
            raw_stock_transports[transport] = float(row[value_i]) / physical_total
    corrections = []
    for row in payload["data_rows"]:
        if row[dataset_i] != "outcome":
            continue
        if row[measure_i] in {"energy", "mileage"}:
            row[value_i] = float(row[value_i]) * 1000.0
        elif row[measure_i] == "stock" and row[year_i] == 2022 and str(row[transport_i]) in raw_stock_transports:
            row[value_i] = float(row[value_i]) / 1_000_000.0
            if row[fuel_i] == "Total":
                corrections.append({
                    "scenario": row[scenario_i],
                    "transport_type": row[transport_i],
                    "year": 2022,
                    "factor_applied": 1_000_000,
                    "raw_to_physical_ratio": raw_stock_transports[str(row[transport_i])],
                })
    return corrections


def _total_comparison_rows(payload: dict) -> list[dict[str, object]]:
    """Return 9th-versus-new-model total rows for automated outlier review."""
    frame = pd.DataFrame(payload["data_rows"], columns=payload["data_columns"])
    frame = frame[
        frame["dataset"].isin(["outcome", "new_model"])
        & frame["fuel"].eq("Total")
        & frame["measure"].isin(["energy", "stock", "mileage", "efficiency"])
    ]
    keys = ["scenario", "transport_type", "measure", "year"]
    pivot = frame.pivot_table(index=keys, columns="dataset", values="value", aggfunc="first").reset_index()
    if "outcome" not in pivot or "new_model" not in pivot:
        return []
    pivot = pivot.dropna(subset=["outcome", "new_model"]).copy()
    pivot["absolute_difference"] = (pivot["new_model"] - pivot["outcome"]).abs()
    denominator = pivot[["outcome", "new_model"]].abs().max(axis=1).replace(0, pd.NA)
    pivot["relative_difference"] = pivot["absolute_difference"] / denominator
    pivot["major_difference"] = pivot["relative_difference"].ge(0.5)
    return pivot.to_dict("records")


def _add_both_transport_rows(payload: dict, additions: list[list[object]]) -> None:
    """Add a combined passenger+freight view where aggregation is meaningful."""
    columns = payload["data_columns"]
    frame = pd.DataFrame(payload["data_rows"] + additions, columns=columns)
    frame = frame[frame["transport_type"].isin(["passenger", "freight"])]
    if frame.empty:
        return
    common = ["dataset", "scenario", "vehicle_type", "drive", "fuel", "year"]
    rows: list[list[object]] = []

    def append_grouped(grouped: pd.DataFrame, measure: str) -> None:
        for _, item in grouped.iterrows():
            if pd.notna(item["value"]):
                rows.append(_row(item["dataset"], item["scenario"], "both", item["vehicle_type"], item["drive"], item["fuel"], measure, item["year"], item["value"]))

    additive = frame[frame["measure"].isin({"energy", "stock", "vehicle_stock", "fuel_allocated_stock", "fuel_allocated_sales"})].copy()
    if not additive.empty:
        grouped = additive.groupby(common + ["measure"], dropna=False, as_index=False)["value"].sum()
        for measure in grouped["measure"].unique():
            append_grouped(grouped[grouped["measure"] == measure].drop(columns="measure"), measure)

    mileage = frame[frame["measure"] == "mileage"].copy()
    stock = frame[frame["measure"] == "stock"].copy()
    if not mileage.empty and not stock.empty:
        mileage = mileage.rename(columns={"value": "mileage_value"})
        stock = stock.rename(columns={"value": "stock_value"})
        joined = mileage.merge(stock[common + ["transport_type", "stock_value"]], on=common + ["transport_type"], how="left")
        joined["weighted"] = pd.to_numeric(joined["mileage_value"], errors="coerce") * pd.to_numeric(joined["stock_value"], errors="coerce")
        grouped = joined.groupby(common, dropna=False, as_index=False).agg(weighted=("weighted", "sum"), stock_value=("stock_value", "sum"))
        grouped["value"] = grouped["weighted"] / grouped["stock_value"].replace(0, pd.NA)
        append_grouped(grouped, "mileage")

    efficiency = frame[frame["measure"] == "efficiency"].copy()
    energy = frame[frame["measure"] == "energy"].copy()
    if not efficiency.empty and not energy.empty:
        efficiency = efficiency.rename(columns={"value": "efficiency_value"})
        energy = energy.rename(columns={"value": "energy_value"})
        joined = efficiency.merge(energy[common + ["transport_type", "energy_value"]], on=common + ["transport_type"], how="left")
        joined["energy_value"] = pd.to_numeric(joined["energy_value"], errors="coerce")
        joined["efficiency_value"] = pd.to_numeric(joined["efficiency_value"], errors="coerce")
        joined["activity_proxy"] = joined["energy_value"] / joined["efficiency_value"].where(joined["efficiency_value"] > 0)
        grouped = joined.groupby(common, dropna=False, as_index=False).agg(energy_value=("energy_value", "sum"), activity_proxy=("activity_proxy", "sum"))
        grouped["value"] = grouped["energy_value"] / grouped["activity_proxy"].replace(0, pd.NA)
        append_grouped(grouped, "efficiency")

    # Turnover and retirement rates are intentionally kept transport-specific.
    payload["data_rows"].extend(rows)


def _patch_renderer(html: str) -> str:
    html = html.replace(
        '"lpg":"LPG"',
        '"lpg":"LPG", "lpv_small":"LPV small", "lpv_medium":"LPV medium", "lpv_large":"LPV large", "lpv":"LPVs", "trucks":"Trucks"',
    )
    html = html.replace(
        '<div id="outcomeMetrics" class="metric-tabs">',
        '<div class="field source-filter-field"><label>Show data source</label><div class="source-buttons"><button class="source-filter" data-source="all" aria-pressed="true">All</button><button class="source-filter" data-source="ninth" aria-pressed="false">9th edition only</button><button class="source-filter" data-source="new" aria-pressed="false">LEAP/new model only</button></div></div>\n    <div id="outcomeMetrics" class="metric-tabs">',
    )
    html = html.replace(
        '<select id="transport"><option value="passenger">Passenger</option><option value="freight">Freight</option></select>',
        '<select id="transport"><option value="passenger">Passenger</option><option value="freight">Freight</option><option value="both">Both</option></select>',
    )
    html = html.replace(
        '.metric-tabs { grid-column: 1 / -1;',
        '.source-filter-field { grid-column: 1 / -1; } .source-buttons { display: flex; flex-wrap: wrap; gap: 6px; } .source-filter { min-height: 32px; padding: 4px 10px; border: 1px solid var(--line); color: var(--muted); background: var(--surface); cursor: pointer; } .source-filter[aria-pressed="true"] { color: var(--ink); border-color: var(--accent); background: color-mix(in srgb, var(--accent) 12%, var(--surface)); }\n    .metric-tabs { grid-column: 1 / -1;',
    )
    html = html.replace(
        'let fleetMeasure = "vehicle_stock";',
        'let fleetMeasure = "vehicle_stock";\n    let sourceFilter = "all";',
    )
    html = html.replace(
        'const options = [...new Set(DATA.filter(d => d.dataset === "fleet" && d.transport_type === transport).map(d => d.vehicle_type))].sort();',
        'const options = [...new Set(DATA.filter(d => ["fleet", "new_model_fleet"].includes(d.dataset) && d.transport_type === transport).map(d => d.vehicle_type))].sort();',
    )
    html = html.replace(
        'let rows = DATA.filter(d => d.scenario === scenario && d.transport_type === transport && d.measure === measure);',
        'const allDatasets = page === "outcomes" ? ["outcome", "new_model"] : ["fleet", "new_model_fleet"];\n      const datasets = sourceFilter === "ninth" ? [allDatasets[0]] : sourceFilter === "new" ? [allDatasets[1]] : allDatasets;\n      let rows = DATA.filter(d => datasets.includes(d.dataset) && d.scenario === scenario && d.transport_type === transport && d.measure === measure);',
    )
    html = html.replace(
        'const key = `${series}|${row.year}`;',
        'const key = `${row.dataset}|${series}|${row.year}`;',
    )
    html = html.replace(
        'grouped.set(key, {series, year: row.year, sum: 0, count: 0});',
        'grouped.set(key, {dataset: row.dataset, series, year: row.year, sum: 0, count: 0});',
    )
    html = html.replace(
        'item.sum += Number(row.value);',
        'item.sum += Number(row.value);',
    )
    html = html.replace(
        'return [...grouped.values()].map(item => ({series: item.series, year: item.year, value: percentMeasure ? item.sum / item.count * 100 : item.sum}));',
        'return [...grouped.values()].map(item => ({dataset: item.dataset, series: item.series, year: item.year, value: percentMeasure ? item.sum / item.count * 100 : item.sum}));',
    )
    html = html.replace(
        'const series = [...new Set(plotted.map(d => d.series))].sort((a, b) => a === "Total" ? -1 : b === "Total" ? 1 : String(a).localeCompare(String(b)));',
        'const series = [...new Set(plotted.map(d => `${d.dataset}|${d.series}`))].sort((a, b) => String(a).localeCompare(String(b)));',
    )
    html = html.replace(
        'const points = plotted.filter(d => d.series === name).sort((a, b) => a.year - b.year);\n        return {\n          x: points.map(d => d.year), y: points.map(d => d.value), name: label(name),',
        'const [dataset, rawSeries] = name.split("|");\n        const points = plotted.filter(d => `${d.dataset}|${d.series}` === name).sort((a, b) => a.year - b.year);\n        const displayName = `${dataset === "new_model" || dataset === "new_model_fleet" ? "LEAP/new model" : "9th edition"}: ${label(rawSeries)}`;\n        return {\n          x: points.map(d => d.year), y: points.map(d => d.value), name: displayName,',
    )
    html = html.replace(
        'line: {width: name === "Total" ? 3.4 : 2.4, color: palette[index % palette.length], dash: index >= palette.length ? "dash" : "solid"},\n          hovertemplate: `<b>${label(name)}</b><br>%{x}: %{y:,.3g}<extra></extra>`',
        'line: {width: rawSeries === "Total" ? 3.4 : 2.4, color: palette[Math.max(0, series.findIndex(x => x.endsWith(`|${rawSeries}`))) % palette.length], dash: dataset === "new_model" || dataset === "new_model_fleet" ? "dash" : "solid"},\n          hovertemplate: `<b>${displayName}</b><br>%{x}: %{y:,.3g}<extra></extra>`',
    )
    html = html.replace(
        'document.querySelectorAll("#fleetMetrics button").forEach(button => button.addEventListener("click", () => {',
        'document.querySelectorAll(".source-filter").forEach(button => button.addEventListener("click", () => { sourceFilter = button.dataset.source; document.querySelectorAll(".source-filter").forEach(item => item.setAttribute("aria-pressed", item === button)); renderChart(); }));\n    document.querySelectorAll("#fleetMetrics button").forEach(button => button.addEventListener("click", () => {',
    )
    html = html.replace(
        'visibleRows = plotted.map(d => ({scenario, transport_type: transport, measure, series_dimension: seriesField, series: d.series, year: d.year, value: d.value, unit}));',
        'visibleRows = plotted.map(d => ({dataset: d.dataset, scenario, transport_type: transport, measure, series_dimension: seriesField, series: d.series, year: d.year, value: d.value, unit}));',
    )
    html = html.replace('hovermode: "x unified"', 'hovermode: "closest"')
    return html.replace(
        '<title>Road assumptions dashboard</title>',
        '<title>Road assumptions dashboard — 9th edition versus new model</title>',
    )


def build(source: Path, model_root: Path, merged_energy_path: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    road_source = source / "road"
    pages = sorted(road_source.glob("[0-9][0-9]_*.html"))
    if not pages:
        raise FileNotFoundError(f"No economy dashboard pages found in {road_source}")
    merged_energy = _load_merged_energy(merged_energy_path)
    counts = {}
    stock_corrections = []
    total_comparisons = []
    for page in pages:
        html = page.read_text(encoding="utf-8")
        payload = _payload_from_html(html)
        corrections = _normalise_released_outcome_units(payload)
        for correction in corrections:
            stock_corrections.append({"economy": payload["meta"]["economy"], **correction})
        # The released dashboard energy rows use inconsistent scales and omit
        # some alternatives. Replace them with the merged-energy source. Its
        # detailed rows begin in 2023, so 2022 is intentionally absent here.
        payload["data_rows"] = [
            row for row in payload["data_rows"]
            if not (row[payload["data_columns"].index("dataset")] == "outcome" and row[payload["data_columns"].index("measure")] == "energy")
        ]
        additions = _model_rows(model_root, payload["meta"]["economy"], payload)
        payload["data_rows"].extend(_merged_energy_rows(merged_energy, payload["meta"]["economy"]))
        payload["data_rows"].extend(additions)
        _add_both_transport_rows(payload, [])
        for comparison in _total_comparison_rows(payload):
            total_comparisons.append({"economy": payload["meta"]["economy"], **comparison})
        rebuilt = html.replace(
            re.search(r"const PAYLOAD = \{.*?\};", html, flags=re.S).group(0),
            "const PAYLOAD = " + json.dumps(payload, separators=(",", ":")) + ";",
            1,
        )
        (output / page.name).write_text(_patch_renderer(rebuilt), encoding="utf-8")
        counts[payload["meta"]["economy"]] = len(additions)
    links = "\n".join(
        f'<li><a href="{page.name}">{page.stem}</a></li>'
        for page in pages
    )
    launcher = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>9th edition versus new road model</title>
<style>body{{font-family:system-ui,sans-serif;max-width:760px;margin:40px auto;padding:0 20px;color:#163238}} a{{color:#087f70}} li{{margin:8px 0}}</style></head>
<body><h1>9th edition versus new road model</h1>
<p>Each page retains the released 9th-edition dashboard and adds fresh default road-model lines. New-model lines are dashed. Use the transport selector's Both option for combined passenger+freight views; rate measures remain separate.</p>
<ul>{links}</ul></body></html>"""
    (output / "index.html").write_text(launcher, encoding="utf-8")
    comparison_frame = pd.DataFrame(total_comparisons)
    if not comparison_frame.empty:
        comparison_frame = comparison_frame.sort_values("relative_difference", ascending=False, na_position="last")
        comparison_frame.to_csv(output / "total_comparison_scan.csv", index=False)
    corrections_frame = pd.DataFrame(stock_corrections)
    if not corrections_frame.empty:
        corrections_frame.to_csv(output / "stock_unit_corrections.csv", index=False)
    manifest = {"source_dashboard": str(source), "merged_energy_source": str(merged_energy_path), "model_root": str(model_root), "pages": counts, "stock_unit_corrections": stock_corrections, "major_total_differences": int(comparison_frame["major_difference"].sum()) if not comparison_frame.empty else 0, "total_comparison_scan": str(output / "total_comparison_scan.csv"), "note": "9th-edition energy is sourced from detailed merged-energy rows from 2023 onward; 2022 energy is intentionally not shown. 2022 9th-edition stock rows are rescaled only when their total is more than 100 times the physical fleet total. Other original dashboard rows are retained."}
    (output / "comparison_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--model-root", type=Path, default=DEFAULT_MODEL_ROOT)
    parser.add_argument("--merged-energy", type=Path, default=DEFAULT_MERGED_ENERGY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.model_root, args.merged_energy, args.output), indent=2))


if __name__ == "__main__":
    main()
