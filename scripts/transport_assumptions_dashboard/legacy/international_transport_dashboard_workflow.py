#%%
"""Build the all-economy international transport review dashboard.

The workflow uses the archived 9th-edition international bunker output and
extracts code-backed assumptions that are not obvious from the trajectories.
It is designed for interactive execution from a Jupyter notebook or editor.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from . import non_road_assumptions_workflow as dashboard_base


# --- Stable constants ---

SCENARIOS = ["Reference", "Target"]
MEDIA = ["air", "ship"]
SCOPE = "international"


# --- Data preparation ---

def load_economy_names(concordance_path: Path) -> dict[str, str]:
    """Load the canonical APEC economy names."""
    data = pd.read_csv(concordance_path)
    dashboard_base.require_columns(data, ["Economy", "Economy_name"], concordance_path.name)
    return dict(zip(data["Economy"], data["Economy_name"]))


def discover_domestic_output_vintages(raw_dir: Path, economy_names: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """Read model and final-fuel vintages from the selectively extracted filenames."""
    model_vintages: dict[str, str] = {}
    energy_vintages: dict[str, str] = {}
    for economy in economy_names:
        model_matches = sorted(raw_dir.glob(f"{economy}_NON_ROAD_DETAILED_model_output*.csv"))
        energy_matches = sorted(raw_dir.glob(f"{economy}_*_transport_energy_use.csv"))
        if len(model_matches) != 1 or len(energy_matches) != 1:
            raise FileNotFoundError(f"{economy}: expected one detailed output and one final-fuel output")
        model_date = re.search(r"model_output(\d{8})", model_matches[0].name)
        energy_date = re.search(rf"{re.escape(economy)}_(\d{{8}})_transport", energy_matches[0].name)
        if not model_date or not energy_date:
            raise ValueError(f"Could not parse output vintages for {economy}")
        model_vintages[economy] = pd.to_datetime(model_date.group(1)).strftime("%Y-%m-%d")
        energy_vintages[economy] = pd.to_datetime(energy_date.group(1)).strftime("%Y-%m-%d")
    return model_vintages, energy_vintages


def load_international_output(source_path: Path, economy_names: dict[str, str], end_year: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create drive/activity and final-fuel tables from bunker output."""
    data = pd.read_csv(source_path)
    required = ["Scenario", "Economy", "Date", "Drive", "Fuel", "Medium", "Energy", "Activity"]
    dashboard_base.require_columns(data, required, source_path.name)
    data = data.loc[
        data["Scenario"].isin(SCENARIOS)
        & data["Medium"].isin(MEDIA)
        & data["Date"].le(end_year)
    ].copy()
    data["Energy"] = pd.to_numeric(data["Energy"], errors="coerce").fillna(0)
    data["Activity"] = pd.to_numeric(data["Activity"], errors="coerce").fillna(0)

    drive_keys = ["Economy", "Date", "Medium", "Drive", "Scenario"]
    # Post-hoc fuel allocation divides both energy and activity over output fuels.
    drive = data.groupby(drive_keys, as_index=False)[["Activity", "Energy"]].sum()
    drive["Intensity"] = drive["Energy"].div(drive["Activity"].replace(0, np.nan)).fillna(0)
    drive = drive.sort_values(["Economy", "Scenario", "Medium", "Drive", "Date"])
    drive["Activity_growth"] = (
        drive.groupby(["Economy", "Scenario", "Medium", "Drive"])["Activity"]
        .pct_change(fill_method=None)
        .replace([np.inf, -np.inf], np.nan)
        .fillna(0)
    )
    previous_intensity = drive.groupby(["Economy", "Scenario", "Medium", "Drive"])["Intensity"].shift(1)
    improvement = previous_intensity.sub(drive["Intensity"]).div(previous_intensity.replace(0, np.nan)).fillna(0)
    drive["Intensity_improvement_factor"] = 1 + improvement
    drive["Transport Type"] = SCOPE
    drive["Economy_name"] = drive["Economy"].map(economy_names)
    drive["Source"] = source_path.name

    fuel = data.groupby(["Economy", "Date", "Medium", "Fuel", "Scenario"], as_index=False)["Energy"].sum()
    fuel = fuel.rename(columns={"Energy": "Fuel_energy"})
    fuel["Transport Type"] = SCOPE
    fuel["Economy_name"] = fuel["Economy"].map(economy_names)
    fuel["Source"] = source_path.name
    return drive, fuel


