#%%
"""Build standalone road assumptions and results dashboards for all economies."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml


# --- Stable constants ---

DEFAULT_ECONOMY = "05_PRC"
OUTCOME_UNITS = {
    "energy": "PJ",
    "efficiency": "thousand MJ/100km",
    "mileage": "km per vehicle per year",
    "stock": "million fuel-allocated vehicles",
}
DETAIL_MEASURES = {
    "Stocks": ("fuel_allocated_stock", "million fuel-allocated vehicles"),
    "Sales": ("fuel_allocated_sales", "million fuel-allocated vehicles"),
    "Turnover_rate": ("turnover_rate", "share of stock per year"),
    "retirement_rate_used": ("retirement_rate", "share of stock per year"),
}


def extract_json_argument(text: str, marker: str) -> object:
    """Extract the first balanced JSON array/object following a marker."""
    start = text.index(marker) + len(marker)
    while start < len(text) and text[start] not in "[{":
        start += 1
    opening = text[start]
    closing = "]" if opening == "[" else "}"
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return json.loads(text[start : index + 1])
    raise ValueError("Could not find a balanced Plotly JSON argument.")


def decode_plotly_array(value: object) -> list[float] | list[int]:
    """Decode Plotly's compact typed-array representation."""
    if isinstance(value, list):
        return value
    if not isinstance(value, dict) or "bdata" not in value or "dtype" not in value:
        raise ValueError(f"Unexpected Plotly array value: {type(value).__name__}")
    dtype = np.dtype(value["dtype"])
    decoded = np.frombuffer(base64.b64decode(value["bdata"]), dtype=dtype)
    return decoded.tolist()


def scenario_for_outcome_trace(measure: str, trace_name: str) -> str | None:
    """Choose the full, most useful trace for each outcome measure."""
    prefix_to_scenario = {"REF": "Reference", "TGT": "Target"}
    prefix = trace_name.split(",", 1)[0]
    scenario = prefix_to_scenario.get(prefix)
    if scenario is None or "," not in trace_name:
        return None
    stage = trace_name.split(",", 1)[1].strip()
    if measure in {"energy", "stock"} and stage in {"Reconciled", "Reconciled + alternatives"}:
        return scenario
    if measure in {"mileage", "efficiency"} and stage == "Input":
        return scenario
    return None


def load_outcome_series(chart_dir: Path, economy: str) -> pd.DataFrame:
    """Read one economy's road outcome traces from comparison chart files."""
    rows: list[dict] = []
    for chart_path in sorted(chart_dir.glob(f"{economy}__*.html")):
        parts = chart_path.stem.split("__")
        if len(parts) != 4:
            continue
        _, measure, transport_label, fuel = parts
        if transport_label not in {"Passenger_road", "Freight_road"}:
            continue
        if measure not in OUTCOME_UNITS:
            continue
        text = chart_path.read_text(encoding="utf-8")
        traces = extract_json_argument(text, "Plotly.newPlot(")
        parsed_traces = []
        for trace in traces:
            name = trace.get("name", "")
            if "," not in name:
                continue
            prefix, stage = [part.strip() for part in name.split(",", 1)]
            scenario = {"REF": "Reference", "TGT": "Target"}.get(prefix)
            if scenario is None:
                continue
            parsed_traces.append(
                {
                    "scenario": scenario,
                    "stage": stage,
                    "years": decode_plotly_array(trace["x"]),
                    "values": decode_plotly_array(trace["y"]),
                }
            )
        for scenario in ["Reference", "Target"]:
            candidates = [trace for trace in parsed_traces if trace["scenario"] == scenario]
            selected = None
            if measure in {"energy", "stock"}:
                reconciled = [trace for trace in candidates if trace["stage"].startswith("Reconciled") and len(trace["years"]) > 1]
                selected = reconciled[0] if reconciled else next((trace for trace in candidates if trace["stage"] == "Input"), None)
            else:
                selected = next((trace for trace in candidates if trace["stage"] == "Input"), None)
            if selected is None:
                continue
            years = selected["years"]
            values = selected["values"]
            for year, value in zip(years, values):
                rows.append(
                    {
                        "dataset": "outcome",
                        "scenario": scenario,
                        "transport_type": transport_label.split("_")[0].lower(),
                        "vehicle_type": "all",
                        "drive": "all",
                        "fuel": fuel.replace("_", " "),
                        "measure": measure,
                        "year": int(year),
                        "value": float(value),
                        "unit": OUTCOME_UNITS[measure],
                    }
                )
    result = pd.DataFrame(rows)
    if result.empty:
        raise ValueError(f"No road outcome traces were found for {economy}.")
    return result


