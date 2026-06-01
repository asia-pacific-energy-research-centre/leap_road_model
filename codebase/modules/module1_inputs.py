"""
Module 1 — Road input data and defaults system.

Responsibilities:
- Collect researcher-provided inputs (from CSV or Fabian's tool output).
- Load default assumptions from config/model_defaults.yaml.
- Merge researcher inputs with defaults, applying the fallback hierarchy.
- Flag which values came from researchers and which came from defaults.
- Standardise economy, scenario, year, vehicle type, drive, and fuel labels.
- Check units and missing values.
- Produce a clean merged input table (T3) for Module 2.

Outputs: T3_merged_inputs DataFrame.

Note: Connection to Fabian's researcher input tool is a future enhancement.
      For now, researcher inputs are read from a structured CSV (see below).
"""

from __future__ import annotations

import logging
import yaml
from pathlib import Path

import pandas as pd

from diagnostics.module_charts import write_module1_charts
from schemas.validation import validate_table

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_module1(
    researcher_input_path: str | Path | None,
    config_dir: str | Path = "config",
    economies: list[str] | None = None,
    scenarios: list[str] | None = None,
    diagnostics_dir: str | Path | None = None,
) -> pd.DataFrame:
    """
    Run Module 1: load and merge inputs and defaults.

    Args:
        researcher_input_path: Path to researcher input CSV (T1 schema), or None
            to use defaults only.
        config_dir: Directory containing model_defaults.yaml and other configs.
        economies: Optional list of economy codes to process. None = all.
        scenarios: Optional list of scenario labels. None = all.
        diagnostics_dir: Optional directory root for Module 1 PNG diagnostic
            charts. When provided, charts are written to
            diagnostics_dir/module1/.

    Returns:
        T3_merged_inputs DataFrame ready for Module 2.
    """
    config_dir = Path(config_dir)

    defaults_df = _load_defaults(config_dir)
    log.info("Loaded %d default assumption rows", len(defaults_df))

    if researcher_input_path is not None:
        researcher_df = load_researcher_inputs(researcher_input_path)
        log.info("Loaded %d researcher input rows", len(researcher_df))
    else:
        researcher_df = pd.DataFrame(columns=_T1_COLUMNS)
        log.info("No researcher input file provided — using defaults only")

    merged = _merge_inputs_with_defaults(researcher_df, defaults_df, economies, scenarios)
    log.info("Merged table has %d rows", len(merged))

    errors = validate_table(merged, "T3_merged_inputs")
    for err in errors:
        log.warning("Validation: %s", err)

    if diagnostics_dir is not None:
        try:
            written = write_module1_charts(merged, diagnostics_dir)
            log.info("Module 1 diagnostics: wrote %d chart(s)", len(written))
        except Exception as exc:
            log.warning("Module 1 diagnostics chart generation failed: %s", exc)

    return merged


def load_researcher_inputs(path: str | Path) -> pd.DataFrame:
    """
    Load a researcher input CSV in T1 schema format.

    Expected columns: economy, scenario, year, transport_type, vehicle_type,
    drive_type, variable, value, unit, source_flag, comment (optional).

    Args:
        path: Path to the CSV file.

    Returns:
        T1_researcher_inputs DataFrame.
    """
    df = pd.read_csv(path, dtype={"year": int})
    df["source_flag"] = "researcher"
    errors = validate_table(df, "T1_researcher_inputs")
    for err in errors:
        log.warning("Researcher input validation: %s", err)
    return df


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_T1_COLUMNS = [
    "economy", "scenario", "year", "transport_type", "vehicle_type",
    "drive_type", "variable", "value", "unit", "source_flag", "comment",
]


def _load_defaults(config_dir: Path) -> pd.DataFrame:
    """
    Build a T2 defaults table from model_defaults.yaml.

    Returns:
        T2_defaults DataFrame.
    """
    with open(config_dir / "model_defaults.yaml") as f:
        cfg = yaml.safe_load(f)

    rows = []

    # Mileage defaults
    for vt, drives in cfg.get("default_mileage_km_per_year", {}).items():
        for drive, value in drives.items():
            rows.append({
                "scope": "global", "variable": "mileage",
                "vehicle_type": vt, "drive_type": drive,
                "value": value, "unit": "km/vehicle/year",
                "source": "multinode_energy_balance road_module1_defaults",
                "version": "v2026_05_25",
                "review_recommended": True,
            })

    # Efficiency defaults
    for vt, drives in cfg.get("default_efficiency_km_per_gj", {}).items():
        for drive, value in drives.items():
            rows.append({
                "scope": "global", "variable": "efficiency",
                "vehicle_type": vt, "drive_type": drive,
                "value": value, "unit": "km/GJ",
                "source": "multinode_energy_balance road_module1_defaults",
                "version": "v2026_05_25",
                "review_recommended": True,
            })

    # PHEV utilisation rate
    rows.append({
        "scope": "global", "variable": "phev_electric_utilisation_rate",
        "vehicle_type": "all", "drive_type": "PHEV",
        "value": cfg["phev"]["default_electric_utilisation_rate"],
        "unit": "fraction",
        "source": "model_defaults.yaml (see Human Review Question D1)",
        "version": "v2026_05_25",
        "review_recommended": True,
    })

    return pd.DataFrame(rows)


def _merge_inputs_with_defaults(
    researcher_df: pd.DataFrame,
    defaults_df: pd.DataFrame,
    economies: list[str] | None,
    scenarios: list[str] | None,
) -> pd.DataFrame:
    """
    Merge researcher inputs with defaults.
    Researcher inputs take priority; defaults fill gaps.

    Returns:
        T3_merged_inputs DataFrame.
    """
    # TODO: implement full merge logic
    # For now, return researcher inputs with is_default=False,
    # plus defaults for any missing (economy, vehicle_type, drive_type, variable) combos.
    raise NotImplementedError(
        "Module 1 merge logic not yet implemented. "
        "Implement after Human Review Questions are answered (especially E1)."
    )
