#%%
"""Create all-economy non-road review data and the interactive dashboard.

The workflow uses one latest archived model-output file, user-input file and
fuel-energy file per APEC economy. It is designed to be run interactively from
Jupyter, with the configuration toggles at the bottom of this file.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from . import non_road_assumptions_workflow as base


# --- Stable constants ---

NON_ROAD_MEDIA = ["air", "rail", "ship"]
TRANSPORT_TYPES = ["passenger", "freight"]
SCENARIOS = ["Reference", "Target"]

SECTOR_TO_MEDIUM = {
    "15_01_domestic_air_transport": "air",
    "15_03_rail": "rail",
    "15_04_domestic_navigation": "ship",
}

SUBSECTOR_TO_TRANSPORT_TYPE = {
    "15_01_01_passenger": "passenger",
    "15_01_02_freight": "freight",
    "15_03_01_passenger": "passenger",
    "15_03_02_freight": "freight",
    "15_04_01_passenger": "passenger",
    "15_04_02_freight": "freight",
}


# --- File discovery ---

def load_economy_names(concordance_path: Path) -> dict[str, str]:
    """Load the canonical 21-economy name mapping."""
    data = pd.read_csv(concordance_path)
    base.require_columns(data, ["Economy", "Economy_name"], concordance_path.name)
    return dict(zip(data["Economy"], data["Economy_name"]))


def discover_latest_files(raw_dir: Path, economy_names: dict[str, str]) -> tuple[dict, dict, dict, dict, dict]:
    """Find the selectively extracted latest files and parse their vintages."""
    model_files: dict[str, str] = {}
    model_vintages: dict[str, str] = {}
    input_files: dict[str, str] = {}
    energy_files: dict[str, str] = {}
    energy_vintages: dict[str, str] = {}

    for economy in economy_names:
        model_matches = sorted(raw_dir.glob(f"{economy}_NON_ROAD_DETAILED_model_output*.csv"))
        input_matches = sorted(raw_dir.glob(f"{economy}_user_inputs_and_growth_rates.csv"))
        energy_matches = sorted(raw_dir.glob(f"{economy}_*_transport_energy_use.csv"))
        if len(model_matches) != 1 or len(input_matches) != 1 or len(energy_matches) != 1:
            raise FileNotFoundError(
                f"{economy}: expected one model, input and energy file; got "
                f"{len(model_matches)}, {len(input_matches)}, {len(energy_matches)}"
            )

        model_path = model_matches[0]
        energy_path = energy_matches[0]
        model_date = re.search(r"model_output(\d{8})", model_path.name)
        energy_date = re.search(rf"{re.escape(economy)}_(\d{{8}})_transport", energy_path.name)
        if not model_date or not energy_date:
            raise ValueError(f"Could not parse source vintages for {economy}")

        model_files[economy] = model_path.name
        input_files[economy] = input_matches[0].name
        energy_files[economy] = energy_path.name
        model_vintages[economy] = pd.to_datetime(model_date.group(1)).strftime("%Y-%m-%d")
        energy_vintages[economy] = pd.to_datetime(energy_date.group(1)).strftime("%Y-%m-%d")

    return model_files, model_vintages, input_files, energy_files, energy_vintages


# --- Source transformations ---

def load_drive_output(
    raw_dir: Path,
    economy: str,
    source_name: str,
    source_vintage: str,
    economy_names: dict[str, str],
    end_year: int,
) -> pd.DataFrame:
    """Load compact detailed-drive output and calculate intensity and growth."""
    source_path = raw_dir / source_name
    required = ["Date", "Economy", "Scenario", "Transport Type", "Drive", "Medium", "Activity", "Energy"]
    data = pd.read_csv(source_path, usecols=required)
    data = data.loc[
        data["Medium"].isin(NON_ROAD_MEDIA)
        & data["Transport Type"].isin(TRANSPORT_TYPES)
        & data["Scenario"].isin(SCENARIOS)
        & data["Date"].le(end_year)
    ].copy()
    data["Activity"] = pd.to_numeric(data["Activity"], errors="coerce").fillna(0)
    data["Energy"] = pd.to_numeric(data["Energy"], errors="coerce").fillna(0)

    keys = ["Economy", "Date", "Medium", "Transport Type", "Drive", "Scenario"]
    data = data.groupby(keys, as_index=False)[["Activity", "Energy"]].sum()
    data["Intensity"] = data["Energy"].div(data["Activity"].replace(0, np.nan)).fillna(0)
    growth_keys = ["Economy", "Medium", "Transport Type", "Drive", "Scenario"]
    data = data.sort_values(growth_keys + ["Date"])
    data["Activity_growth"] = (
        data.groupby(growth_keys)["Activity"].pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).fillna(0)
    )
    data["Economy_name"] = data["Economy"].map(economy_names)
    data["Source"] = source_name
    data["Source_vintage"] = source_vintage
    return data


def load_user_inputs(
    raw_dir: Path,
    economy: str,
    source_name: str,
    source_vintage: str,
    economy_names: dict[str, str],
    end_year: int,
) -> pd.DataFrame:
    """Load explicit non-road user-input assumptions."""
    source_path = raw_dir / source_name
    data = pd.read_csv(source_path)
    required = ["Date", "Economy", "Measure", "Medium", "Transport Type", "Drive", "Scenario", "Unit", "Value", "Data_available"]
    base.require_columns(data, required, source_path.name)
    data = data.loc[
        data["Medium"].isin(NON_ROAD_MEDIA)
        & data["Transport Type"].isin(TRANSPORT_TYPES)
        & data["Scenario"].isin(SCENARIOS)
        & data["Date"].le(end_year)
    ].copy()
    data["Value"] = pd.to_numeric(data["Value"], errors="coerce")
    data["Economy_name"] = data["Economy"].map(economy_names)
    data["Source"] = source_name
    data["Source_vintage"] = source_vintage
    return data


def attach_intensity_improvement(drive: pd.DataFrame, user_inputs: pd.DataFrame) -> pd.DataFrame:
    """Attach the explicit intensity-improvement factor to each drive row."""
    keys = ["Economy", "Date", "Medium", "Transport Type", "Drive", "Scenario"]
    improvement = user_inputs.loc[
        user_inputs["Measure"].eq("Non_road_intensity_improvement"), keys + ["Value"]
    ].groupby(keys, as_index=False)["Value"].mean().rename(columns={"Value": "Non_road_intensity_improvement"})
    result = drive.merge(improvement, on=keys, how="left")
    result["Non_road_intensity_improvement"] = result["Non_road_intensity_improvement"].fillna(1.0)
    return result


def load_fuel_energy(
    raw_dir: Path,
    economy: str,
    source_name: str,
    source_vintage: str,
    economy_names: dict[str, str],
    end_year: int,
) -> pd.DataFrame:
    """Load and tidy Outlook-format final energy by individual fuel."""
    source_path = raw_dir / source_name
    data = pd.read_csv(source_path)
    required = ["economy", "scenarios", "fuels", "subfuels", "sub1sectors", "sub2sectors"]
    base.require_columns(data, required, source_path.name)
    year_columns = [column for column in data.columns if column.isdigit() and int(column) <= end_year]
    data["Medium"] = data["sub1sectors"].map(SECTOR_TO_MEDIUM)
    data["Transport Type"] = data["sub2sectors"].map(SUBSECTOR_TO_TRANSPORT_TYPE)
    data["Fuel"] = data.apply(base.choose_output_fuel, axis=1)
    data["Scenario"] = data["scenarios"].str.title()
    data = data.loc[data["Medium"].notna() & data["Transport Type"].notna() & data["Scenario"].isin(SCENARIOS)].copy()
    tidy = data.melt(
        id_vars=["economy", "Scenario", "Medium", "Transport Type", "Fuel"],
        value_vars=year_columns,
        var_name="Date",
        value_name="Fuel_energy",
    )
    tidy["Date"] = tidy["Date"].astype(int)
    tidy["Fuel_energy"] = pd.to_numeric(tidy["Fuel_energy"], errors="coerce").fillna(0)
    tidy = tidy.groupby(["economy", "Date", "Medium", "Transport Type", "Fuel", "Scenario"], as_index=False)["Fuel_energy"].sum().rename(columns={"economy": "Economy"})
    tidy["Economy_name"] = tidy["Economy"].map(economy_names)
    tidy["Source"] = source_name
    tidy["Source_vintage"] = source_vintage
    return tidy


def build_payload(
    drive: pd.DataFrame,
    fuel: pd.DataFrame,
    economy_names: dict[str, str],
    model_vintages: dict[str, str],
    energy_vintages: dict[str, str],
    end_year: int,
) -> dict:
    """Build the nested annual series object used by the dashboard."""
    start_years = drive.groupby("Economy")["Date"].min().astype(int).to_dict()
    series: dict = {}
    share_keys = ["Economy", "Date", "Medium", "Transport Type", "Scenario"]

    drive_share = drive.copy()
    drive_share["Drive_share"] = drive_share["Activity"].div(
        drive_share.groupby(share_keys)["Activity"].transform("sum").replace(0, np.nan)
    ).fillna(0)
    fuel_share = fuel.copy()
    fuel_share["Fuel_share"] = fuel_share["Fuel_energy"].div(
        fuel_share.groupby(share_keys)["Fuel_energy"].transform("sum").replace(0, np.nan)
    ).fillna(0)
    total_activity = drive.groupby(share_keys, as_index=False)["Activity"].sum().assign(Series="total activity")

    for measure, value_column in [
        ("activity", "Activity"),
        ("drive_energy", "Energy"),
        ("intensity", "Intensity"),
        ("activity_growth", "Activity_growth"),
        ("intensity_improvement", "Non_road_intensity_improvement"),
    ]:
        base.add_nested_series(series, drive, measure, "Drive", value_column, start_years, end_year)
    base.add_nested_series(series, drive_share, "drive_share", "Drive", "Drive_share", start_years, end_year)
    base.add_nested_series(series, total_activity, "total_activity", "Series", "Activity", start_years, end_year)
    base.add_nested_series(series, fuel, "fuel_energy", "Fuel", "Fuel_energy", start_years, end_year)
    base.add_nested_series(series, fuel_share, "fuel_share", "Fuel", "Fuel_share", start_years, end_year)

    return {
        "metadata": {
            "economies": economy_names,
            "start_years": start_years,
            "end_year": end_year,
            "model_output_vintages": model_vintages,
            "fuel_energy_vintages": energy_vintages,
            "fuel_assumption_vintage": "2025-10-03",
        },
        "series": series,
    }


def build_exception_candidates(
    drive: pd.DataFrame,
    model_vintages: dict[str, str],
    energy_vintages: dict[str, str],
) -> pd.DataFrame:
    """Create a review queue of numerical patterns that may represent exceptions."""
    candidates: list[dict] = []
    keys = ["Economy", "Scenario", "Medium", "Transport Type"]
    totals = drive.groupby(keys + ["Date"], as_index=False)["Activity"].sum()
    active_drives = drive.loc[drive["Activity"].gt(0)].groupby(keys)["Drive"].nunique()

    for group_values, group in totals.groupby(keys):
        economy, scenario, medium, transport_type = group_values
        values = group.sort_values("Date")["Activity"]
        common = {"Economy": economy, "Scenario": scenario, "Medium": medium, "Transport_type": transport_type, "Review_status": "Needs review"}
        if values.abs().max() == 0:
            candidates.append({**common, "Category": "zero activity", "Summary": "Activity remains zero for the full model horizon.", "Evidence": "max activity = 0"})
        elif np.isclose(values.max(), values.min(), rtol=1e-9, atol=1e-12):
            candidates.append({**common, "Category": "flat activity", "Summary": "Activity is held constant for the full model horizon.", "Evidence": f"constant activity = {values.iloc[0]:.6g}"})
        count = int(active_drives.get(group_values, 0))
        if count <= 1:
            candidates.append({**common, "Category": "single active drive", "Summary": "Only one drive carries non-zero activity.", "Evidence": f"active drives = {count}"})

    for economy in model_vintages:
        if model_vintages[economy] != energy_vintages[economy]:
            candidates.append({
                "Economy": economy,
                "Scenario": "all",
                "Medium": "all",
                "Transport_type": "all",
                "Category": "source vintage mismatch",
                "Summary": "Drive and fuel-energy outputs come from different run dates.",
                "Evidence": f"drive {model_vintages[economy]}; fuel {energy_vintages[economy]}",
                "Review_status": "Needs review",
            })

    result = pd.DataFrame(candidates)
    result.insert(0, "Candidate_id", [f"EXC-{index:04d}" for index in range(1, len(result) + 1)])
    return result


def run_all_economies_workflow(
    raw_dir: Path,
    concordance_path: Path,
    template_path: Path,
    dashboard_fragment_path: Path,
    output_dir: Path,
    end_year: int,
) -> dict:
    """Run extraction transformations, exports, dashboard build and exception scan."""
    economy_names = load_economy_names(concordance_path)
    model_files, model_vintages, input_files, energy_files, energy_vintages = discover_latest_files(raw_dir, economy_names)
    base.ECONOMY_NAMES = economy_names

    drive_parts = []
    input_parts = []
    fuel_parts = []
    for economy in economy_names:
        print(f"Processing {economy} {economy_names[economy]}...")
        drive_parts.append(load_drive_output(raw_dir, economy, model_files[economy], model_vintages[economy], economy_names, end_year))
        input_parts.append(load_user_inputs(raw_dir, economy, input_files[economy], model_vintages[economy], economy_names, end_year))
        fuel_parts.append(load_fuel_energy(raw_dir, economy, energy_files[economy], energy_vintages[economy], economy_names, end_year))

    drive = pd.concat(drive_parts, ignore_index=True)
    user_inputs = pd.concat(input_parts, ignore_index=True)
    drive = attach_intensity_improvement(drive, user_inputs)
    fuel = pd.concat(fuel_parts, ignore_index=True)
    fuel_mix = base.load_fuel_mix_assumptions(raw_dir, end_year)
    qa = base.build_reconciliation(drive, fuel)
    exceptions = build_exception_candidates(drive, model_vintages, energy_vintages)
    payload = build_payload(drive, fuel, economy_names, model_vintages, energy_vintages, end_year)

    output_dir.mkdir(parents=True, exist_ok=True)
    drive.to_csv(output_dir / "non_road_drive_timeseries_all_economies.csv", index=False)
    fuel.to_csv(output_dir / "non_road_fuel_energy_all_economies.csv", index=False)
    user_inputs.to_csv(output_dir / "non_road_user_inputs_all_economies.csv", index=False)
    fuel_mix.to_csv(output_dir / "non_road_fuel_mix_assumptions_all_economies.csv", index=False)
    qa.to_csv(output_dir / "non_road_energy_reconciliation_all_economies.csv", index=False)
    exceptions.to_csv(output_dir / "economy_exception_candidates_all_economies.csv", index=False)
    (output_dir / "dashboard_data_all_economies.json").write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
    base.write_dashboard(template_path, dashboard_fragment_path, payload)

    summary = {
        "economies": len(economy_names),
        "drive_rows": len(drive),
        "fuel_rows": len(fuel),
        "user_input_rows": len(user_inputs),
        "fuel_mix_rows": len(fuel_mix),
        "exception_candidates": len(exceptions),
        "fragment_bytes": dashboard_fragment_path.stat().st_size,
    }
    print(json.dumps(summary, indent=2))
    return summary


# --- Frequently changed run settings ---

WORKFLOW_DIR = Path(__file__).resolve().parent
RAW_DIR = WORKFLOW_DIR / "data" / "raw_all"
CONCORDANCE_PATH = WORKFLOW_DIR.parent / "transport_model_9th_edition_code" / "transport_model_9th_edition" / "config" / "concordances_and_config_data" / "economy_code_to_name.csv"
TEMPLATE_PATH = WORKFLOW_DIR / "dashboard_template.html"
DASHBOARD_FRAGMENT_PATH = WORKFLOW_DIR / "all_economies_dashboard_fragment.html"
OUTPUT_DIR = WORKFLOW_DIR.parents[1] / "outputs" / "non_road_assumptions_dashboard"
END_YEAR = 2070
# The original notebook executed on import.  The migrated entry point invokes
# ``run_all_economies_workflow`` explicitly after checking supplied paths.
RUN_ALL_ECONOMIES_WORKFLOW = False


# --- Notebook-style run block ---

if RUN_ALL_ECONOMIES_WORKFLOW:
    try:
        ALL_ECONOMIES_SUMMARY = run_all_economies_workflow(
            raw_dir=RAW_DIR,
            concordance_path=CONCORDANCE_PATH,
            template_path=TEMPLATE_PATH,
            dashboard_fragment_path=DASHBOARD_FRAGMENT_PATH,
            output_dir=OUTPUT_DIR,
            end_year=END_YEAR,
        )
    except Exception as error:
        print(f"All-economy workflow failed: {type(error).__name__}: {error}")
        raise

#%%