def load_vehicle_stock(stock_dir: Path, economy: str) -> pd.DataFrame:
    """Load unique physical vehicle stocks by vehicle type."""
    columns = ["dataset", "scenario", "transport_type", "vehicle_type", "drive", "fuel", "measure", "year", "value", "unit"]
    parts = []
    for scenario in ["Reference", "Target"]:
        path = stock_dir / f"{economy}_{scenario}_road_vehicle_type_stock_share_compare.csv"
        if not path.exists():
            return pd.DataFrame(columns=columns)
        frame = pd.read_csv(path)
        frame = frame.rename(
            columns={
                "Date": "year",
                "transport_type_norm": "transport_type",
                "Vehicle Type": "vehicle_type",
                "projected_stock": "value",
            }
        )
        frame["dataset"] = "fleet"
        frame["scenario"] = scenario
        frame["drive"] = "all"
        frame["fuel"] = "all"
        frame["measure"] = "vehicle_stock"
        frame["unit"] = "million vehicles"
        parts.append(frame)
    return pd.concat(parts, ignore_index=True)[columns]


def load_fleet_diagnostics(stock_dir: Path, economy: str) -> pd.DataFrame:
    """Load detailed drive/fuel fleet diagnostics without implying unique counts."""
    columns = ["dataset", "scenario", "transport_type", "vehicle_type", "drive", "fuel", "measure", "year", "value", "unit"]
    parts = []
    for scenario in ["Reference", "Target"]:
        path = stock_dir / f"{economy}_{scenario}_road_stock_detail_with_projection.csv"
        if not path.exists():
            return pd.DataFrame(columns=columns)
        raw = pd.read_csv(path).rename(
            columns={
                "Date": "year",
                "transport_type_norm": "transport_type",
                "Vehicle Type": "vehicle_type",
                "Drive": "drive",
                "Fuel": "fuel",
            }
        )
        for source_column, (measure, unit) in DETAIL_MEASURES.items():
            frame = raw[["year", "transport_type", "vehicle_type", "drive", "fuel", source_column]].copy()
            frame = frame.rename(columns={source_column: "value"})
            frame = frame.loc[frame["value"].notna()]
            frame["dataset"] = "fleet"
            frame["scenario"] = scenario
            frame["measure"] = measure
            frame["unit"] = unit
            parts.append(frame)
    return pd.concat(parts, ignore_index=True)[columns]