def build_exception_registry(
    parameters_path: Path,
    non_road_code_path: Path,
    international_code_path: Path,
    model_vintages: dict[str, str],
    energy_vintages: dict[str, str],
) -> pd.DataFrame:
    """Build a concise registry of code-backed, interpretation-relevant rules."""
    parameters = yaml.safe_load(parameters_path.read_text(encoding="utf-8"))
    rows: list[dict] = []

    def add(
        scope: str,
        economy: str,
        title: str,
        category: str,
        scenario: str,
        medium: str,
        start_year: int | str,
        end_year: int | str,
        explanation: str,
        result_effect: str,
        source_reference: str,
        confidence: str = "Confirmed in code/config",
        review_status: str = "Needs model-owner review",
    ) -> None:
        rows.append({
            "Scope": scope,
            "Economy": economy,
            "Title": title,
            "Category": category,
            "Scenario": scenario,
            "Medium": medium,
            "Start_year": start_year,
            "End_year": end_year,
            "Explanation": explanation,
            "Result_effect": result_effect,
            "Source_reference": source_reference,
            "Confidence": confidence,
            "Review_status": review_status,
        })

    manual_growth = parameters.get("MANUAL_ACTIVITY_GROWTH_SETTINGS_NON_ROAD_ALL_YEARS", {}).get("non_road", {})
    for economy, media in manual_growth.items():
        for medium, factor in media.items():
            add(
                "domestic non-road", economy, "Manual activity growth override", "Activity",
                "both", medium, 2022, 2070,
                f"The activity-growth factor is replaced with {factor} for every model year, scenario, transport type and drive in this medium.",
                "A factor of 1.0 holds activity constant after the initial model-year value and bypasses the usual growth forecast.",
                f"{parameters_path.name}: MANUAL_ACTIVITY_GROWTH_SETTINGS_NON_ROAD_ALL_YEARS; {non_road_code_path.name}: apply_manual_adjustments_to_activity_growth_for_non_road",
            )

    for economy in sorted(model_vintages):
        if model_vintages[economy] != energy_vintages[economy]:
            add(
                "domestic non-road", economy, "Drive and fuel output vintages differ", "Source vintage",
                "both", "all", 2022, 2070,
                f"Detailed drive results use {model_vintages[economy]}, while final fuel-energy results use {energy_vintages[economy]}.",
                "Fuel totals and drive totals may not reconcile because they are not from the same run.",
                "Selectively extracted archived model-output filenames",
                confidence="Confirmed from source filenames",
            )

    intended_non_road = parameters.get("TURNOVER_RATE_MIDPOINT_MULT_ADJUSTMENT_NON_ROAD_TARGET", {})
    applied_road = parameters.get("TURNOVER_RATE_MIDPOINT_MULT_ADJUSTMENT_ROAD_TARGET", {})
    for economy in sorted(set(intended_non_road) | set(applied_road)):
        intended = intended_non_road.get(economy, 1)
        applied = applied_road.get(economy, 1)
        if intended == applied:
            continue
        add(
            "domestic non-road", economy, "Target turnover uses the road-model parameter", "Technical implementation",
            "Target", "all", 2022, 2070,
            f"The non-road loader reads TURNOVER_RATE_MIDPOINT_MULT_ADJUSTMENT_ROAD_TARGET. The resulting multiplier is {applied}, while the non-road target setting is {intended}.",
            "The target-scenario pace of non-road stock turnover can differ from the value documented in the non-road configuration.",
            f"{non_road_code_path.name}: load_non_road_model_data; {parameters_path.name}: TURNOVER_RATE_MIDPOINT_MULT_ADJUSTMENT_*_TARGET",
            confidence="Confirmed implementation mismatch",
        )

    add(
        "international", "all", "International intensity is shared across economies", "Intensity",
        "both", "air and ship", 2022, 2070,
        "International bunker intensity is derived from domestic non-road outputs, then averaged across economy and transport type for each scenario, year and drive.",
        "Economies differ in bunker energy and activity, but not in the drive-level intensity trajectory used by the international model.",
        f"{international_code_path.name}: extract_non_road_modelled_data",
    )
    add(
        "international", "all", "Early growth is replaced with a later-period average", "Activity",
        "both", "air and ship", 2022, 2025,
        "Growth through 2025 is overwritten with each economy/medium average growth for 2026–2036 to remove the modelled COVID-period effect.",
        "The early projection is a smoothed assumption rather than a direct continuation of observed activity.",
        f"{international_code_path.name}: calculate_non_road_activity_growth_rate",
    )
    add(
        "international", "all", "Marine growth reduction is applied to both scenarios", "Activity",
        "both", "ship", 2025, 2070,
        "Configuration describes a Target-only reduction reaching 30% by 2070, but the implementation applies the multiplying reduction to every ship row without filtering scenario.",
        "Reference and Target international marine growth are both reduced progressively, contrary to the surrounding code comment.",
        f"{international_code_path.name}: calculate_non_road_activity_growth_rate; {parameters_path.name}: INTERNATIONAL_MARINE_GROWTH_MAX_ADJUSTMENT_BY_2070_TGT",
        confidence="Confirmed implementation mismatch",
    )
    add(
        "international", "all", "Fuel-switching paths are common to every economy", "Fuel switching",
        "both", "air and ship", 2022, 2070,
        "All 21 economies map to the single 'all' international fuel-mixing region.",
        "Biofuel and alternative-fuel mixing assumptions do not vary by economy, although base-year fuel quantities still do.",
        "fuel_mixing_assumptions.xlsx: int_regions and international_supply_side",
        confidence="Confirmed in input workbook",
    )

    extra_activity = parameters.get("EXTRA_PROPORTIONAL_INCREASES_IN_BUNKERS_ACTIVITY", {}).get("bunkers", {})
    for economy, years in extra_activity.items():
        grouped_increases: dict[tuple[str, float], list[int]] = {}
        for year_text, media in years.items():
            for medium, increase in media.items():
                grouped_increases.setdefault((medium, float(increase)), []).append(int(year_text))
        for (medium, increase), active_years in grouped_increases.items():
            active_years = sorted(active_years)
            add(
                "international", economy, "Additional international activity growth", "Activity",
                "both", medium, active_years[0], active_years[-1],
                f"An additional {increase:.1%} proportional activity increase is applied in every year from {active_years[0]} through {active_years[-1]}.",
                "Activity is raised above the standard international growth projection for this economy and medium throughout this period.",
                f"{parameters_path.name}: EXTRA_PROPORTIONAL_INCREASES_IN_BUNKERS_ACTIVITY",
            )

    for medium in ["AIR", "SHIP"]:
        decreases = parameters[f"INTERNATIONAL_TRANSPORT_EXPECTED_ENERGY_DECREASE_FROM_COVID_{medium}"]
        years_to_recover = parameters[f"INTERNATIONAL_TRANSPORT_EXPECTED_YEARS_TO_RETURN_TO_NORMAL_ACTIVITY_FROM_COVID_{medium}"]
        return_fraction = parameters[f"INTERNATIONAL_TRANSPORT_EXPECTED_RETURN_TO_NORMAL_ACTIVITY_FROM_COVID_{medium}"]
        listed_years = parameters[f"INTERNATIONAL_TRANSPORT_LISTED_YEARS_WHEN_COVID_EFFECTS_APPLIED_{medium}"]
        for economy, decrease in decreases.items():
            recovery_years = years_to_recover[economy]
            fraction = return_fraction[economy]
            if decrease == 0:
                continue
            final_covid_year = max(listed_years[economy])
            add(
                "international", economy, f"International {medium.lower()} COVID recovery adjustment", "COVID recovery",
                "both", medium.lower(), final_covid_year + 1, final_covid_year + recovery_years,
                f"The model assumes a {decrease:.1%} COVID-related energy decrease and restores {fraction:.0%} of the implied gap over {recovery_years} year(s) after {final_covid_year}.",
                "The near-term international activity path is recalculated before the normal growth assumption resumes.",
                f"{parameters_path.name}: INTERNATIONAL_TRANSPORT_*_COVID_{medium}",
            )

    registry = pd.DataFrame(rows)
    registry.insert(0, "Exception_id", [f"RULE-{number:04d}" for number in range(1, len(registry) + 1)])
    return registry


