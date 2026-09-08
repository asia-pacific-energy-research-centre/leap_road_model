#%%
"""Build a compact, review-ready non-road assumptions dataset and dashboard.

The workflow intentionally starts with Russia and PRC as a validation pair. It
uses selectively extracted files rather than unpacking the full model archive.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


# --- Stable constants ---

ECONOMY_NAMES = {
    "05_PRC": "China",
    "16_RUS": "Russia",
}

MODEL_OUTPUT_FILES = {
    "05_PRC": "20250225_05_PRC_detailed_incl_non_road.csv",
    "16_RUS": "20250331_16_RUS_detailed_incl_non_road.csv",
}

MODEL_OUTPUT_VINTAGES = {
    "05_PRC": "2025-02-25",
    "16_RUS": "2025-03-31",
}

ENERGY_OUTPUT_FILES = {
    "05_PRC": "05_PRC_20241108_transport_energy_use.csv",
    "16_RUS": "16_RUS_20241108_transport_energy_use.csv",
}

ENERGY_OUTPUT_VINTAGE = "2024-11-08"
FUEL_ASSUMPTION_VINTAGE = "2025-10-03"
NON_ROAD_MEDIA = ["air", "rail", "ship"]
SCENARIOS = ["Reference", "Target"]
TRANSPORT_TYPES = ["passenger", "freight"]

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

DRIVE_COLUMNS = [
    "Economy",
    "Date",
    "Medium",
    "Transport Type",
    "Drive",
    "Scenario",
    "Activity",
    "Energy",
    "Intensity",
    "Non_road_intensity_improvement",
    "Activity_growth",
]


# --- Validation and transformation functions ---

def require_columns(data: pd.DataFrame, required: list[str], dataset_name: str) -> None:
    """Raise a useful error when an input schema is incomplete."""
    missing = sorted(set(required) - set(data.columns))
    if missing:
        raise ValueError(f"{dataset_name} is missing columns: {missing}")


def load_drive_output(raw_dir: Path, economy: str, end_year: int) -> pd.DataFrame:
    """Load annual non-road drive activity, energy, intensity and growth."""
    source_path = raw_dir / MODEL_OUTPUT_FILES[economy]
    data = pd.read_csv(source_path, usecols=DRIVE_COLUMNS)
    require_columns(data, DRIVE_COLUMNS, source_path.name)

    data = data.loc[
        data["Medium"].isin(NON_ROAD_MEDIA)
        & data["Transport Type"].isin(TRANSPORT_TYPES)
        & data["Scenario"].isin(SCENARIOS)
        & data["Date"].between(2021, end_year)
    ].copy()

    numeric_columns = [
        "Activity",
        "Energy",
        "Intensity",
        "Non_road_intensity_improvement",
        "Activity_growth",
    ]
    for column in numeric_columns:
        data[column] = pd.to_numeric(data[column], errors="coerce")

    group_columns = ["Economy", "Date", "Medium", "Transport Type", "Drive", "Scenario"]
    grouped = (
        data.groupby(group_columns, dropna=False, as_index=False)
        .agg(
            Activity=("Activity", "sum"),
            Energy=("Energy", "sum"),
            Source_intensity=("Intensity", "mean"),
            Non_road_intensity_improvement=("Non_road_intensity_improvement", "mean"),
            Activity_growth=("Activity_growth", "mean"),
        )
    )

    calculated_intensity = grouped["Energy"].div(grouped["Activity"].replace(0, np.nan))
    grouped["Intensity"] = calculated_intensity.fillna(grouped["Source_intensity"])
    grouped["Economy_name"] = grouped["Economy"].map(ECONOMY_NAMES)
    grouped["Source"] = source_path.name
    grouped["Source_vintage"] = MODEL_OUTPUT_VINTAGES[economy]
    return grouped.drop(columns="Source_intensity")


def choose_output_fuel(row: pd.Series) -> str:
    """Prefer a detailed subfuel code and fall back to the broad fuel code."""
    subfuel = str(row["subfuels"])
    return str(row["fuels"]) if subfuel.lower() in {"x", "nan", "none"} else subfuel


def load_fuel_energy(raw_dir: Path, economy: str, end_year: int) -> pd.DataFrame:
    """Load the Outlook-format annual fuel-energy output and make it tidy."""
    source_path = raw_dir / ENERGY_OUTPUT_FILES[economy]
    data = pd.read_csv(source_path)
    required = ["economy", "scenarios", "fuels", "subfuels", "sub1sectors", "sub2sectors"]
    require_columns(data, required, source_path.name)

    year_columns = [column for column in data.columns if column.isdigit() and int(column) <= end_year]
    data["Medium"] = data["sub1sectors"].map(SECTOR_TO_MEDIUM)
    data["Transport Type"] = data["sub2sectors"].map(SUBSECTOR_TO_TRANSPORT_TYPE)
    data["Fuel"] = data.apply(choose_output_fuel, axis=1)
    data["Scenario"] = data["scenarios"].str.title()
    data = data.loc[
        data["Medium"].notna()
        & data["Transport Type"].notna()
        & data["Scenario"].isin(SCENARIOS)
    ].copy()

    tidy = data.melt(
        id_vars=["economy", "Scenario", "Medium", "Transport Type", "Fuel"],
        value_vars=year_columns,
        var_name="Date",
        value_name="Fuel_energy",
    )
    tidy["Date"] = tidy["Date"].astype(int)
    tidy["Fuel_energy"] = pd.to_numeric(tidy["Fuel_energy"], errors="coerce").fillna(0)
    tidy = (
        tidy.groupby(
            ["economy", "Date", "Medium", "Transport Type", "Fuel", "Scenario"],
            as_index=False,
        )["Fuel_energy"]
        .sum()
        .rename(columns={"economy": "Economy"})
    )
    tidy["Economy_name"] = tidy["Economy"].map(ECONOMY_NAMES)
    tidy["Source"] = source_path.name
    tidy["Source_vintage"] = ENERGY_OUTPUT_VINTAGE
    return tidy


def load_user_inputs(raw_dir: Path, economy: str, end_year: int) -> pd.DataFrame:
    """Load explicit non-road input measures for provenance and review."""
    source_path = raw_dir / f"{economy}_user_inputs_and_growth_rates.csv"
    data = pd.read_csv(source_path)
    required = [
        "Date",
        "Economy",
        "Measure",
        "Medium",
        "Transport Type",
        "Drive",
        "Scenario",
        "Unit",
        "Value",
        "Data_available",
    ]
    require_columns(data, required, source_path.name)
    data = data.loc[
        data["Medium"].isin(NON_ROAD_MEDIA)
        & data["Transport Type"].isin(TRANSPORT_TYPES)
        & data["Scenario"].isin(SCENARIOS)
        & data["Date"].between(2021, end_year)
    ].copy()
    data["Value"] = pd.to_numeric(data["Value"], errors="coerce")
    data["Economy_name"] = data["Economy"].map(ECONOMY_NAMES)
    data["Source"] = source_path.name
    data["Source_vintage"] = MODEL_OUTPUT_VINTAGES[economy]
    return data


def load_fuel_mix_assumptions(raw_dir: Path, end_year: int) -> pd.DataFrame:
    """Normalise domestic and international supply-side switching assumptions."""
    workbook = raw_dir / "fuel_mixing_assumptions.xlsx"
    regions = pd.read_excel(workbook, sheet_name="regions")
    international_regions = pd.read_excel(workbook, sheet_name="int_regions")
    domestic = pd.read_excel(workbook, sheet_name="supply_side")
    international = pd.read_excel(workbook, sheet_name="international_supply_side")

    domestic = domestic.merge(regions, on="Region", how="inner")
    domestic["Scope"] = "domestic"
    domestic["Medium"] = "all domestic transport"
    domestic["Drive"] = "all relevant drives"

    international = international.merge(international_regions, on="Region", how="inner")
    international["Scope"] = "international"
    combined = pd.concat([domestic, international], ignore_index=True, sort=False)
    combined = combined.loc[
        combined["Economy"].isin(ECONOMY_NAMES)
        & combined["Date"].between(2021, end_year)
    ].copy()

    tidy = combined.melt(
        id_vars=["Economy", "Date", "Scope", "Medium", "Drive", "Fuel", "New_fuel", "Comment"],
        value_vars=SCENARIOS,
        var_name="Scenario",
        value_name="Value",
    )
    tidy["Value"] = pd.to_numeric(tidy["Value"], errors="coerce")
    tidy["Economy_name"] = tidy["Economy"].map(ECONOMY_NAMES)
    tidy["Source"] = workbook.name
    tidy["Source_vintage"] = FUEL_ASSUMPTION_VINTAGE
    return tidy


def build_reconciliation(drive: pd.DataFrame, fuel: pd.DataFrame) -> pd.DataFrame:
    """Compare drive energy with fuel energy, retaining vintage mismatch evidence."""
    keys = ["Economy", "Date", "Medium", "Transport Type", "Scenario"]
    drive_total = drive.groupby(keys, as_index=False)["Energy"].sum().rename(columns={"Energy": "Drive_energy"})
    fuel_total = fuel.groupby(keys, as_index=False)["Fuel_energy"].sum()
    qa = drive_total.merge(fuel_total, on=keys, how="outer")
    qa["Absolute_gap"] = qa["Fuel_energy"] - qa["Drive_energy"]
    qa["Relative_gap"] = qa["Absolute_gap"].div(qa["Drive_energy"].replace(0, np.nan))
    qa["Same_vintage"] = False
    qa["QA_note"] = "Fuel output predates drive output; gap is diagnostic, not a failed identity check."
    return qa


def add_nested_series(
    destination: dict,
    data: pd.DataFrame,
    measure: str,
    series_column: str,
    value_column: str,
    start_year_by_economy: dict[str, int],
    end_year: int,
) -> None:
    """Store annual values compactly as one array per economy/filter/series."""
    group_columns = ["Economy", "Scenario", "Transport Type", "Medium", series_column]
    for group_values, group in data.groupby(group_columns, dropna=False):
        economy, scenario, transport_type, medium, series = group_values
        start_year = start_year_by_economy[economy]
        years = list(range(start_year, end_year + 1))
        lookup = group.groupby("Date")[value_column].sum().to_dict()
        values = [round(float(lookup.get(year, 0) or 0), 6) for year in years]
        path = destination.setdefault(measure, {}).setdefault(economy, {}).setdefault(scenario, {})
        path = path.setdefault(transport_type, {}).setdefault(medium, {})
        path[str(series)] = values


def build_dashboard_payload(
    drive: pd.DataFrame,
    fuel: pd.DataFrame,
    user_inputs: pd.DataFrame,
    fuel_mix: pd.DataFrame,
    end_year: int,
) -> dict:
    """Create the compact nested object embedded in the interactive dashboard."""
    start_year_by_economy = drive.groupby("Economy")["Date"].min().astype(int).to_dict()
    series: dict = {}

    share_keys = ["Economy", "Date", "Medium", "Transport Type", "Scenario"]
    drive_for_shares = drive.copy()
    drive_for_shares["Drive_share"] = drive_for_shares["Activity"].div(
        drive_for_shares.groupby(share_keys)["Activity"].transform("sum").replace(0, np.nan)
    ).fillna(0)
    fuel_for_shares = fuel.copy()
    fuel_for_shares["Fuel_share"] = fuel_for_shares["Fuel_energy"].div(
        fuel_for_shares.groupby(share_keys)["Fuel_energy"].transform("sum").replace(0, np.nan)
    ).fillna(0)
    total_activity = (
        drive.groupby(share_keys, as_index=False)["Activity"].sum().assign(Series="total activity")
    )

    for measure, value_column in [
        ("activity", "Activity"),
        ("drive_energy", "Energy"),
        ("intensity", "Intensity"),
        ("activity_growth", "Activity_growth"),
        ("intensity_improvement", "Non_road_intensity_improvement"),
    ]:
        add_nested_series(series, drive, measure, "Drive", value_column, start_year_by_economy, end_year)
    add_nested_series(series, drive_for_shares, "drive_share", "Drive", "Drive_share", start_year_by_economy, end_year)
    add_nested_series(series, total_activity, "total_activity", "Series", "Activity", start_year_by_economy, end_year)
    add_nested_series(series, fuel, "fuel_energy", "Fuel", "Fuel_energy", start_year_by_economy, end_year)
    add_nested_series(series, fuel_for_shares, "fuel_share", "Fuel", "Fuel_share", start_year_by_economy, end_year)

    input_inventory = (
        user_inputs.groupby(["Economy", "Measure", "Medium", "Transport Type"], as_index=False)
        .agg(Rows=("Value", "size"), Non_null=("Value", "count"), Min_year=("Date", "min"), Max_year=("Date", "max"))
        .to_dict(orient="records")
    )
    mix_inventory = (
        fuel_mix.groupby(["Economy", "Scope", "Medium", "Fuel", "New_fuel"], as_index=False)
        .agg(Rows=("Value", "size"), Max_share=("Value", "max"), Min_year=("Date", "min"), Max_year=("Date", "max"))
        .to_dict(orient="records")
    )
    return {
        "metadata": {
            "economies": ECONOMY_NAMES,
            "start_years": start_year_by_economy,
            "end_year": end_year,
            "model_output_vintages": MODEL_OUTPUT_VINTAGES,
            "fuel_energy_vintage": ENERGY_OUTPUT_VINTAGE,
            "fuel_assumption_vintage": FUEL_ASSUMPTION_VINTAGE,
        },
        "series": series,
        "input_inventory": input_inventory,
        "fuel_mix_inventory": mix_inventory,
    }


def write_dashboard(template_path: Path, output_path: Path, payload: dict) -> None:
    """Insert compact static data into the dashboard template."""
    template = template_path.read_text(encoding="utf-8")
    if "__NON_ROAD_DASHBOARD_DATA__" not in template:
        raise ValueError("Dashboard template does not contain the data placeholder.")
    compact_data = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(template.replace("__NON_ROAD_DASHBOARD_DATA__", compact_data), encoding="utf-8")


def run_workflow(
    raw_dir: Path,
    template_path: Path,
    dashboard_output_path: Path,
    tabular_output_dir: Path,
    end_year: int,
) -> dict:
    """Run the complete Russia/PRC validation workflow."""
    drive_parts = []
    fuel_parts = []
    user_input_parts = []
    for economy in ECONOMY_NAMES:
        print(f"Loading {economy} drive output...")
        drive_parts.append(load_drive_output(raw_dir=raw_dir, economy=economy, end_year=end_year))
        print(f"Loading {economy} fuel-energy output...")
        fuel_parts.append(load_fuel_energy(raw_dir=raw_dir, economy=economy, end_year=end_year))
        print(f"Loading {economy} user inputs...")
        user_input_parts.append(load_user_inputs(raw_dir=raw_dir, economy=economy, end_year=end_year))

    drive = pd.concat(drive_parts, ignore_index=True)
    fuel = pd.concat(fuel_parts, ignore_index=True)
    user_inputs = pd.concat(user_input_parts, ignore_index=True)
    fuel_mix = load_fuel_mix_assumptions(raw_dir=raw_dir, end_year=end_year)
    qa = build_reconciliation(drive=drive, fuel=fuel)
    payload = build_dashboard_payload(
        drive=drive,
        fuel=fuel,
        user_inputs=user_inputs,
        fuel_mix=fuel_mix,
        end_year=end_year,
    )

    tabular_output_dir.mkdir(parents=True, exist_ok=True)
    drive.to_csv(tabular_output_dir / "non_road_drive_timeseries_russia_prc.csv", index=False)
    fuel.to_csv(tabular_output_dir / "non_road_fuel_energy_russia_prc.csv", index=False)
    user_inputs.to_csv(tabular_output_dir / "non_road_user_inputs_russia_prc.csv", index=False)
    fuel_mix.to_csv(tabular_output_dir / "non_road_fuel_mix_assumptions_russia_prc.csv", index=False)
    qa.to_csv(tabular_output_dir / "non_road_energy_reconciliation_russia_prc.csv", index=False)
    (tabular_output_dir / "dashboard_data_russia_prc.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8"
    )
    write_dashboard(template_path=template_path, output_path=dashboard_output_path, payload=payload)

    summary = {
        "drive_rows": len(drive),
        "fuel_rows": len(fuel),
        "user_input_rows": len(user_inputs),
        "fuel_mix_rows": len(fuel_mix),
        "qa_rows": len(qa),
        "dashboard_bytes": dashboard_output_path.stat().st_size,
    }
    print(json.dumps(summary, indent=2))
    return summary


# --- Frequently changed run settings ---

WORKFLOW_DIR = Path(__file__).resolve().parent
RAW_DIR = WORKFLOW_DIR / "data" / "raw"
TEMPLATE_PATH = WORKFLOW_DIR / "dashboard_template.html"
TABULAR_OUTPUT_DIR = WORKFLOW_DIR.parents[1] / "outputs" / "non_road_assumptions_dashboard"
# Retained only for legacy notebook compatibility. The migrated CLI supplies
# its own generated-output paths.
VISUALIZATION_OUTPUT_PATH = WORKFLOW_DIR / "non-road-assumptions-dashboard.html"
END_YEAR = 2070
RUN_DASHBOARD_WORKFLOW = False


# --- Notebook-style run block ---

if RUN_DASHBOARD_WORKFLOW:
    try:
        WORKFLOW_SUMMARY = run_workflow(
            raw_dir=RAW_DIR,
            template_path=TEMPLATE_PATH,
            dashboard_output_path=VISUALIZATION_OUTPUT_PATH,
            tabular_output_dir=TABULAR_OUTPUT_DIR,
            end_year=END_YEAR,
        )
    except Exception as error:
        print(f"Dashboard workflow failed: {type(error).__name__}: {error}")
        raise

#%%