def build_assumptions() -> list[dict]:
    """Return plain-language model-wide and PRC-specific assumption notes."""
    return [
        {
            "scope": "How the road model works",
            "title": "Road energy is built from the fleet and its use",
            "explanation": "The model combines vehicle stocks, distance travelled and vehicle efficiency. Passenger activity also depends on occupancy; freight activity depends on average load.",
            "effect": "A change in fleet size, mileage, occupancy/load or efficiency can change activity and energy even when the other inputs stay fixed.",
        },
        {
            "scope": "How the road model works",
            "title": "Sales shares change the fleet gradually",
            "explanation": "New-vehicle sales are divided among drive technologies. Existing vehicles remain until the turnover calculation removes them, so sales changes do not become stock changes immediately.",
            "effect": "Fast EV sales growth can still produce a slower change in the total fleet and fuel use.",
        },
        {
            "scope": "How the road model works",
            "title": "Drive and fuel answer different questions",
            "explanation": "Drive describes the vehicle technology, such as BEV, PHEV or diesel ICE. Fuel is the energy output after fossil, biofuel, electricity, hydrogen and other alternatives are allocated.",
            "effect": "Use drive views to review technology change and fuel views to review the resulting energy mix.",
        },
        {
            "scope": "How the road model works",
            "title": "Reference and Target can use different transition paths",
            "explanation": "Both scenarios begin from the same historical system, but scenario-specific sales, efficiency and other settings can change their future paths.",
            "effect": "Scenario differences should be read as a package of assumptions, not as the effect of one isolated switch.",
        },
        {
            "scope": "China-specific settings",
            "title": "Freight growth is deliberately moderated",
            "explanation": "China uses a 0.20 addition in the freight-to-GDP growth relationship, lower than the 0.35 used for many economies. The code comment links this choice to an expected shift from manufacturing toward services.",
            "effect": "Road freight activity grows more slowly than it would under the common 0.35 setting, all else equal.",
        },
        {
            "scope": "China-specific settings",
            "title": "The vehicle-turnover midpoint is adjusted in both scenarios",
            "explanation": "China's Reference and Target road settings both multiply the standard turnover midpoint by 0.9.",
            "effect": "The age at which half of a cohort is retired is slightly earlier than under an unadjusted midpoint, accelerating fleet renewal.",
        },
        {
            "scope": "China-specific settings",
            "title": "COVID-era road energy adjustments are included",
            "explanation": "For 2020–2022, the configured reductions are 10% for passenger road and 8% for freight road. The return-to-normal factor is 0.75 for passenger and 1.0 for freight.",
            "effect": "Early model years include a temporary shock and recovery rather than extending the disrupted pattern indefinitely.",
        },
        {
            "scope": "Data and interpretation",
            "title": "Outcome measures come from the most complete available stage",
            "explanation": "Energy and stock use the full reconciled results when those series are available. If the comparison output contains only a reconciliation checkpoint, the full model input path is shown instead. Mileage and efficiency use their full input paths.",
            "effect": "The dashboard prioritises a complete time path and explains whether a measure is a reconciled outcome or a model input.",
        },
        {
            "scope": "Data and interpretation",
            "title": "The available road series currently end in 2060",
            "explanation": "The available outcome series run to 2060. Detailed stock, sales, drive and fuel diagnostics also run to 2060 when they are available for the economy.",
            "effect": "The road charts end at 2060 by design; this is a source-data boundary, not a dashboard filter.",
        },
        {
            "scope": "Data and interpretation",
            "title": "Fuel-allocated stocks are not unique vehicle counts",
            "explanation": "A multi-fuel technology can appear under more than one fuel in the detailed diagnostic output. The physical vehicle-stock view is the appropriate view for unique vehicle totals.",
            "effect": "Do not add fuel-allocated stock or sales lines across fuels and interpret the sum as a physical fleet total.",
        },
    ]


def parameter_value(parameters: dict, key: str, economy: str, default: object) -> object:
    """Read one economy's value from a parameters.yml dictionary."""
    values = parameters.get(key, {})
    if not isinstance(values, dict):
        return default
    return values.get(economy, default)


