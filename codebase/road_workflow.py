#%%
"""
Single-entry road model workflow orchestrator.

This provides a thin, config-driven entrypoint similar in spirit to
leap_transport/codebase/transport_workflow.py:

- keep run settings in one place
- delegate heavy logic to module functions
- run Modules 2–6 sequentially
- emit diagnostics/chart suites from each module (when enabled)
- optionally save intermediate outputs to CSV

Module 1 defaults are loaded at the start of run_with_config() via
load_module1_for_economy(). Pre-generate them with scripts/generate_module1_defaults.py.
The live Module 1 merge/processing function (run_module1) is not called here;
road_workflow.py consumes pre-generated Module 1 output packages, not raw researcher inputs.

Module 7 mirror is implemented in module7_mirror.py but must be called
separately after run_module6(); pass its T6 and T9/T10 outputs directly.

Input format:
- Module 1 packages may use the canonical long CSV contract
  (Economy, Scenario, Branch Path, Variable, Year, Value, Units, metadata) or
  the legacy LEAP workbook format.
- The adapter normalises either package shape before Modules 2-7 run.
- parse_leap_format_inputs() still consumes the internal LEAP-style shape after
  adapter normalisation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import os
import re
import shutil
import time
import json
import traceback
from typing import Any

import numpy as np
import pandas as pd
import yaml

from modules.module2_base_year import run_module2
from modules.module3_stock_targets import run_module3
from modules.module4_sales_turnover import run_module4
from modules.module5_sales_shares import run_module5
from modules.module6_reconciliation_and_leap_handoff import run_module6
from modules.module7_mirror import build_base_technology_assumptions, run_module7_mirror
from logging_utils import StructuredLogger, log_dataframe_info
from adapters.road_module1_defaults import load_module1_for_economy
from adapters.module1_reimport_exporter import (
    load_module1_source_long_csv,
    write_reconciled_module1_reimport_csv,
)
from adapters.leap_workbook import write_leap_import_workbook
from adapters.lifecycle_profile_exporter import export_lifecycle_profiles_from_t6v

# Canonical LEAP region name(s) per economy code.
# One-to-one mapping from economy code to canonical LEAP region name.
# Keys use the road model's underscored code format (e.g. "01_AUS").
ECONOMY_CODE_TO_LEAP_REGION_NAMES: dict[str, str] = {
    "01_AUS": "Australia",
    "02_BD":  "Brunei Darussalam",
    "03_CDA": "Canada",
    "04_CHL": "Chile",
    "05_PRC": "China",
    "06_HKC": "Hong Kong, China",
    "07_INA": "Indonesia",
    "08_JPN": "Japan",
    "09_ROK": "Republic of Korea",
    "10_MAS": "Malaysia",
    "11_MEX": "Mexico",
    "12_NZ":  "New Zealand",
    "13_PNG": "Papua New Guinea",
    "14_PE":  "Peru",
    "15_PHL": "The Philippines",
    "16_RUS": "Russia",
    "17_SGP": "Singapore",
    "18_CT":  "Chinese Taipei",
    "19_THA": "Thailand",
    "20_USA": "United States",
    "21_VN":  "Viet Nam",
}
from diagnostics.module_charts import write_module1_charts, write_module6_charts, write_workflow_summary_charts
from diagnostics.plotly_dashboard import write_module_pages
from adapters.leap_import_writer import write_leap_import_workbook as write_strict_leap_import_workbook


_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_WORKFLOW_CONFIG_PATH = _REPO_ROOT / "codebase" / "config" / "workflow_defaults.yaml"


def load_workflow_defaults(config_path: str | Path | None = None) -> dict[str, Any]:
    """
    Load runtime workflow defaults from YAML.

    This controls run switches and paths only. Model assumptions still come from
    Module 1 packages and module-specific configuration files.
    """
    path = Path(config_path) if config_path is not None else _DEFAULT_WORKFLOW_CONFIG_PATH
    if not path.is_absolute():
        path = _REPO_ROOT / path
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Workflow defaults must be a YAML mapping: {path}")
    return data


def _workflow_defaults_to_config_overrides(defaults: dict[str, Any]) -> dict[str, Any]:
    """Map workflow_defaults.yaml keys to RoadWorkflowConfig fields."""
    run_modules = defaults.get("run_modules") or {}
    module6 = defaults.get("module6") or {}
    leap_import = defaults.get("leap_import") or {}
    overrides: dict[str, Any] = {}

    for key in [
        "module1_defaults_dir",
        "module1_defaults_version",
        "enable_visualisations",
        "save_csv_outputs",
        "show_progress",
        "write_leap_row_diagnostics",
    ]:
        if key in defaults:
            overrides[key] = defaults[key]

    for module_num in range(2, 8):
        key = f"m{module_num}"
        if key in run_modules:
            overrides[f"run_m{module_num}"] = bool(run_modules[key])

    if "match_tolerance" in module6:
        overrides["module6_match_tolerance"] = float(module6["match_tolerance"])
    if "adjust_stock_targets_after_reconciliation" in module6:
        overrides["adjust_stock_targets_after_reconciliation"] = bool(
            module6["adjust_stock_targets_after_reconciliation"]
        )
    if "export_values_in_raw_units" in leap_import:
        overrides["leap_import_export_values_in_raw_units"] = bool(leap_import["export_values_in_raw_units"])

    return overrides


def _workflow_defaults_value(defaults: dict[str, Any], key: str, fallback: Any) -> Any:
    value = defaults.get(key, fallback)
    return fallback if value is None else value


def _resolve_repo_relative_path(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    path = Path(value)
    return path if path.is_absolute() else _REPO_ROOT / path


#%%
# ============================================================
# Settings — edit here and run the cells below
# ============================================================

ECONOMY  = "20_USA"   # economy code, e.g. "12_NZ", "01_AUS", "20_USA"
SCENARIO = "Target"
ENABLE_VIS = True    # True → write PNG/HTML diagnostic charts


# ---------------------------------------------------------------------------
# LEAP format input parsing
# ---------------------------------------------------------------------------


def _parse_branch_path(branch_path: str) -> dict[str, str | None] | None:
    """
    Parse a LEAP branch path into road model dimension components.

    Expected format: Demand\\{transport road}\\{vehicle type}\\{drive[ size]}[\\{fuel}]

    Returns a dict with keys transport_type, vehicle_type, drive_type, size, fuel,
    or None if the path cannot be parsed as a road branch.
    """
    parts = [p.strip() for p in str(branch_path or "").split("\\")]
    if len(parts) < 3 or parts[0].lower() != "demand":
        return None
    transport_label = parts[1].lower()
    if "passenger" in transport_label:
        transport_type = "passenger"
    elif "freight" in transport_label:
        transport_type = "freight"
    else:
        return None
    vehicle_type = parts[2]
    # 3-level paths (Demand\Transport\VehicleType) carry vehicle-type-level data
    # (e.g. aggregate mileage for Motorcycles, Buses, LCVs). No drive_type or fuel.
    if len(parts) == 3:
        return {
            "transport_type": transport_type,
            "vehicle_type": vehicle_type,
            "drive_type": None,
            "size": None,
            "fuel": None,
        }
    tech_parts = parts[3].split()
    drive_type = tech_parts[0]
    size: str | None = " ".join(tech_parts[1:]) or None
    fuel: str | None = parts[4] if len(parts) > 4 else None
    return {
        "transport_type": transport_type,
        "vehicle_type": vehicle_type,
        "drive_type": drive_type,
        "size": size,
        "fuel": fuel,
    }


def parse_leap_format_inputs(
    df: pd.DataFrame,
    base_year: int | None = None,
    region_to_economy: dict[str, str] | None = None,
    source_flag: str = "provided",
) -> pd.DataFrame:
    """
    Convert a LEAP-format input table into a DataFrame suitable for Module 2.

    This accepts the format produced by road_model_inputs_interface (and the LEAP
    import/export workbook format more generally).

    Required columns:
        Branch Path  — backslash-separated LEAP branch path
        Variable     — LEAP variable name (Stock, Mileage, Fuel Economy, etc.)
        Scenario     — scenario label
        Region       — economy name or code
        <year>       — one or more integer year columns, e.g. 2022 or "2022";
                       columns can appear in any order

    Optional columns (used when present, ignored otherwise):
        Scale        — LEAP scale prefix (Thousand / Million / Billion / blank)
        Units        — unit string; used to convert MJ/100 km → km/GJ automatically

    All other columns (input_source, notes, default_version, etc.) are silently ignored.

    Args:
        df: DataFrame in LEAP workbook column format.
        base_year: If set, only rows for this year are returned. If None, all
            year columns are returned as separate rows.
        region_to_economy: Optional mapping from Region strings (e.g. "Australia")
            to economy codes (e.g. "01AUS"). When omitted, Region is used as-is.
        source_flag: Source flag assigned to every output row (default "provided").

    Returns:
        DataFrame with columns:
            economy, scenario, year, transport_type, vehicle_type, drive_type,
            size (if any path has a size qualifier), fuel (if any path has a fuel level),
            variable, value, unit, source_flag
    """
    variable_map = {
        "Stock": "stock",
        "Mileage": "mileage",
        "Average Mileage": "mileage",
        "Fuel Economy": "efficiency",
        "Final On-Road Fuel Economy": "efficiency",
        "Sales Share": "sales_share",
        "Stock Share": "stock_share",
        "Device Share": "device_share",
    }
    scale_multipliers = {
        "": 1.0,
        "%": 1.0,
        "thousand": 1_000.0,
        "thousands": 1_000.0,
        "million": 1_000_000.0,
        "millions": 1_000_000.0,
        "billion": 1_000_000_000.0,
        "billions": 1_000_000_000.0,
    }

    df = df.copy()

    # Detect year columns — any column whose name casts cleanly to int
    year_cols: list[tuple[int, str]] = []
    for col in df.columns:
        try:
            year_cols.append((int(col), str(col)))
        except (ValueError, TypeError):
            pass
    year_cols.sort()
    if not year_cols:
        raise ValueError(
            "parse_leap_format_inputs: no year columns found. "
            "Expected integer column names such as 2022 or '2022'."
        )

    year_col_names = [name for _, name in year_cols]

    # Keep only id/metadata columns that are actually present.
    # Source metadata is useful for diagnostics, and downstream modules ignore
    # columns they do not need.
    metadata_cols = [
        "input_source",
        "source_type",
        "source_name",
        "source_scope",
        "default_version",
        "researcher_review_recommended",
        "review_reason",
    ]
    id_cols = [
        c for c in [
            "Branch Path", "Variable", "Scenario", "Region", "Scale", "Units",
            *metadata_cols,
        ]
        if c in df.columns
    ]

    melted = df.melt(
        id_vars=id_cols,
        value_vars=year_col_names,
        var_name="_year",
        value_name="value",
    )
    melted["year"] = pd.to_numeric(melted["_year"], errors="coerce")
    melted = melted.drop(columns=["_year"])
    melted["value"] = pd.to_numeric(melted["value"], errors="coerce")
    melted = melted.dropna(subset=["value", "year"])
    melted["year"] = melted["year"].astype(int)

    if base_year is not None:
        melted = melted[melted["year"] == base_year]

    # Map Variable → internal variable name; drop unrecognised rows
    melted["variable"] = melted["Variable"].map(variable_map)
    melted = melted.dropna(subset=["variable"])

    # Parse Branch Path into road model dimensions
    parsed = melted["Branch Path"].map(_parse_branch_path)
    for key in ["transport_type", "vehicle_type", "drive_type", "size", "fuel"]:
        melted[key] = [row[key] if row is not None else None for row in parsed]
    melted = melted.dropna(subset=["transport_type", "vehicle_type"])

    # Apply LEAP Scale multiplier when the column is present
    if "Scale" in melted.columns:
        melted["value"] = melted["value"] * melted["Scale"].map(
            lambda s: scale_multipliers.get(str(s).strip().lower(), 1.0) if pd.notna(s) else 1.0
        )

    # Unit conversion: efficiency in MJ/100 km → km/GJ
    # km/GJ = 10_000 / (MJ/100 km)
    if "Units" in melted.columns:
        eff_mask = (melted["variable"] == "efficiency") & (
            melted["Units"].str.strip().str.lower().isin(["mj/100 km", "mj/100km"])
        )
        nonzero = eff_mask & (melted["value"] != 0)
        melted.loc[nonzero, "value"] = 10_000.0 / melted.loc[nonzero, "value"]
        melted.loc[eff_mask, "Units"] = "km/GJ"

    # Economy: apply optional name→code mapping, fall back to Region as-is
    region_col = melted["Region"] if "Region" in melted.columns else pd.Series("", index=melted.index)
    if region_to_economy:
        melted["economy"] = region_col.map(region_to_economy).fillna(region_col)
    else:
        melted["economy"] = region_col

    melted["scenario"] = melted["Scenario"] if "Scenario" in melted.columns else "Reference"
    melted["unit"] = melted["Units"] if "Units" in melted.columns else ""
    melted["source_flag"] = source_flag

    keep = [
        "economy", "scenario", "year",
        "transport_type", "vehicle_type", "drive_type", "size", "fuel",
        "variable", "value", "unit", "source_flag",
    ]
    keep.extend([c for c in metadata_cols if c in melted.columns])
    # Only include size / fuel columns if at least one row has a non-null value
    if melted.get("size") is None or melted["size"].isna().all():
        keep = [c for c in keep if c != "size"]
    if melted.get("fuel") is None or melted["fuel"].isna().all():
        keep = [c for c in keep if c != "fuel"]

    return melted[[c for c in keep if c in melted.columns]].reset_index(drop=True)


def _read_base_stocks_for_shares(base_year_branches: pd.DataFrame, base_year: int) -> dict[str, float]:
    if base_year_branches is None or base_year_branches.empty or "stock" not in base_year_branches.columns:
        return {}
    df = base_year_branches.copy()
    if "base_year" in df.columns:
        df = df[df["base_year"] == base_year]
    branch_keys = [c for c in ["transport_type", "vehicle_type", "size", "drive_type"] if c in df.columns]
    if branch_keys:
        df = df.drop_duplicates(subset=branch_keys)
    return df.groupby("vehicle_type")["stock"].sum().to_dict()


def _interpolate_vehicle_type_stock_shares(
    module1_stock_shares: dict[str, pd.Series] | None,
    base_stocks: dict[str, float],
    years: list[int],
) -> dict[str, pd.Series] | None:
    """Build annual physical vehicle-type stock shares from base stocks and sparse Module 1 Stock Share rows."""
    if not years:
        return None
    base_year = years[0]
    module1_stock_shares = module1_stock_shares or {}
    vehicle_types = ["LPVs", "Motorcycles", "Buses", "Trucks", "LCVs"]
    result: dict[str, pd.Series] = {}

    group_members = {
        "passenger": ["LPVs", "Motorcycles", "Buses"],
        "freight": ["Trucks", "LCVs"],
    }
    base_share_by_type: dict[str, float] = {}
    for members in group_members.values():
        total = sum(float(base_stocks.get(vt, 0.0)) for vt in members)
        for vt in members:
            base_share_by_type[vt] = (float(base_stocks.get(vt, 0.0)) / total) if total > 0 else 0.0

    for vt in vehicle_types:
        points = {base_year: base_share_by_type.get(vt, 0.0)}
        if vt in module1_stock_shares:
            for year, value in module1_stock_shares[vt].dropna().items():
                points[int(year)] = float(value)
        point_series = pd.Series(points).sort_index()
        annual = point_series.reindex(years).interpolate(method="index").ffill().bfill()
        if not point_series.empty:
            last_target_year = int(point_series.index.max())
            annual.loc[annual.index > last_target_year] = float(point_series.loc[last_target_year])
        result[vt] = annual

    for members in group_members.values():
        totals = sum(result[vt] for vt in members)
        for vt in members:
            result[vt] = result[vt].where(totals == 0, result[vt] / totals)
    return result


def _convert_passenger_physical_to_capacity_shares(
    physical_shares: dict[str, pd.Series] | None,
    weights: dict[str, float] | None,
) -> dict[str, pd.Series] | None:
    if physical_shares is None:
        return None
    weights = weights or {"LPVs": 1.0, "Motorcycles": 0.8, "Buses": 20.0}
    result = dict(physical_shares)
    passenger_types = ["LPVs", "Motorcycles", "Buses"]
    weighted = {
        vt: physical_shares[vt] * float(weights.get(vt, 1.0))
        for vt in passenger_types
        if vt in physical_shares
    }
    if weighted:
        total = sum(weighted.values())
        for vt, series in weighted.items():
            result[vt] = series.where(total == 0, series / total)
    return result


# ---------------------------------------------------------------------------
# Configuration / inputs
# ---------------------------------------------------------------------------


@dataclass
class RoadWorkflowConfig:
    """Runtime settings for the orchestrator."""

    # Scope
    economy: str
    scenarios: list[str] = field(default_factory=lambda: ["Target"])

    # Time
    base_year: int = 2022
    final_year: int = 2060

    # Paths (default to env vars, fallback to local dev paths)
    config_dir: str | Path = field(default_factory=lambda: os.getenv("ROAD_MODEL_CONFIG_DIR", "config"))
    diagnostics_root: str | Path | None = field(default_factory=lambda: os.getenv("ROAD_MODEL_DIAGNOSTICS_ROOT", "plotting_output/module_diagnostics"))
    output_root: str | Path = field(default_factory=lambda: os.getenv("ROAD_MODEL_OUTPUT_ROOT", "results/road_workflow"))

    # Module 1 — mandatory input source.
    # Points to the directory containing versioned per-economy default CSVs generated
    # by scripts/generate_module1_defaults.py (or the road_model_inputs_interface website).
    # All base-year assumptions (stock, mileage, efficiency, survival curves, PHEV rate,
    # reconciliation bounds, vehicle equivalent weights) are sourced from here.
    module1_defaults_dir: str | Path = field(
        default_factory=lambda: os.getenv("ROAD_MODEL_MODULE1_DIR", "input_data/module1_defaults")
    )
    module1_defaults_version: str | None = None  # None = most recently modified version folder

    # Module flags
    run_m2: bool = True
    run_m3: bool = True
    run_m4: bool = True
    run_m5: bool = True
    run_m6: bool = True
    run_m7: bool = True

    # Visualisation / diagnostics switch.
    # When False, no matplotlib QA figures are generated even if diagnostics_root is set.
    enable_visualisations: bool = True

    # Output behavior
    save_csv_outputs: bool = True
    show_progress: bool = True
    write_leap_row_diagnostics: bool = field(
        default_factory=lambda: os.getenv("ROAD_MODEL_WRITE_LEAP_ROW_DIAGNOSTICS", "").lower() in {"1", "true", "yes", "on"}
    )

    # Optional module settings
    leap_workbook_path: str | Path | None = None
    leap_reference_path: str | Path | None = None
    module3_config: dict[str, Any] | None = None
    module4_config: dict[str, Any] | None = None
    module6_match_tolerance: float = 0.01
    adjust_stock_targets_after_reconciliation: bool = True
    leap_import_export_values_in_raw_units: bool = False

    def projection_years(self) -> list[int]:
        return list(range(self.base_year, self.final_year + 1))


@dataclass
class RoadWorkflowInputs:
    """External data inputs needed by modules 2–6 that are NOT sourced from Module 1.

    Module 1 (base-year assumptions: stock, mileage, efficiency, survival curves,
    PHEV utilisation rate, reconciliation bounds, vehicle equivalent weights) is
    loaded automatically from config.module1_defaults_dir by run_with_config().
    Run scripts/generate_module1_defaults.py to populate that directory.

    Provide only the inputs listed here from your own data pipeline.
    """

    # Required for Module 3
    population: pd.Series | None = None
    gdp: pd.Series | None = None
    esto_road_energy_pj: pd.DataFrame | None = None

    # Optional Module 3 overrides
    # vehicle_type_shares: time-varying shares for passenger/freight vehicle types
    vehicle_type_shares: dict[str, pd.Series] | None = None
    # elasticity_overrides: GDP elasticity per vehicle_type (freight). Module 3 estimates
    # these from energy trends when not provided.
    elasticity_overrides: dict[str, float] | None = None

    # Optional Module 4 policy inputs (fleet policy scenarios)
    turnover_policies: dict[str, dict[str, Any]] | None = None
    fleet_age_shift_years: float | dict[str, float] | None = None
    scrappage_years: dict[str, dict[int, float]] | None = None

    # Module 5 input — future sales share trajectories in LEAP workbook format
    # (Branch Path, Variable="Sales Share", Scenario, Region, year columns).
    # Produced by road_model_inputs_interface. When None, Module 5 returns
    # base-year shares only with no future projection.
    future_sales_shares: pd.DataFrame | None = None

    # Optional Module 5 supplementary data
    ev_sales_data: pd.DataFrame | None = None

    # Required for Module 6
    esto_fuel_totals: pd.DataFrame | None = None

    # Optional Module 7 mirror inputs
    module7_mileage_adjustment_variables: pd.DataFrame | None = None
    module7_efficiency_adjustment_variables: pd.DataFrame | None = None
    module7_scrappage_by_year: pd.DataFrame | dict[str, dict[int, float]] | None = None


# ---------------------------------------------------------------------------
# Workflow engine
# ---------------------------------------------------------------------------


def build_post_reconciliation_stock_targets(
    stock_targets: pd.DataFrame,
    reconciliation_scalars: pd.DataFrame,
    *,
    base_year: int,
    final_year: int,
) -> pd.DataFrame:
    """
    Re-anchor Module 3 stock targets to Module 6 reconciled base-year stock.

    Passenger stocks preserve the final-year ownership target. The difference
    between the original base-year stock and reconciled base-year stock fades
    linearly to zero by final_year.

    Freight stocks preserve the original growth index. The reconciled base-year
    stock is multiplied by the pre-reconciliation stock growth factor in each
    later year, so reconciliation changes the physical level but not the
    freight GDP-elasticity growth shape.
    """
    required_t5 = {"year", "transport_type", "vehicle_type", "target_stock"}
    missing_t5 = sorted(required_t5 - set(stock_targets.columns))
    if missing_t5:
        raise KeyError(f"stock_targets missing required columns: {missing_t5}")

    if stock_targets.empty or reconciliation_scalars.empty:
        return stock_targets.copy()

    base_assumptions = build_base_technology_assumptions(reconciliation_scalars)
    if base_assumptions.empty or "base_stock" not in base_assumptions.columns:
        return stock_targets.copy()

    key_cols = [
        c
        for c in ["economy", "scenario", "transport_type", "vehicle_type"]
        if c in stock_targets.columns and c in base_assumptions.columns
    ]
    if not {"transport_type", "vehicle_type"}.issubset(key_cols):
        raise ValueError("stock targets and reconciliation scalars must share transport_type and vehicle_type")

    reconciled = (
        base_assumptions.groupby(key_cols, dropna=False)["base_stock"]
        .sum()
        .reset_index()
        .rename(columns={"base_stock": "_reconciled_base_stock"})
    )

    out = stock_targets.copy()
    out["_original_target_stock"] = pd.to_numeric(out["target_stock"], errors="coerce")
    out = out.merge(reconciled, on=key_cols, how="left")

    base_lookup = (
        out[out["year"].astype(int).eq(int(base_year))]
        [key_cols + ["_original_target_stock"]]
        .rename(columns={"_original_target_stock": "_original_base_stock"})
    )
    out = out.merge(base_lookup, on=key_cols, how="left")

    base_adjustment = out["_reconciled_base_stock"] - out["_original_base_stock"]
    transport_type = out["transport_type"].astype(str).str.lower()
    passenger_mask = transport_type.eq("passenger")
    freight_mask = transport_type.eq("freight")

    years_from_base = max(1, int(final_year) - int(base_year))
    progress = (
        (pd.to_numeric(out["year"], errors="coerce") - int(base_year)) / years_from_base
    ).clip(lower=0.0, upper=1.0)
    passenger_target_stock = out["_original_target_stock"] + base_adjustment.fillna(0.0) * (1.0 - progress)

    growth_factor = out["_original_target_stock"] / out["_original_base_stock"].replace(0.0, np.nan)
    freight_target_stock = out["_reconciled_base_stock"] * growth_factor

    target_stock = out["_original_target_stock"].copy()
    target_stock.loc[passenger_mask] = passenger_target_stock.loc[passenger_mask]
    target_stock.loc[freight_mask] = freight_target_stock.loc[freight_mask]

    has_reconciled_stock = out["_reconciled_base_stock"].notna()
    out.loc[has_reconciled_stock, "target_stock"] = target_stock[has_reconciled_stock]
    out.loc[
        has_reconciled_stock & out["year"].astype(int).eq(int(base_year)),
        "target_stock",
    ] = out.loc[
        has_reconciled_stock & out["year"].astype(int).eq(int(base_year)),
        "_reconciled_base_stock",
    ]

    out["pre_reconciliation_target_stock"] = out["_original_target_stock"]
    out["reconciled_base_stock"] = out["_reconciled_base_stock"]
    out["stock_target_base_adjustment"] = base_adjustment
    out["stock_target_adjustment_method"] = np.select(
        [
            passenger_mask & has_reconciled_stock,
            freight_mask & has_reconciled_stock,
        ],
        [
            "preserve_final_target_linear_base_adjustment",
            "preserve_growth_index_from_reconciled_base",
        ],
        default="no_reconciled_base_stock",
    )

    return out.drop(columns=["_original_target_stock", "_reconciled_base_stock", "_original_base_stock"])


def run_with_config(config: RoadWorkflowConfig, inputs: RoadWorkflowInputs) -> dict[str, Any]:
    """Run the road model workflow from one orchestrator.

    Returns a dictionary with module outputs and timing metadata.
    """
    timings: dict[str, float] = {}
    outputs: dict[str, Any] = {}

    diagnostics_dir = (
        Path(config.diagnostics_root)
        if (config.enable_visualisations and config.diagnostics_root)
        else None
    )
    output_root = Path(config.output_root)

    log_file = output_root / "workflow.log" if config.save_csv_outputs else None
    logger = StructuredLogger("road_workflow", log_file=log_file, print_to_console=False)

    if config.save_csv_outputs:
        output_root.mkdir(parents=True, exist_ok=True)

    _print_progress(config, f"Road workflow started for {config.economy}.")
    logger.info("workflow_start", economy=config.economy, scenarios=config.scenarios)

    # --- Load Module 1 defaults (mandatory) ---
    # All base-year assumptions (stock, mileage, efficiency, survival curves,
    # PHEV utilisation rate, reconciliation bounds, vehicle equivalent weights)
    # are sourced from Module 1. Refresh them with scripts/generate_module1_defaults.py.
    _print_progress(config, "Module 1: loading base-year road assumptions.")
    logger.info("module1_load", defaults_dir=str(config.module1_defaults_dir), version=config.module1_defaults_version)
    m1 = load_module1_for_economy(
        config.module1_defaults_dir,
        economy=config.economy,
        version=config.module1_defaults_version,
    )
    _merged = parse_leap_format_inputs(
        m1["raw_leap_df"],
        base_year=config.base_year,
    )
    # Module 1 base-year data carries a single scenario label (usually "Target" or "Reference" in older files).
    # The base year is scenario-agnostic — replicate rows for every requested scenario
    # so Module 2's cross-join finds matching data regardless of which scenario is run.
    if "scenario" in _merged.columns and config.scenarios:
        existing = set(_merged["scenario"].dropna().unique())
        missing = [s for s in config.scenarios if s not in existing]
        if missing:
            base_rows = _merged[_merged["scenario"].isin(existing)].copy()
            extras = [base_rows.assign(scenario=s) for s in missing]
            _merged = pd.concat([_merged] + extras, ignore_index=True)
    logger.info(
        "module1_loaded",
        phev_rate=m1["phev_utilisation_rate"],
        scalar_bounds=m1["scalar_bounds"],
        passenger_saturation_level=m1.get("passenger_saturation_level"),
        passenger_saturation_reached=m1.get("passenger_saturation_reached"),
        reconciliation_weights=m1.get("reconciliation_weights"),
        survival_curve_types=list(m1["survival_curves"].keys()),
        vintage_profile_types=list(m1["vintage_profiles"].keys()),
    )
    _print_progress(config, f"Module 1 complete: loaded {len(_merged):,} base input rows.")
    # Expose parsed Module 1 inputs for downstream dashboard writing.
    # Also keep the raw LEAP DataFrame so the dashboard can find rows that were
    # dropped for missing year values — those disappear from merged_inputs.
    outputs["module1_merged"] = _merged
    outputs["module1_raw_df"] = m1["raw_leap_df"]
    outputs["population"] = inputs.population

    if diagnostics_dir is not None:
        try:
            written = write_module1_charts(_merged, diagnostics_dir)
            logger.info("module1_output", charts_written=len(written), **log_dataframe_info(_merged, "module1_base_inputs"))
        except Exception as exc:
            logger.warning("module1_diagnostics_failed", error=str(exc))

    # ------------------------ Module 2 ------------------------
    if config.run_m2:
        if _merged is None:
            raise ValueError(
                "Module 2 requires Module 1 LEAP-format defaults loaded from module1_defaults_dir"
            )
        logger.info("module2_input", **log_dataframe_info(_merged, "input"))
        _print_progress(config, "Module 2: building base-year branch table.")
        t0 = time.perf_counter()
        t4 = run_module2(
            merged_inputs=_merged,
            config_dir=config.config_dir,
            economies=[config.economy],
            scenarios=config.scenarios,
            base_year=config.base_year,
            leap_workbook_path=config.leap_workbook_path,
            diagnostics_dir=diagnostics_dir,
        )
        timings["module2_seconds"] = time.perf_counter() - t0
        logger.info("module2_output", duration_sec=timings["module2_seconds"], **log_dataframe_info(t4, "output"))
        _print_progress(config, f"Module 2 complete: {len(t4):,} branch rows.")
        outputs["T4"] = t4
        if config.save_csv_outputs:
            _write_df(t4, output_root / "module2" / "T4_base_year_branches.csv")
    else:
        t4 = outputs.get("T4")

    # ------------------------ Module 3 ------------------------
    if config.run_m3:
        if t4 is None:
            t4 = outputs.get("T4")
        if t4 is None:
            raise ValueError("Module 3 requires T4 from Module 2")
        if inputs.population is None or inputs.gdp is None or inputs.esto_road_energy_pj is None:
            raise ValueError("Module 3 requires inputs.population, inputs.gdp, inputs.esto_road_energy_pj")

        t0 = time.perf_counter()
        _print_progress(config, "Module 3: projecting stock targets.")
        _sat = m1.get("passenger_saturation_level")
        _saturation_overrides = {"researcher": float(_sat)} if _sat is not None else None
        _module3_config = dict(config.module3_config or {})
        _module3_config["passenger_stock_growth_rate_adjustment"] = float(
            m1.get("passenger_stock_growth_rate_adjustment", 1.2)
        )
        _vehicle_type_shares = inputs.vehicle_type_shares
        if _vehicle_type_shares is None:
            _physical_stock_shares = _interpolate_vehicle_type_stock_shares(
                module1_stock_shares=m1.get("vehicle_type_stock_shares"),
                base_stocks=_read_base_stocks_for_shares(t4, config.base_year),
                years=config.projection_years(),
            )
            _vehicle_type_shares = _convert_passenger_physical_to_capacity_shares(
                _physical_stock_shares,
                m1["vehicle_equivalent_weights"] or None,
            )
        t5 = run_module3(
            base_year_branches=t4,
            population=inputs.population,
            gdp=inputs.gdp,
            esto_road_energy_pj=inputs.esto_road_energy_pj,
            projection_years=config.projection_years(),
            vehicle_type_shares=_vehicle_type_shares,
            saturation_overrides=_saturation_overrides,
            passenger_saturation_reached=bool(m1.get("passenger_saturation_reached", False)),
            elasticity_overrides=inputs.elasticity_overrides,
            elasticity_adjustments=(
                {"freight_total": float(m1.get("freight_gdp_elasticity_adjustment", 1.0))}
                if float(m1.get("freight_gdp_elasticity_adjustment", 1.0)) != 1.0
                else None
            ),
            vehicle_equivalent_weights=m1["vehicle_equivalent_weights"] or None,
            vehicle_equivalent_weight_bounds=m1.get("vehicle_equivalent_weight_bounds"),
            config=_module3_config,
            diagnostics_dir=str(diagnostics_dir) if diagnostics_dir else None,
            economy=config.economy,
            scenario=config.scenarios[0],
        )
        timings["module3_seconds"] = time.perf_counter() - t0
        # Module 3 reindexes against the full population series, producing null rows
        # beyond final_year.  Clamp to the intended projection window.
        _proj_years = set(config.projection_years())
        t5 = t5[t5["year"].isin(_proj_years)].copy()
        _print_progress(config, f"Module 3 complete: {len(t5):,} stock target rows.")
        outputs["T5"] = t5
        if config.save_csv_outputs:
            _write_df(t5, output_root / "module3" / "T5_stock_targets.csv")
    else:
        t5 = outputs.get("T5")

    # ------------------------ Module 4 ------------------------
    if config.run_m4:
        if t5 is None:
            t5 = outputs.get("T5")
        if t5 is None:
            raise ValueError("Module 4 requires T5 from Module 3")
        if not m1["survival_curves"] or not m1["vintage_profiles"]:
            raise ValueError(
                "Module 4 requires survival_curves and vintage_profiles from Module 1 defaults. "
                "Ensure module1_defaults_dir contains data for this economy."
            )

        logger.info("module4_input", **log_dataframe_info(t5, "stock_targets"))
        _print_progress(config, "Module 4: calculating sales, retirements, and vintages.")
        t0 = time.perf_counter()
        t6, t6v = run_module4(
            stock_targets=t5,
            survival_curves=m1["survival_curves"],
            vintage_profiles=m1["vintage_profiles"],
            turnover_policies=inputs.turnover_policies,
            fleet_age_shift_years=inputs.fleet_age_shift_years,
            scrappage_years=inputs.scrappage_years,
            config=config.module4_config,
            diagnostics_dir=diagnostics_dir,
            economy=config.economy,
            scenario=config.scenarios[0],
        )
        timings["module4_seconds"] = time.perf_counter() - t0
        logger.info("module4_output", duration_sec=timings["module4_seconds"], **log_dataframe_info(t6, "sales_turnover"))
        _print_progress(config, f"Module 4 complete: {len(t6):,} sales/turnover rows.")
        outputs["T6"] = t6
        outputs["T6v"] = t6v
        if config.save_csv_outputs:
            _write_df(t6, output_root / "module4" / "T6_sales_turnover.csv")
            _write_df(t6v, output_root / "module4" / "T6v_vintage_profiles.csv")
    else:
        t6 = outputs.get("T6")
        t6v = outputs.get("T6v")

    # ------------------------ Module 5 ------------------------
    if config.run_m5:
        if t4 is None:
            t4 = outputs.get("T4")
        if t4 is None:
            raise ValueError("Module 5 requires T4 from Module 2")

        # Parse future sales shares from LEAP format if provided
        _future_sales: pd.DataFrame | None = None
        if inputs.future_sales_shares is not None:
            _parsed_future = parse_leap_format_inputs(
                inputs.future_sales_shares,
            )
            _sales_rows = _parsed_future[_parsed_future["variable"] == "sales_share"].copy()
            if not _sales_rows.empty:
                group_cols = [c for c in
                    ["economy", "scenario", "year", "transport_type", "vehicle_type", "drive_type"]
                    if c in _sales_rows.columns]
                _future_sales = (
                    _sales_rows.groupby(group_cols, as_index=False)["value"]
                    .sum()
                    .rename(columns={"value": "sales_share"})
                )
        else:
            _future_sales = _module1_future_sales_share_rows(
                m1["raw_leap_df"],
                base_year=config.base_year,
            )
        _module1_sales_shares = _module1_sales_share_overrides(
            _merged,
            economy=config.economy,
            base_year=config.base_year,
        )

        t0 = time.perf_counter()
        _print_progress(config, "Module 5: preparing vehicle sales shares.")
        t7, t7f = run_module5(
            base_year_branches=t4,
            future_sales_shares=_future_sales,
            economy=config.economy,
            scenarios=config.scenarios,
            economy_aliases=[
                config.economy,
                ECONOMY_CODE_TO_LEAP_REGION_NAMES.get(config.economy, ""),
            ],
            ev_sales_data=inputs.ev_sales_data,
            researcher_sales_shares=_module1_sales_shares,
            diagnostics_dir=diagnostics_dir,
        )
        timings["module5_seconds"] = time.perf_counter() - t0
        _print_progress(config, f"Module 5 complete: {len(t7f):,} future sales-share rows.")
        outputs["T7"] = t7
        outputs["T7f"] = t7f
        if config.save_csv_outputs:
            _write_df(t7, output_root / "module5" / "T7_sales_shares.csv")
            _write_df(t7f, output_root / "module5" / "T7f_future_shares.csv")
    else:
        t7f = outputs.get("T7f")

    # ------------------------ Module 6 ------------------------
    if config.run_m6:
        if t4 is None:
            t4 = outputs.get("T4")
        if t6 is None:
            t6 = outputs.get("T6")
        if t7f is None:
            t7f = outputs.get("T7f")

        if t4 is None or t6 is None or t7f is None:
            raise ValueError("Module 6 requires T4, T6, and T7f (from Modules 2, 4, 5)")
        if inputs.esto_fuel_totals is None:
            raise ValueError("Module 6 requires inputs.esto_fuel_totals")

        logger.info("module6_input", t4_rows=len(t4), t6_rows=len(t6), t7f_rows=len(t7f))
        _print_progress(config, "Module 6: reconciling fuel energy and preparing LEAP inputs.")
        t0 = time.perf_counter()
        m6 = run_module6(
            base_year_branches=t4,
            sales_turnover=t6,
            sales_shares=t7f,
            esto_fuel_totals=inputs.esto_fuel_totals,
            projection_years=config.projection_years(),
            reconciliation_weights=m1.get("reconciliation_weights"),
            phev_electric_utilisation_rate=m1["phev_utilisation_rate"],
            scalar_bounds=m1["scalar_bounds"],
            match_tolerance=config.module6_match_tolerance,
            diagnostics_dir=diagnostics_dir,
        )
        stock_targets_adjusted = False
        t5_pre_reconciliation = t5.copy() if isinstance(t5, pd.DataFrame) else None
        t6_pre_reconciliation = t6.copy() if isinstance(t6, pd.DataFrame) else None
        t6v_pre_reconciliation = t6v.copy() if isinstance(t6v, pd.DataFrame) else None

        if config.adjust_stock_targets_after_reconciliation and isinstance(t5, pd.DataFrame):
            t5_post_reconciliation = build_post_reconciliation_stock_targets(
                t5,
                m6["T9"],
                base_year=config.base_year,
                final_year=config.final_year,
            )
            _before = pd.to_numeric(t5["target_stock"], errors="coerce").fillna(0.0)
            _after = pd.to_numeric(t5_post_reconciliation["target_stock"], errors="coerce").fillna(0.0)
            stock_targets_adjusted = not _before.reset_index(drop=True).equals(_after.reset_index(drop=True))

            if stock_targets_adjusted:
                _print_progress(
                    config,
                    "Module 6: re-anchoring stock trajectory to reconciled base-year stock.",
                )
                t_adjust = time.perf_counter()
                t5 = t5_post_reconciliation
                t6, t6v = run_module4(
                    stock_targets=t5,
                    survival_curves=m1["survival_curves"],
                    vintage_profiles=m1["vintage_profiles"],
                    turnover_policies=inputs.turnover_policies,
                    fleet_age_shift_years=inputs.fleet_age_shift_years,
                    scrappage_years=inputs.scrappage_years,
                    config=config.module4_config,
                    diagnostics_dir=diagnostics_dir,
                    economy=config.economy,
                    scenario=config.scenarios[0],
                )
                m6 = run_module6(
                    base_year_branches=t4,
                    sales_turnover=t6,
                    sales_shares=t7f,
                    esto_fuel_totals=inputs.esto_fuel_totals,
                    projection_years=config.projection_years(),
                    reconciliation_weights=m1.get("reconciliation_weights"),
                    phev_electric_utilisation_rate=m1["phev_utilisation_rate"],
                    scalar_bounds=m1["scalar_bounds"],
                    match_tolerance=config.module6_match_tolerance,
                    diagnostics_dir=None,
                )
                timings["post_reconciliation_stock_adjustment_seconds"] = time.perf_counter() - t_adjust
                outputs["T5_pre_reconciliation"] = t5_pre_reconciliation
                outputs["T6_pre_reconciliation"] = t6_pre_reconciliation
                outputs["T6v_pre_reconciliation"] = t6v_pre_reconciliation
                outputs["T5_post_reconciliation"] = t5
                outputs["T6_post_reconciliation"] = t6
                outputs["T6v_post_reconciliation"] = t6v

                if diagnostics_dir is not None:
                    try:
                        write_module6_charts(
                            {
                                **m6,
                                "T5_pre_reconciliation": t5_pre_reconciliation,
                                "T5_post_reconciliation": t5,
                            },
                            diagnostics_dir,
                        )
                    except Exception as exc:
                        logger.warning("module6_stock_trajectory_diagnostics_failed", error=str(exc))

        timings["module6_seconds"] = time.perf_counter() - t0
        logger.info(
            "module6_output",
            duration_sec=timings["module6_seconds"],
            **{k: log_dataframe_info(v, k) for k, v in m6.items() if isinstance(v, pd.DataFrame)},
        )
        _print_progress(config, f"Module 6 complete: {len(m6['T11']):,} LEAP-ready rows.")
        for line in _module6_reconciliation_summary(m6):
            _print_progress(config, line)

        base_year_warnings = _validate_t11_base_year_consistency(m6["T11"], config.base_year)
        for w in base_year_warnings:
            _print_progress(config, f"Base year consistency warning: {w['message']}")
            logger.warning("t11_base_year_mismatch", **{k: v for k, v in w.items() if k != "message"})

        t11_with_ca = _extract_current_accounts_base_year(m6["T11"], config.base_year)
        m6 = {**m6, "T11": t11_with_ca}
        outputs["T5"] = t5
        outputs["T6"] = t6
        outputs["T6v"] = t6v
        outputs.update(m6)

        if config.save_csv_outputs:
            if stock_targets_adjusted:
                _write_df(t5_pre_reconciliation, output_root / "module3" / "T5_stock_targets_pre_reconciliation.csv")
                _write_df(t5, output_root / "module3" / "T5_stock_targets.csv")
                _write_df(t5, output_root / "module3" / "T5_stock_targets_post_reconciliation.csv")
                _write_df(t6_pre_reconciliation, output_root / "module4" / "T6_sales_turnover_pre_reconciliation.csv")
                _write_df(t6v_pre_reconciliation, output_root / "module4" / "T6v_vintage_profiles_pre_reconciliation.csv")
                _write_df(t6, output_root / "module4" / "T6_sales_turnover.csv")
                _write_df(t6, output_root / "module4" / "T6_sales_turnover_post_reconciliation.csv")
                _write_df(t6v, output_root / "module4" / "T6v_vintage_profiles.csv")
                _write_df(t6v, output_root / "module4" / "T6v_vintage_profiles_post_reconciliation.csv")
            _write_df(m6["T8"], output_root / "module6" / "T8_fuel_allocation.csv")
            _write_df(m6["T9"], output_root / "module6" / "T9_reconciliation_scalars.csv")
            _write_df(m6["T10"], output_root / "module6" / "T10_device_shares.csv")
            _write_df(m6["T11"], output_root / "module6" / "T11_leap_ready.csv")
            _write_df(m6["T12"], output_root / "module6" / "T12_reconciliation_diagnostics.csv")
            _write_df(m6["T12_phev"], output_root / "module6" / "T12_phev_utilisation_diagnostics.csv")
            module1_reimport_path = output_root / "module6" / f"{config.economy}_module1_reimport_reconciled.csv"
            module1_source_long = load_module1_source_long_csv(
                config.module1_defaults_dir,
                economy=config.economy,
                version=config.module1_defaults_version,
            )
            write_reconciled_module1_reimport_csv(
                source_long_df=module1_source_long,
                leap_ready=m6["T11"],
                output_path=module1_reimport_path,
                base_year=config.base_year,
                reconciliation_scalars=m6["T9"],
            )
            outputs["module1_reimport_reconciled_path"] = module1_reimport_path
            leap_import_path = output_root / "module6" / f"{config.economy}_leap_import.xlsx"
            reference_path = Path(config.leap_reference_path) if config.leap_reference_path else _default_leap_reference_path()
            if reference_path is not None and reference_path.exists():
                warnings = write_strict_leap_import_workbook(
                    m6["T11"],
                    leap_import_path,
                    reference_path=reference_path,
                    economy_long_name=ECONOMY_CODE_TO_LEAP_REGION_NAMES.get(config.economy, config.economy),
                    coverage_diagnostics_path=(
                        output_root / "module6" / f"{config.economy}_leap_import_row_coverage_diagnostics.csv"
                        if config.write_leap_row_diagnostics
                        else None
                    ),
                    economy_code=config.economy,
                    export_values_in_raw_units=config.leap_import_export_values_in_raw_units,
                )
                outputs["leap_import_warnings"] = warnings
                if config.write_leap_row_diagnostics:
                    outputs["leap_import_row_coverage_diagnostics_path"] = (
                        output_root / "module6" / f"{config.economy}_leap_import_row_coverage_diagnostics.csv"
                    )
                if warnings:
                    pd.DataFrame(warnings).to_csv(
                        output_root / "module6" / f"{config.economy}_leap_import_warnings.csv",
                        index=False,
                    )
            else:
                write_leap_import_workbook(
                    m6["T11"],
                    leap_import_path,
                    economy_long_name=ECONOMY_CODE_TO_LEAP_REGION_NAMES.get(config.economy, config.economy),
                )
                outputs["leap_import_warnings"] = [
                    {
                        "severity": "warning",
                        "type": "missing_reference_export",
                        "message": "Strict LEAP writer skipped because no reference export was found.",
                    }
                ]

    # ------------------------ Module 7 ------------------------
    if config.run_m7:
        t6 = outputs.get("T6") if t6 is None else t6
        t9 = outputs.get("T9")
        t10 = outputs.get("T10")
        t7f = outputs.get("T7f") if t7f is None else t7f
        if t6 is None or t9 is None or t10 is None:
            raise ValueError("Module 7 requires T6, T9, and T10 (from Modules 4 and 6)")

        logger.info("module7_input", t6_rows=len(t6), t9_rows=len(t9), t10_rows=len(t10))
        _print_progress(config, "Module 7: running Python mirror checks.")
        t0 = time.perf_counter()
        m7 = run_module7_mirror(
            sales_turnover=t6,
            reconciliation_scalars=t9,
            device_shares=t10,
            sales_shares=t7f,
            projection_years=config.projection_years(),
            mileage_adjustment_variables=inputs.module7_mileage_adjustment_variables,
            efficiency_adjustment_variables=inputs.module7_efficiency_adjustment_variables,
            scrappage_by_year=inputs.module7_scrappage_by_year,
            diagnostics_dir=str(diagnostics_dir) if diagnostics_dir else None,
            base_year_branches=outputs.get("T4"),
        )
        timings["module7_seconds"] = time.perf_counter() - t0
        logger.info(
            "module7_output",
            duration_sec=timings["module7_seconds"],
            **{k: log_dataframe_info(v, k) for k, v in m7.items() if isinstance(v, pd.DataFrame)},
        )
        _print_progress(config, "Module 7 complete.")
        outputs.update(m7)

        if config.save_csv_outputs:
            if "T13" in m7:
                _write_df(m7["T13"], output_root / "module7" / "T13_mirror_outputs.csv")
            if "T13_fuel" in m7:
                _write_df(m7["T13_fuel"], output_root / "module7" / "T13_mirror_fuel_outputs.csv")

    if config.save_csv_outputs and isinstance(outputs.get("T6v"), pd.DataFrame):
        try:
            lifecycle_result = export_lifecycle_profiles_from_t6v(
                outputs["T6v"],
                output_root / "lifecycle_profiles",
                economy=config.economy,
                area_name=f"{ECONOMY_CODE_TO_LEAP_REGION_NAMES.get(config.economy, config.economy)} transport",
            )
            outputs["lifecycle_profile_manifest_path"] = lifecycle_result["manifest_path"]
            outputs["lifecycle_profile_zip_path"] = lifecycle_result.get("zip_path")
            logger.info(
                "lifecycle_profiles_exported",
                manifest_path=str(lifecycle_result["manifest_path"]),
                zip_path=str(lifecycle_result.get("zip_path", "")),
                profile_count=len(lifecycle_result["manifest"]),
            )
            _print_progress(config, "Lifecycle profile export complete.")
        except Exception as exc:
            logger.warning("lifecycle_profile_export_failed", error=str(exc))
            outputs["lifecycle_profile_export_error"] = str(exc)

    dashboard_dir: Path | None = None
    if diagnostics_dir is not None:
        try:
            t0 = time.perf_counter()
            summary_written = write_workflow_summary_charts({**outputs, "timings": timings}, diagnostics_dir)
            timings["workflow_summary_visuals_seconds"] = time.perf_counter() - t0
            logger.info(
                "workflow_visual_summary",
                charts_written=len(summary_written),
                duration_sec=timings["workflow_summary_visuals_seconds"],
            )
        except Exception as exc:
            logger.warning("workflow_summary_charts_failed", error=str(exc))

        try:
            t0 = time.perf_counter()
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            dashboard_dir = diagnostics_dir / f"dashboard_{ts}"
            # Purge old timestamped dashboards; keep recent ones so users can
            # compare runs by switching between open browser tabs.
            _purge_old_dashboards(diagnostics_dir)
            html_written = write_module_pages(
                {**outputs, "timings": timings},
                dashboard_dir=dashboard_dir,
                economy=config.economy,
            )
            timings["dashboard_html_seconds"] = time.perf_counter() - t0
            logger.info(
                "workflow_dashboard",
                pages_written=len(html_written),
                dashboard_dir=str(dashboard_dir),
                duration_sec=timings["dashboard_html_seconds"],
            )
        except Exception as exc:
            logger.warning(
                "workflow_dashboard_failed",
                error=str(exc),
                traceback=traceback.format_exc(),
            )
            dashboard_dir = None

    outputs["timings"] = timings
    outputs["workflow_meta"] = {
        "economy": config.economy,
        "scenarios": config.scenarios,
        "base_year": config.base_year,
        "final_year": config.final_year,
        "enable_visualisations": config.enable_visualisations,
        "diagnostics_root": str(diagnostics_dir) if diagnostics_dir else None,
        "dashboard_dir": str(dashboard_dir) if dashboard_dir else None,
        "output_root": str(output_root),
    }
    logger.info("workflow_complete", total_timings_sec=sum(timings.values()))
    _print_progress(config, f"Road workflow complete. Total timed work: {sum(timings.values()):.1f} seconds.")
    return outputs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_df(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def _validate_t11_base_year_consistency(t11: pd.DataFrame, base_year: int) -> list[dict]:
    """Warn if any (branch, variable) has different base-year values across scenarios.

    The base year is calibrated from observed data and should be scenario-agnostic.
    Differences indicate a bug in the upstream modules.
    """
    from itertools import combinations

    base = t11[t11["year"] == base_year].copy()
    scenarios = sorted(base["scenario"].dropna().unique())
    if len(scenarios) < 2:
        return []

    key_cols = [c for c in ["economy", "leap_branch_path", "variable"] if c in base.columns]
    pivot = base.pivot_table(index=key_cols, columns="scenario", values="value", aggfunc="first")
    warnings: list[dict] = []
    for s1, s2 in combinations(scenarios, 2):
        if s1 not in pivot.columns or s2 not in pivot.columns:
            continue
        diff = (pivot[s1] - pivot[s2]).abs()
        for idx in diff[diff > 1e-9].index:
            warnings.append({
                "severity": "warning",
                "type": "base_year_scenario_mismatch",
                "key": str(idx),
                "scenario_a": s1,
                "scenario_b": s2,
                "value_a": float(pivot.loc[idx, s1]),
                "value_b": float(pivot.loc[idx, s2]),
                "message": (
                    f"Base year ({base_year}) values differ between '{s1}' and '{s2}' "
                    f"for {idx}"
                ),
            })
    return warnings


def _extract_current_accounts_base_year(t11: pd.DataFrame, base_year: int) -> pd.DataFrame:
    """Append Current Accounts rows to T11 by extracting the base-year slice.

    Current Accounts in LEAP holds base-year stock/sales scalars (not a projection).
    We derive them from the first available scenario's base-year values rather than
    running a separate CA scenario, which keeps them consistent with the projection.
    """
    if "Current Accounts" in t11["scenario"].values:
        return t11
    first_scenario = t11["scenario"].dropna().iloc[0] if not t11.empty else None
    if first_scenario is None:
        return t11
    base_rows = t11[(t11["year"] == base_year) & (t11["scenario"] == first_scenario)].copy()
    base_rows["scenario"] = "Current Accounts"
    return pd.concat([t11, base_rows], ignore_index=True)


def _default_leap_reference_path() -> Path | None:
    repo_root = Path(__file__).resolve().parents[1]
    candidates = [
        repo_root
        / "input_data"
        / "leap_import_templates"
        / "DEFAULT_transport_leap_import_TGT_REF_CA.xlsx",
        repo_root.parent
        / "road_model_inputs_interface"
        / "back-end"
        / "data"
        / "road_model"
        / "leap_import_workbooks"
        / "transport_leap_export_combined_ALL_ECONS_domestic_international_Target_20260526.xlsx",
        Path(r"C:\Users\Work\github\leap_utilities\data\full model export.xlsx"),
    ]
    return next((path for path in candidates if path.exists()), None)


def _validate_macro_inputs(
    population: pd.Series,
    gdp: pd.Series,
    esto_road_energy_pj: pd.DataFrame,
    projection_years: list[int],
) -> None:
    """Fail fast if macro driver inputs are structurally wrong or under-cover projection years."""
    series_checks = [
        ("population", population),
        ("gdp", gdp),
    ]
    for name, s in series_checks:
        covered_years = set(pd.to_numeric(s.index, errors="coerce").dropna().astype(int))
        missing_years = sorted(set(projection_years) - covered_years)
        if missing_years:
            raise ValueError(
                f"{name} has no data for {len(missing_years)} projection year(s): "
                f"{missing_years[:5]}{'...' if len(missing_years) > 5 else ''}"
            )

    required_cols = {"year", "transport_type", "energy_pj"}
    actual_cols = set(esto_road_energy_pj.columns)
    missing_cols = required_cols - actual_cols
    if missing_cols:
        raise ValueError(
            f"esto_road_energy_pj is missing required columns: {sorted(missing_cols)}. "
            f"Found columns: {sorted(actual_cols)}"
        )


def _print_progress(config: RoadWorkflowConfig, message: str) -> None:
    if config.show_progress:
        print(message)


def _module1_future_sales_share_rows(
    raw_leap_df: pd.DataFrame,
    base_year: int,
) -> pd.DataFrame:
    """Extract projected Sales Share rows from the canonical Module 1 package."""
    if raw_leap_df is None or raw_leap_df.empty:
        return pd.DataFrame()

    parsed = parse_leap_format_inputs(raw_leap_df)
    sales_rows = parsed[
        parsed["variable"].eq("sales_share")
        & (parsed["year"] > base_year)
        & parsed["vehicle_type"].notna()
        & parsed["drive_type"].notna()
    ].copy()
    if sales_rows.empty:
        return pd.DataFrame()

    group_cols = [
        c for c in
        ["economy", "scenario", "year", "transport_type", "vehicle_type", "drive_type"]
        if c in sales_rows.columns
    ]
    return (
        sales_rows.groupby(group_cols, as_index=False)["value"]
        .sum()
        .rename(columns={"value": "sales_share"})
    )


def _module1_sales_share_overrides(
    module1_inputs: pd.DataFrame,
    economy: str,
    base_year: int,
) -> pd.DataFrame:
    """Extract explicit base-year sales-share rows from parsed Module 1 inputs."""
    required = {"scenario", "year", "vehicle_type", "drive_type", "variable", "value"}
    if module1_inputs.empty or not required.issubset(module1_inputs.columns):
        return pd.DataFrame()

    df = module1_inputs[
        module1_inputs["variable"].eq("sales_share")
        & module1_inputs["year"].eq(base_year)
        & module1_inputs["vehicle_type"].notna()
        & module1_inputs["drive_type"].notna()
    ].copy()
    if df.empty:
        return pd.DataFrame()

    df["sales_share"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["sales_share"])
    if df.empty:
        return pd.DataFrame()

    group_cols = ["scenario", "vehicle_type", "drive_type"]
    df = df.groupby(group_cols, as_index=False)["sales_share"].sum()
    if df["sales_share"].max() > 1.0:
        df["sales_share"] = df["sales_share"] / 100.0
    df["economy"] = economy
    df["source_flag"] = "module1_input"
    return df[["economy", "scenario", "vehicle_type", "drive_type", "sales_share", "source_flag"]]


def _module6_reconciliation_summary(module6_outputs: dict[str, Any]) -> list[str]:
    t9 = module6_outputs.get("T9")
    t12 = module6_outputs.get("T12")
    if not isinstance(t9, pd.DataFrame) or t9.empty:
        return []

    lines: list[str] = []
    out_of_bounds = int((~t9.get("scalars_within_bounds", pd.Series(dtype=bool)).astype(bool)).sum())
    hit_max_iterations = int(t9.get("reconciliation_hit_max_iterations", pd.Series(dtype=bool)).astype(bool).sum())
    if out_of_bounds or hit_max_iterations:
        scalar_subset = t9.copy()
        if out_of_bounds and "scalars_within_bounds" in scalar_subset.columns:
            scalar_subset = scalar_subset[~scalar_subset["scalars_within_bounds"].astype(bool)].copy()
        scalar_notes = []
        for column, label in [
            ("stock_scalar", "stock"),
            ("mileage_scalar", "mileage"),
            ("efficiency_scalar", "efficiency"),
        ]:
            if column in scalar_subset.columns and not scalar_subset.empty:
                avg_scalar = pd.to_numeric(scalar_subset[column], errors="coerce").dropna().mean()
                if pd.notna(avg_scalar):
                    scalar_notes.append(f"{label}={avg_scalar:.3f}x")
        scalar_text = f" Average bounded scalars: {', '.join(scalar_notes)}." if scalar_notes else ""
        lines.append(
            "Module 6 reconciliation note: "
            f"{out_of_bounds:,} branch(es) reached scalar bounds; "
            f"{hit_max_iterations:,} branch(es) hit the iteration limit."
            f"{scalar_text}"
        )

    if isinstance(t12, pd.DataFrame) and not t12.empty and "gap_pct" in t12.columns:
        if "reconciliation_status" in t12.columns:
            status = t12["reconciliation_status"].astype(str)
        else:
            status = pd.Series("ok", index=t12.index)
        problem_fuels = t12[status != "ok"].copy()
        if not problem_fuels.empty:
            problem_fuels = problem_fuels.sort_values("gap_pct", ascending=False).head(3)
            fuel_notes = [
                f"{row['fuel']} ({row['gap_pct']:.2f}% gap)"
                for _, row in problem_fuels.iterrows()
            ]
            lines.append("Module 6 fuel check: largest remaining gaps are " + "; ".join(fuel_notes) + ".")
        else:
            lines.append("Module 6 fuel check: reconciled fuel totals are within tolerance.")

    return lines


def _read_leap_input_table(path: Path) -> pd.DataFrame | None:
    """Load a potential LEAP-format table from CSV/XLSX/JSON.

    Returns:
        DataFrame when file can be parsed, otherwise None.
    """
    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            return pd.read_csv(path)
        if suffix in {".xlsx", ".xls"}:
            return pd.read_excel(path)
        if suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
                return pd.DataFrame(payload["rows"])
            if isinstance(payload, list):
                return pd.DataFrame(payload)
            return pd.DataFrame(payload)
    except Exception:
        return None
    return None


def _looks_like_future_sales_share_input(df: pd.DataFrame, base_year: int) -> bool:
    """True when DataFrame appears to contain future LEAP-format Sales Share rows."""
    required = {"Branch Path", "Variable", "Scenario", "Region"}
    if not required.issubset(df.columns):
        return False

    year_cols: list[int] = []
    for col in df.columns:
        try:
            year_cols.append(int(col))
        except (TypeError, ValueError):
            continue
    if not year_cols or max(year_cols) <= base_year:
        return False

    sales_mask = df["Variable"].astype(str).str.strip().str.lower().eq("sales share")
    if not sales_mask.any():
        return False

    future_cols = [str(y) for y in year_cols if y > base_year and str(y) in df.columns]
    if not future_cols:
        return False

    future_values = df.loc[sales_mask, future_cols].apply(pd.to_numeric, errors="coerce")
    return bool(future_values.notna().any().any())


def _candidate_future_sales_paths(repo_root: Path, economy: str, scenario: str) -> list[Path]:
    """Build candidate file paths for convenience auto-loading."""
    compact = economy.replace("_", "")
    candidates: list[Path] = []
    scenario_labels = [
        scenario,
        "Target" if str(scenario).strip().lower() == "tgt" else scenario,
        "Reference" if str(scenario).strip().lower() == "ref" else scenario,
    ]
    # Stable de-dup while preserving order.
    _seen_labels: set[str] = set()
    scenario_labels = [s for s in scenario_labels if not (s in _seen_labels or _seen_labels.add(s))]

    # Primary deterministic source: leap_transport domestic exports.
    # This is the same upstream source used for other road assumptions.
    leap_transport_root = repo_root.parent / "leap_transport" / "results" / "domestic_exports"
    for scen in scenario_labels:
        candidates.append(leap_transport_root / f"{economy}_transport_leap_export_{scen}.xlsx")

    # Local convention inside leap_road_model
    local_dir = repo_root / "input_data" / "future_sales_shares"
    for stem in (economy, compact):
        candidates.extend([
            local_dir / f"{stem}.csv",
            local_dir / f"{stem}.xlsx",
            local_dir / f"{stem}.json",
            local_dir / f"future_sales_shares_{stem}.csv",
            local_dir / f"future_sales_shares_{stem}.xlsx",
            local_dir / f"future_sales_shares_{stem}.json",
        ])

    # Sibling road_model_inputs_interface static bundle convention
    static_root = repo_root.parent / "road_model_inputs_interface" / "front-end" / "road-module1-static"
    if static_root.exists():
        candidates.extend(static_root.glob(f"*/{compact}.json"))
        candidates.extend(static_root.glob(f"*/{economy}.json"))

    # Optional explicit path(s) from environment.
    # Supports placeholders {economy} and {economy_compact}.
    env_paths = os.getenv("ROAD_MODEL_FUTURE_SALES_SHARES_PATH", "").strip()
    if env_paths:
        for token in env_paths.split(os.pathsep):
            token = token.strip()
            if not token:
                continue
            resolved = token.format(economy=economy, economy_compact=compact)
            p = Path(resolved)
            if p.is_dir():
                for stem in (economy, compact):
                    candidates.extend([
                        p / f"{stem}.csv",
                        p / f"{stem}.xlsx",
                        p / f"{stem}.json",
                        p / f"future_sales_shares_{stem}.csv",
                        p / f"future_sales_shares_{stem}.xlsx",
                        p / f"future_sales_shares_{stem}.json",
                    ])
            else:
                candidates.append(p)

    # Stable de-dup, preserve order
    seen: set[Path] = set()
    ordered: list[Path] = []
    for p in candidates:
        if p in seen:
            continue
        seen.add(p)
        ordered.append(p)
    return ordered


def _autodiscover_future_sales_shares(
    repo_root: Path,
    economy: str,
    base_year: int,
    scenario: str = "Target",
) -> tuple[pd.DataFrame | None, Path | None]:
    """Try to find and load a future-sales-share LEAP table for one economy."""
    if os.getenv("ROAD_MODEL_DISABLE_AUTO_FUTURE_SALES_SHARES", "").strip() in {"1", "true", "True"}:
        return None, None

    for path in _candidate_future_sales_paths(
        repo_root=repo_root,
        economy=economy,
        scenario=scenario,
    ):
        if not path.exists() or not path.is_file():
            continue
        df = _read_leap_input_table(path)
        if df is None or df.empty:
            continue
        if _looks_like_future_sales_share_input(df, base_year=base_year):
            return df, path

    return None, None


_DASHBOARD_TTL_HOURS: int = 48
_DASHBOARD_MAX_KEEP: int = 3
_DASHBOARD_DIR_RE = re.compile(r"^dashboard_\d{8}_\d{6}$")


def _purge_old_dashboards(
    diagnostics_dir: Path,
    ttl_hours: int = _DASHBOARD_TTL_HOURS,
    max_keep: int = _DASHBOARD_MAX_KEEP,
) -> None:
    """Delete timestamped dashboard dirs older than ttl_hours, keeping at most max_keep."""
    if not diagnostics_dir.is_dir():
        return
    dirs = sorted(
        (d for d in diagnostics_dir.iterdir() if d.is_dir() and _DASHBOARD_DIR_RE.match(d.name)),
        key=lambda d: d.name,
        reverse=True,
    )
    cutoff = time.time() - ttl_hours * 3600
    for i, d in enumerate(dirs):
        if i >= max_keep or d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)


def _latest_dashboard_dir(diagnostics_dir: Path) -> Path | None:
    """Return the most recent dashboard_YYYYMMDD_HHMMSS dir, or None."""
    if not diagnostics_dir.is_dir():
        return None
    candidates = sorted(
        (d for d in diagnostics_dir.iterdir() if d.is_dir() and _DASHBOARD_DIR_RE.match(d.name)),
        key=lambda d: d.name,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _print_dashboard_link(outputs: dict[str, Any]) -> None:
    """Print a local file URL for the generated dashboard when available."""
    workflow_meta = outputs.get("workflow_meta") or {}
    dashboard_dir_str = workflow_meta.get("dashboard_dir")
    if dashboard_dir_str:
        dashboard_dir = Path(dashboard_dir_str)
        dashboard_index = dashboard_dir / "index.html"
        if dashboard_index.exists():
            print(f"Dashboard: {dashboard_index.resolve().as_uri()}")
        elif dashboard_dir.exists():
            print(f"Dashboard folder: {dashboard_dir.resolve().as_uri()}")
        return
    # Fallback: scan for latest timestamped dashboard dir
    diagnostics_root = workflow_meta.get("diagnostics_root")
    if not diagnostics_root:
        return
    dashboard_dir = _latest_dashboard_dir(Path(diagnostics_root))
    if dashboard_dir:
        dashboard_index = dashboard_dir / "index.html"
        if dashboard_index.exists():
            print(f"Dashboard: {dashboard_index.resolve().as_uri()}")
        else:
            print(f"Dashboard folder: {dashboard_dir.resolve().as_uri()}")


# ---------------------------------------------------------------------------
# Convenience entry point — run by economy code only
# ---------------------------------------------------------------------------


def run_for_economy(
    economy: str,
    scenario: str | None = None,
    base_year: int | None = None,
    final_year: int | None = None,
    enable_visualisations: bool | None = None,
    output_root: str | Path | None = None,
    future_sales_shares: pd.DataFrame | None = None,
    auto_load_future_sales_shares: bool | None = None,
    workflow_config_path: str | Path | None = None,
    **config_overrides: Any,
) -> dict[str, Any]:
    """
    Run the full road model for one economy with all defaults applied.

    This is the minimal entry point — only the economy code is required.
    All data files are resolved from environment variables or sibling-repo
    conventions (see adapters/esto_inputs.py).

    Args:
        economy:               Canonical economy code, e.g. '20_USA'.
        scenario:              Macro scenario label. Defaults to workflow_defaults.yaml.
        base_year:             Base year. Defaults to workflow_defaults.yaml.
        final_year:            Final projection year. Defaults to workflow_defaults.yaml.
        enable_visualisations: Write PNG/HTML diagnostics. Defaults to workflow_defaults.yaml.
        output_root:           Override CSV output directory.
        future_sales_shares:   Optional LEAP-format future sales-share table
                               (Branch Path / Variable / Scenario / Region + year cols).
        auto_load_future_sales_shares:
                               If True and future_sales_shares is None, attempt to
                               auto-discover a future sales-share input file. Defaults
                               to workflow_defaults.yaml.
        workflow_config_path:  Optional YAML file with workflow defaults.
        **config_overrides:    Any RoadWorkflowConfig field overrides.

    Returns:
        outputs dict as returned by run_with_config().

    Example::

        from road_workflow import run_for_economy
        outputs = run_for_economy("20_USA")
        t11 = outputs["T11"]  # LEAP-ready table
    """
    from adapters.esto_inputs import load_population, load_gdp, load_esto_road_energy, load_esto_fuel_totals

    workflow_defaults = load_workflow_defaults(workflow_config_path)
    scenario = str(scenario or _workflow_defaults_value(workflow_defaults, "scenario", "Target"))
    base_year = int(base_year if base_year is not None else _workflow_defaults_value(workflow_defaults, "base_year", 2022))
    final_year = int(final_year if final_year is not None else _workflow_defaults_value(workflow_defaults, "final_year", 2060))
    enable_visualisations = bool(
        enable_visualisations
        if enable_visualisations is not None
        else _workflow_defaults_value(workflow_defaults, "enable_visualisations", True)
    )
    auto_load_future_sales_shares = bool(
        auto_load_future_sales_shares
        if auto_load_future_sales_shares is not None
        else _workflow_defaults_value(workflow_defaults, "auto_load_future_sales_shares", True)
    )

    population = load_population(economy, scenario=scenario)
    gdp = load_gdp(economy, scenario=scenario)
    esto_road_energy = load_esto_road_energy(economy)
    esto_fuel_totals = load_esto_fuel_totals(economy, base_year=base_year)

    projection_years = list(range(base_year, final_year + 1))
    _validate_macro_inputs(population, gdp, esto_road_energy, projection_years)

    _repo_root = Path(__file__).resolve().parents[1]  # leap_road_model/
    _output_root = Path(output_root) if output_root else _repo_root / "results" / economy

    yaml_config_overrides = _workflow_defaults_to_config_overrides(workflow_defaults)
    if "module1_defaults_dir" in yaml_config_overrides:
        yaml_config_overrides["module1_defaults_dir"] = _resolve_repo_relative_path(
            yaml_config_overrides["module1_defaults_dir"]
        )

    config_kwargs = {"module1_defaults_dir": _repo_root / "input_data" / "module1_defaults"}
    config_kwargs.update(yaml_config_overrides)
    config_kwargs.update({
        "economy": economy,
        "scenarios": [scenario],
        "base_year": base_year,
        "final_year": final_year,
        "enable_visualisations": enable_visualisations,
        "config_dir": _repo_root / "codebase" / "config",
        "output_root": _output_root,
        "diagnostics_root": _output_root / "diagnostics" if enable_visualisations else None,
    })
    config_kwargs.update(config_overrides)
    if "module1_defaults_dir" in config_kwargs:
        config_kwargs["module1_defaults_dir"] = _resolve_repo_relative_path(config_kwargs["module1_defaults_dir"])
    config = RoadWorkflowConfig(**config_kwargs)

    auto_source: Path | None = None
    if future_sales_shares is None and auto_load_future_sales_shares:
        future_sales_shares, auto_source = _autodiscover_future_sales_shares(
            repo_root=_repo_root,
            economy=economy,
            base_year=base_year,
            scenario=scenario,
        )

    if auto_source is not None:
        print(f"[road_workflow] Auto-loaded future sales shares from: {auto_source}")
    elif future_sales_shares is None and auto_load_future_sales_shares:
        print(
            "[road_workflow] No external future sales-share file auto-discovered; "
            "Module 5 will use projected Module 1 Sales Share rows if present, "
            "otherwise base-year fallback trajectories. Set ROAD_MODEL_FUTURE_SALES_SHARES_PATH "
            "to provide a file explicitly."
        )

    inputs = RoadWorkflowInputs(
        population=population,
        gdp=gdp,
        esto_road_energy_pj=esto_road_energy,
        future_sales_shares=future_sales_shares,
        esto_fuel_totals=esto_fuel_totals,
    )
    return run_with_config(config, inputs)


def _is_jupyter() -> bool:
    try:
        return bool(get_ipython())  # type: ignore[name-defined]  # noqa: F821
    except NameError:
        return False


if __name__ == "__main__" and not _is_jupyter():
    import argparse

    parser = argparse.ArgumentParser(
        description="Run the road model workflow for a single economy.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python road_workflow.py 20_USA
  python road_workflow.py 12_NZ --scenario Reference
  python road_workflow.py 12_NZ --no-vis
  python road_workflow.py 01_AUS --final-year 2050 --output results/test
        """,
    )
    parser.add_argument("economy", help="Economy code, e.g. 20_USA")
    parser.add_argument("--scenario", default=None, help="Macro scenario (default: workflow config)")
    parser.add_argument("--base-year", type=int, default=None, help="Base year (default: workflow config)")
    parser.add_argument("--final-year", type=int, default=None, help="Final projection year (default: workflow config)")
    parser.set_defaults(enable_visualisations=None)
    parser.add_argument("--vis", action="store_true", dest="enable_visualisations",
                        help="Write PNG/HTML diagnostic outputs")
    parser.add_argument("--no-vis", action="store_false", dest="enable_visualisations",
                        help="Skip PNG/HTML diagnostic outputs")
    parser.add_argument("--output", default=None, dest="output_root",
                        help="Output directory (default: results/<economy>)")
    parser.add_argument("--workflow-config", default=None, dest="workflow_config_path",
                        help="Workflow defaults YAML (default: codebase/config/workflow_defaults.yaml)")
    parser.add_argument("--module1-defaults-dir", default=None, dest="module1_defaults_dir",
                        help="Module 1 defaults root directory (default: workflow config)")
    parser.add_argument("--module1-defaults-version", default=None, dest="module1_defaults_version",
                        help="Module 1 defaults version folder (default: workflow config)")
    parser.set_defaults(save_csv_outputs=None)
    parser.add_argument("--save-csv-outputs", action="store_true", dest="save_csv_outputs",
                        help="Write intermediate module CSV outputs")
    parser.add_argument("--no-save-csv-outputs", action="store_false", dest="save_csv_outputs",
                        help="Skip intermediate module CSV outputs")
    parser.set_defaults(show_progress=None)
    parser.add_argument("--progress", action="store_true", dest="show_progress",
                        help="Print workflow progress messages")
    parser.add_argument("--no-progress", action="store_false", dest="show_progress",
                        help="Suppress workflow progress messages")
    parser.set_defaults(auto_load_future_sales_shares=None)
    parser.add_argument("--auto-future-sales-shares", action="store_true", dest="auto_load_future_sales_shares",
                        help="Auto-discover future sales-share inputs")
    parser.add_argument("--no-auto-future-sales-shares", action="store_false", dest="auto_load_future_sales_shares",
                        help="Disable future sales-share auto-discovery")
    parser.set_defaults(write_leap_row_diagnostics=None)
    parser.add_argument("--leap-row-diagnostics", action="store_true", dest="write_leap_row_diagnostics",
                        help="Write LEAP row coverage diagnostics CSV with missing and not-needed rows")
    parser.add_argument("--no-leap-row-diagnostics", action="store_false", dest="write_leap_row_diagnostics",
                        help="Disable LEAP row coverage diagnostics CSV")
    parser.add_argument("--module6-match-tolerance", type=float, default=None, dest="module6_match_tolerance",
                        help="Module 6 fuel match tolerance fraction (default: workflow config)")
    parser.set_defaults(leap_import_export_values_in_raw_units=None)
    parser.add_argument("--leap-import-raw-values", action="store_true", dest="leap_import_export_values_in_raw_units",
                        help="Write raw-unit values to the LEAP import workbook and clear numeric scale labels")
    parser.add_argument("--leap-import-scaled-values", action="store_false", dest="leap_import_export_values_in_raw_units",
                        help="Write values using LEAP Scale labels in the LEAP import workbook")
    for module_num in range(2, 8):
        parser.set_defaults(**{f"run_m{module_num}": None})
        parser.add_argument(f"--run-m{module_num}", action="store_true", dest=f"run_m{module_num}",
                            help=f"Run Module {module_num}")
        parser.add_argument(f"--skip-m{module_num}", action="store_false", dest=f"run_m{module_num}",
                            help=f"Skip Module {module_num}")
    args = parser.parse_args()

    cli_config_overrides = {
        k: v for k, v in {
            "module1_defaults_dir": args.module1_defaults_dir,
            "module1_defaults_version": args.module1_defaults_version,
            "save_csv_outputs": args.save_csv_outputs,
            "show_progress": args.show_progress,
            "write_leap_row_diagnostics": args.write_leap_row_diagnostics,
            "module6_match_tolerance": args.module6_match_tolerance,
            "leap_import_export_values_in_raw_units": args.leap_import_export_values_in_raw_units,
            **{f"run_m{module_num}": getattr(args, f"run_m{module_num}") for module_num in range(2, 8)},
        }.items()
        if v is not None
    }

    result = run_for_economy(
        economy=args.economy,
        scenario=args.scenario,
        base_year=args.base_year,
        final_year=args.final_year,
        enable_visualisations=args.enable_visualisations,
        output_root=args.output_root,
        auto_load_future_sales_shares=args.auto_load_future_sales_shares,
        workflow_config_path=args.workflow_config_path,
        **cli_config_overrides,
    )
    timings = result.get("timings", {})
    total = sum(v for v in timings.values())
    print(f"\nDone — {args.economy}  ({total:.1f}s)")
    for k, v in timings.items():
        print(f"  {k:<30} {v:.2f}s")
    _print_dashboard_link(result)


#%%
# ============================================================
# Run — execute this cell after setting ECONOMY above
# ============================================================

if _is_jupyter():
    outputs = run_for_economy(ECONOMY, scenario=SCENARIO, enable_visualisations=ENABLE_VIS)
    _print_dashboard_link(outputs)
#%%