def registry_to_dashboard_notes(registry: pd.DataFrame) -> dict[str, list[dict[str, str]]]:
    """Convert international registry rows to compact dashboard disclosures."""
    notes: dict[str, list[dict[str, str]]] = {"_global": []}
    international = registry.loc[registry["Scope"].eq("international")]
    for row in international.itertuples(index=False):
        key = "_global" if row.Economy == "all" else row.Economy
        title = row.Title
        explanation = row.Explanation
        effect = row.Result_effect
        if row.Title == "International intensity is shared across economies":
            title = "The same efficiency pathway is used for every economy"
            explanation = "There is no separate international transport efficiency forecast for each economy. The model uses an average calculated from domestic aviation and shipping results."
            effect = "Economy results can have different activity and fuel use, but their assumed efficiency improvement follows the same pathway."
        elif row.Title == "Early growth is replaced with a later-period average":
            title = "Near-term growth is smoothed"
            explanation = "Growth through 2025 is replaced with the average growth expected from 2026 to 2036. This avoids carrying the unusual COVID-period pattern into the forecast."
            effect = "The first few projected years should be read as a smoothing assumption, not a direct continuation of recent observations."
        elif row.Title == "Marine growth reduction is applied to both scenarios":
            title = "International shipping’s annual growth rate is gradually scaled down"
            explanation = "The current implementation reduces the annual shipping growth rate by 30% in 2067 and 32% in 2070. Although configured and described as a Target assumption, it is currently applied to both Reference and Target."
            effect = "When the underlying growth rate is positive, long-term shipping activity is lower in both scenarios than it would otherwise be. If the underlying rate is negative, the scaling makes the decline smaller."
        elif row.Title == "Fuel-switching paths are common to every economy":
            title = "Every economy uses the same clean-fuel switching schedule"
            explanation = "The shares of biofuels and other alternative fuels are based on one common international schedule rather than separate economy assumptions."
            effect = "Differences between economies mainly come from their starting fuel use and activity, not from different future fuel-switching ambitions."
        elif row.Title == "Additional international activity growth":
            title = "Extra shipping growth is added"
            explanation = row.Explanation.replace("proportional activity increase", "activity growth")
            effect = "This economy grows faster than the standard international shipping projection during the stated period."
        elif "COVID recovery adjustment" in row.Title:
            title = "Aviation recovery after COVID" if row.Medium == "air" else "Shipping recovery after COVID"
            explanation = row.Explanation.replace("The model assumes", "The forecast assumes").replace("implied gap", "estimated shortfall")
            effect = "This creates a temporary recovery increase before the normal long-term growth pathway resumes."
        notes.setdefault(key, []).append({
            "title": title,
            "explanation": explanation,
            "effect": effect,
            "source": row.Source_reference,
        })
    return notes