def build_economy_assumptions(economy: str, economy_name: str, parameters: dict, has_fleet_data: bool) -> list[dict]:
    """Return model-wide and economy-specific assumptions in plain language."""
    assumptions = [item.copy() for item in build_assumptions() if item["scope"] in {"How the road model works", "Data and interpretation"}]
    for item in assumptions:
        item["title"] = item["title"].replace("PRC", "road")
        item["explanation"] = item["explanation"].replace("PRC", "the economy")

    economy_scope = f"{economy_name}-specific settings"
    freight_addition = float(parameter_value(parameters, "NON_INDUSTRY_FREIGHT_ADDITION", economy, 0.35))
    if freight_addition < 0.35:
        freight_effect = "This moderates freight activity growth relative to the common 0.35 setting, all else equal."
    elif freight_addition > 0.35:
        freight_effect = "This raises freight activity growth relative to the common 0.35 setting, all else equal."
    else:
        freight_effect = "This uses the common freight-growth setting applied to most economies."
    assumptions.append(
        {
            "scope": economy_scope,
            "title": "Freight activity is linked to GDP and industry growth",
            "explanation": f"{economy_name} uses an addition of {freight_addition:.2f} in the freight-to-GDP growth relationship. The common setting across most economies is 0.35.",
            "effect": freight_effect,
        }
    )

    reference_turnover = float(parameter_value(parameters, "TURNOVER_RATE_MIDPOINT_MULT_ADJUSTMENT_ROAD_REFERENCE", economy, 1.0))
    target_turnover = float(parameter_value(parameters, "TURNOVER_RATE_MIDPOINT_MULT_ADJUSTMENT_ROAD_TARGET", economy, 1.0))
    if reference_turnover != 1.0 or target_turnover != 1.0:
        assumptions.append(
            {
                "scope": economy_scope,
                "title": "The vehicle-turnover midpoint is adjusted",
                "explanation": f"The standard turnover midpoint is multiplied by {reference_turnover:g} in Reference and {target_turnover:g} in Target.",
                "effect": "A multiplier below 1 brings forward fleet retirement and makes changes in new-vehicle sales appear in the total fleet sooner.",
            }
        )

    passenger_covid = float(parameter_value(parameters, "EXPECTED_ENERGY_DECREASE_FROM_COVID_PASSENGER_ROAD", economy, 0.0))
    freight_covid = float(parameter_value(parameters, "EXPECTED_ENERGY_DECREASE_FROM_COVID_FREIGHT_ROAD", economy, 0.0))
    if passenger_covid > 0 or freight_covid > 0:
        passenger_years = parameter_value(parameters, "LISTED_YEARS_WHEN_COVID_EFFECTS_APPLIED_PASSENGER_ROAD", economy, [])
        freight_years = parameter_value(parameters, "LISTED_YEARS_WHEN_COVID_EFFECTS_APPLIED_FREIGHT_ROAD", economy, [])
        passenger_return = float(parameter_value(parameters, "EXPECTED_RETURN_TO_NORMAL_ACTIVITY_FROM_COVID_PASSENGER_ROAD", economy, 1.0))
        freight_return = float(parameter_value(parameters, "EXPECTED_RETURN_TO_NORMAL_ACTIVITY_FROM_COVID_FREIGHT_ROAD", economy, 1.0))
        years = sorted(set(list(passenger_years) + list(freight_years)))
        year_text = f"{years[0]}–{years[-1]}" if len(years) > 1 else str(years[0]) if years else "the COVID period"
        assumptions.append(
            {
                "scope": economy_scope,
                "title": "COVID-era road adjustments are included",
                "explanation": f"For {year_text}, the configured energy reductions are {passenger_covid:.1%} for passenger road and {freight_covid:.1%} for freight road. The return-to-normal factors are {passenger_return:g} and {freight_return:g}, respectively.",
                "effect": "The early model years include a temporary shock and recovery instead of extending the disrupted pattern indefinitely.",
            }
        )

    if bool(parameter_value(parameters, "ECONOMIES_WITH_MAX_STOCKS_PER_CAPITA_REACHED", economy, False)):
        assumptions.append(
            {
                "scope": economy_scope,
                "title": "Passenger vehicle ownership is treated as having reached its saturation range",
                "explanation": "The configuration flags this economy as having reached the model's maximum-stocks-per-capita range.",
                "effect": "Long-run passenger vehicle stock growth is constrained rather than continuing to rise freely with income.",
            }
        )

    if not has_fleet_data:
        assumptions.append(
            {
                "scope": "Data and interpretation",
                "title": "Detailed fleet diagnostics are not available for this economy",
                "explanation": f"The extracted diagnostic folder contains road outcomes for {economy_name}, but not the detailed stock, sales, drive and fuel projection files.",
                "effect": "The Model outcomes page remains available; the Fleet transition page explains that its detailed source is unavailable.",
            }
        )
    return assumptions


def write_dashboard(template_path: Path, output_path: Path, payload: dict) -> None:
    """Embed the payload in a standalone HTML template."""
    template = template_path.read_text(encoding="utf-8")
    marker = "__ROAD_DASHBOARD_DATA__"
    if marker not in template:
        raise ValueError("Road dashboard template is missing its data placeholder.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        template.replace(marker, json.dumps(payload, separators=(",", ":"), ensure_ascii=True)),
        encoding="utf-8",
    )


def run_prc_road_dashboard_workflow(chart_dir: Path, stock_dir: Path, template_path: Path, output_dir: Path) -> dict:
    """Build data exports and the standalone dashboard."""
    outcome = load_outcome_series(chart_dir=chart_dir, economy=DEFAULT_ECONOMY)
    vehicle_stock = load_vehicle_stock(stock_dir=stock_dir, economy=DEFAULT_ECONOMY)
    diagnostics = load_fleet_diagnostics(stock_dir=stock_dir, economy=DEFAULT_ECONOMY)
    all_data = pd.concat([outcome, vehicle_stock, diagnostics], ignore_index=True)

    output_dir.mkdir(parents=True, exist_ok=True)
    outcome.to_csv(output_dir / "prc_road_outcomes_2022_2060.csv", index=False)
    pd.concat([vehicle_stock, diagnostics], ignore_index=True).to_csv(
        output_dir / "prc_road_fleet_diagnostics_2022_2060.csv", index=False
    )
    all_data.to_csv(output_dir / "prc_road_dashboard_all_data.csv", index=False)
    assumptions = pd.DataFrame(build_assumptions())
    assumptions.to_csv(output_dir / "prc_road_assumptions_explained.csv", index=False)

    payload = build_economy_payload(
        economy=DEFAULT_ECONOMY,
        economy_name="China",
        economy_names={DEFAULT_ECONOMY: "China"},
        all_data=all_data,
        assumptions=assumptions.to_dict(orient="records"),
        has_fleet_data=True,
    )
    write_dashboard(template_path, output_dir / "prc_road_assumptions_dashboard.html", payload)
    (output_dir / "prc_road_dashboard_data.json").write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
    summary = {
        "outcome_rows": len(outcome),
        "physical_stock_rows": len(vehicle_stock),
        "diagnostic_rows": len(diagnostics),
        "html_bytes": (output_dir / "prc_road_assumptions_dashboard.html").stat().st_size,
    }
    print(json.dumps(summary, indent=2))
    return summary


def load_economy_names(concordance_path: Path) -> dict[str, str]:
    """Load the 21 economy codes and dashboard display names."""
    concordance = pd.read_csv(concordance_path)
    return dict(zip(concordance["Economy"].astype(str), concordance["Economy_name"].astype(str)))


def add_economy_columns(frame: pd.DataFrame, economy: str, economy_name: str) -> pd.DataFrame:
    """Add economy identifiers to a CSV export without changing embedded rows."""
    exported = frame.copy()
    exported.insert(0, "economy_name", economy_name)
    exported.insert(0, "economy", economy)
    return exported


def build_economy_payload(
    economy: str,
    economy_name: str,
    economy_names: dict[str, str],
    all_data: pd.DataFrame,
    assumptions: list[dict],
    has_fleet_data: bool,
) -> dict:
    """Build a compact payload for one standalone economy dashboard."""
    data_columns = ["dataset", "scenario", "transport_type", "vehicle_type", "drive", "fuel", "measure", "year", "value"]
    embedded = all_data[data_columns].copy()
    embedded["value"] = embedded["value"].round(9)
    dashboard_files = {code: f"road_transport_assumptions_dashboard_{code}.html" for code in economy_names}
    outcome_years = all_data.loc[all_data["dataset"] == "outcome", "year"]
    fleet_years = all_data.loc[all_data["dataset"] == "fleet", "year"]
    outcome_horizon = f"{int(outcome_years.min())}–{int(outcome_years.max())}"
    fleet_horizon = f"{int(fleet_years.min())}–{int(fleet_years.max())}" if not fleet_years.empty else None
    return {
        "meta": {
            "economy": economy,
            "economy_name": economy_name,
            "economies": economy_names,
            "dashboard_files": dashboard_files,
            "has_fleet_data": has_fleet_data,
            "outcome_horizon": outcome_horizon,
            "fleet_horizon": fleet_horizon,
        },
        "data_columns": data_columns,
        "data_rows": embedded.values.tolist(),
        "assumptions": assumptions,
    }