def build_payload(
    drive: pd.DataFrame,
    fuel: pd.DataFrame,
    economy_names: dict[str, str],
    registry: pd.DataFrame,
    end_year: int,
) -> dict:
    """Build the nested payload used by the standalone dashboard."""
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
        ("intensity_improvement", "Intensity_improvement_factor"),
    ]:
        dashboard_base.add_nested_series(series, drive, measure, "Drive", value_column, start_years, end_year)
    dashboard_base.add_nested_series(series, drive_share, "drive_share", "Drive", "Drive_share", start_years, end_year)
    dashboard_base.add_nested_series(series, total_activity, "total_activity", "Series", "Activity", start_years, end_year)
    dashboard_base.add_nested_series(series, fuel, "fuel_energy", "Fuel", "Fuel_energy", start_years, end_year)
    dashboard_base.add_nested_series(series, fuel_share, "fuel_share", "Fuel", "Fuel_share", start_years, end_year)

    return {
        "metadata": {
            "economies": economy_names,
            "start_years": start_years,
            "end_year": end_year,
            "model_output_vintage": "2025-04-21 (post-hoc fuel allocations)",
            "exceptions": registry_to_dashboard_notes(registry),
        },
        "series": series,
    }


# --- Workflow ---

def run_international_dashboard_workflow(
    source_path: Path,
    concordance_path: Path,
    parameters_path: Path,
    non_road_code_path: Path,
    international_code_path: Path,
    domestic_raw_dir: Path,
    template_path: Path,
    fragment_path: Path,
    output_dir: Path,
    end_year: int,
) -> dict:
    """Build review tables, useful exception registry and dashboard fragment."""
    economy_names = load_economy_names(concordance_path)
    dashboard_base.ECONOMY_NAMES = economy_names
    drive, fuel = load_international_output(source_path, economy_names, end_year)

    model_vintages, energy_vintages = discover_domestic_output_vintages(domestic_raw_dir, economy_names)
    registry = build_exception_registry(
        parameters_path=parameters_path,
        non_road_code_path=non_road_code_path,
        international_code_path=international_code_path,
        model_vintages=model_vintages,
        energy_vintages=energy_vintages,
    )
    payload = build_payload(drive, fuel, economy_names, registry, end_year)

    output_dir.mkdir(parents=True, exist_ok=True)
    combined = drive.merge(
        fuel.groupby(["Economy", "Date", "Medium", "Scenario", "Transport Type"], as_index=False)["Fuel_energy"].sum(),
        on=["Economy", "Date", "Medium", "Scenario", "Transport Type"],
        how="left",
        suffixes=("", "_all_fuels"),
    )
    drive.to_csv(output_dir / "international_transport_drive_timeseries_all_economies.csv", index=False)
    fuel.to_csv(output_dir / "international_transport_fuel_energy_all_economies.csv", index=False)
    combined.to_csv(output_dir / "international_transport_review_timeseries_all_economies.csv", index=False)
    registry.to_csv(output_dir / "useful_model_assumptions_and_exceptions_registry.csv", index=False)
    (output_dir / "international_transport_dashboard_data.json").write_text(
        json.dumps(payload, ensure_ascii=True), encoding="utf-8"
    )
    dashboard_base.write_dashboard(template_path, fragment_path, payload)

    summary = {
        "economies": len(economy_names),
        "drive_rows": len(drive),
        "fuel_rows": len(fuel),
        "registry_rows": len(registry),
        "fragment_bytes": fragment_path.stat().st_size,
    }
    print(json.dumps(summary, indent=2))
    return summary