def run_all_economies_road_dashboard_workflow(
    chart_dir: Path,
    stock_dir: Path,
    template_path: Path,
    concordance_path: Path,
    parameters_path: Path,
    output_dir: Path,
    default_economy: str,
) -> pd.DataFrame:
    """Generate one self-contained road dashboard and data bundle per economy."""
    economy_names = load_economy_names(concordance_path)
    parameters = yaml.safe_load(parameters_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    summary_rows = []

    for economy, economy_name in economy_names.items():
        print(f"Building road dashboard for {economy} {economy_name}...")
        outcome = load_outcome_series(chart_dir=chart_dir, economy=economy)
        vehicle_stock = load_vehicle_stock(stock_dir=stock_dir, economy=economy)
        diagnostics = load_fleet_diagnostics(stock_dir=stock_dir, economy=economy)
        has_fleet_data = not vehicle_stock.empty and not diagnostics.empty
        fleet_parts = [frame for frame in [vehicle_stock, diagnostics] if not frame.empty]
        fleet = pd.concat(fleet_parts, ignore_index=True) if fleet_parts else vehicle_stock.copy()
        all_data = pd.concat([outcome, fleet], ignore_index=True) if not fleet.empty else outcome.copy()
        assumptions = build_economy_assumptions(
            economy=economy,
            economy_name=economy_name,
            parameters=parameters,
            has_fleet_data=has_fleet_data,
        )

        add_economy_columns(outcome, economy, economy_name).to_csv(data_dir / f"road_outcomes_{economy}.csv", index=False)
        add_economy_columns(fleet, economy, economy_name).to_csv(data_dir / f"road_fleet_diagnostics_{economy}.csv", index=False)
        add_economy_columns(all_data, economy, economy_name).to_csv(data_dir / f"road_dashboard_all_data_{economy}.csv", index=False)
        pd.DataFrame(assumptions).to_csv(data_dir / f"road_assumptions_explained_{economy}.csv", index=False)

        payload = build_economy_payload(
            economy=economy,
            economy_name=economy_name,
            economy_names=economy_names,
            all_data=all_data,
            assumptions=assumptions,
            has_fleet_data=has_fleet_data,
        )
        dashboard_path = output_dir / f"road_transport_assumptions_dashboard_{economy}.html"
        write_dashboard(template_path=template_path, output_path=dashboard_path, payload=payload)
        summary_rows.append(
            {
                "economy": economy,
                "economy_name": economy_name,
                "outcome_rows": len(outcome),
                "fleet_rows": len(fleet),
                "has_fleet_data": has_fleet_data,
                "dashboard_bytes": dashboard_path.stat().st_size,
            }
        )

    default_path = output_dir / f"road_transport_assumptions_dashboard_{default_economy}.html"
    default_html = default_path.read_text(encoding="utf-8")
    (output_dir / "road_transport_assumptions_dashboard_all_economies.html").write_text(default_html, encoding="utf-8")
    (output_dir / "prc_road_assumptions_dashboard.html").write_text(default_html, encoding="utf-8")
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(data_dir / "road_dashboard_build_summary_all_economies.csv", index=False)
    print(summary.to_string(index=False))
    return summary


# --- Frequently changed settings ---

WORKFLOW_DIR = Path(__file__).resolve().parent
# The migrated CLI requires explicit --road-chart-dir and --road-stock-dir paths.
CHART_DIR = Path("road_charts")
STOCK_DIR = Path("road_fleet_diagnostics")
TEMPLATE_PATH = WORKFLOW_DIR / "prc_road_dashboard_template.html"
OUTPUT_DIR = WORKFLOW_DIR.parents[1] / "outputs" / "road_transport_assumptions_dashboard"
CONCORDANCE_PATH = WORKFLOW_DIR.parent / "transport_model_9th_edition_code" / "transport_model_9th_edition" / "config" / "concordances_and_config_data" / "economy_code_to_name.csv"
PARAMETERS_PATH = WORKFLOW_DIR.parent / "transport_model_9th_edition_code" / "transport_model_9th_edition" / "config" / "parameters.yml"
RUN_PRC_ROAD_DASHBOARD_WORKFLOW = False
# The original notebook executed on import.  The migrated entry point invokes
# ``run_all_economies_road_dashboard_workflow`` explicitly after checking paths.
RUN_ALL_ECONOMIES_ROAD_DASHBOARD_WORKFLOW = False


# --- Notebook-style run block ---

if RUN_PRC_ROAD_DASHBOARD_WORKFLOW:
    try:
        PRC_ROAD_DASHBOARD_SUMMARY = run_prc_road_dashboard_workflow(
            chart_dir=CHART_DIR,
            stock_dir=STOCK_DIR,
            template_path=TEMPLATE_PATH,
            output_dir=OUTPUT_DIR,
        )
    except Exception as error:
        print(f"PRC road dashboard workflow failed: {type(error).__name__}: {error}")
        raise

if RUN_ALL_ECONOMIES_ROAD_DASHBOARD_WORKFLOW:
    try:
        ALL_ECONOMIES_ROAD_SUMMARY = run_all_economies_road_dashboard_workflow(
            chart_dir=CHART_DIR,
            stock_dir=STOCK_DIR,
            template_path=TEMPLATE_PATH,
            concordance_path=CONCORDANCE_PATH,
            parameters_path=PARAMETERS_PATH,
            output_dir=OUTPUT_DIR,
            default_economy=DEFAULT_ECONOMY,
        )
    except Exception as error:
        print(f"All-economies road dashboard workflow failed: {type(error).__name__}: {error}")
        raise

#%%