# --- Frequently changed run settings ---

WORKFLOW_DIR = Path(__file__).resolve().parent
CODE_ROOT = WORKFLOW_DIR.parent / "transport_model_9th_edition_code" / "transport_model_9th_edition"
# The migrated CLI requires an explicit --international-source path.
SOURCE_PATH = Path("international_bunker_outputs.csv")
CONCORDANCE_PATH = CODE_ROOT / "config" / "concordances_and_config_data" / "economy_code_to_name.csv"
PARAMETERS_PATH = CODE_ROOT / "config" / "parameters.yml"
NON_ROAD_CODE_PATH = CODE_ROOT / "model_code" / "calculation_functions" / "run_non_road_model.py"
INTERNATIONAL_CODE_PATH = CODE_ROOT / "model_code" / "calculation_functions" / "international_bunkers.py"
DOMESTIC_RAW_DIR = WORKFLOW_DIR / "data" / "raw_all"
TEMPLATE_PATH = WORKFLOW_DIR / "international_transport_dashboard_template.html"
FRAGMENT_PATH = WORKFLOW_DIR / "international_transport_dashboard_fragment.html"
OUTPUT_DIR = WORKFLOW_DIR.parents[1] / "outputs" / "international_transport_assumptions_dashboard"
END_YEAR = 2070
# The original notebook executed on import.  The migrated entry point invokes
# ``run_international_dashboard_workflow`` explicitly after checking paths.
RUN_INTERNATIONAL_DASHBOARD_WORKFLOW = False


# --- Notebook-style run block ---

if RUN_INTERNATIONAL_DASHBOARD_WORKFLOW:
    try:
        INTERNATIONAL_DASHBOARD_SUMMARY = run_international_dashboard_workflow(
            source_path=SOURCE_PATH,
            concordance_path=CONCORDANCE_PATH,
            parameters_path=PARAMETERS_PATH,
            non_road_code_path=NON_ROAD_CODE_PATH,
            international_code_path=INTERNATIONAL_CODE_PATH,
            domestic_raw_dir=DOMESTIC_RAW_DIR,
            template_path=TEMPLATE_PATH,
            fragment_path=FRAGMENT_PATH,
            output_dir=OUTPUT_DIR,
            end_year=END_YEAR,
        )
    except Exception as error:
        print(f"International dashboard workflow failed: {error}")
        raise

#%%
