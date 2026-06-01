"""
ESTO and macro data adapter for the road model workflow.

Loads the external data that run_for_economy() needs:
  - Population + GDP from leap_transport/data/9th_macro_data.csv
  - ESTO road energy totals (Module 3 calibration)
  - ESTO base-year road fuel totals (Module 6 reconciliation)

Fuel name mappings are read from leap_road_model/config/leap_mappings*.xlsx
(the most recently dated file is used automatically):
  - fuel_product_final_proposed  : ESTO product string  → LEAP fuel name
  - fuel_ninth_final_proposed    : 9th-edition fuel code → LEAP fuel name

Data file locations are resolved in priority order:
  1. Explicit argument
  2. Environment variable  (ROAD_MODEL_ESTO_CSV / ROAD_MODEL_MACRO_CSV / ROAD_MODEL_FUEL_MAPPINGS)
  3. Default convention    (leap_road_model/config/ for mappings; sibling leap_transport/data/ for data)
"""

from __future__ import annotations

import glob
import logging
import os
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------

_REPO_ROOT      = Path(__file__).resolve().parents[2]   # leap_road_model/
_LEAP_TRANSPORT = _REPO_ROOT.parent / "leap_transport"

_DEFAULT_ESTO_CSV  = _LEAP_TRANSPORT / "data" / "00APEC_2024_low_with_subtotals.csv"
_DEFAULT_MACRO_CSV = _LEAP_TRANSPORT / "data" / "9th_macro_data.csv"

# Glob for dated leap_mappings xlsx files in leap_road_model/config/.
# Alphabetic sort of "leap_mappings DDMMYYYY.xlsx" gives the newest last.
_LEAP_MAPPINGS_GLOB = str(_REPO_ROOT / "config" / "leap_mappings*.xlsx")


def _resolve_path(explicit: str | Path | None, env_var: str, default: Path) -> Path:
    if explicit is not None:
        return Path(explicit)
    env = os.getenv(env_var)
    if env:
        return Path(env)
    return default


def _find_leap_mappings_xlsx(mappings_path: str | Path | None = None) -> Path:
    """Return path to the leap_mappings xlsx. Raises FileNotFoundError if not found."""
    if mappings_path is not None:
        p = Path(mappings_path)
        if p.exists():
            return p
        raise FileNotFoundError(f"leap_mappings xlsx not found at explicit path: {p}")
    env = os.getenv("ROAD_MODEL_FUEL_MAPPINGS")
    if env:
        p = Path(env)
        if p.exists():
            return p
        raise FileNotFoundError(f"ROAD_MODEL_FUEL_MAPPINGS points to missing file: {p}")
    hits = sorted(glob.glob(_LEAP_MAPPINGS_GLOB))
    if not hits:
        raise FileNotFoundError(
            f"No leap_mappings*.xlsx found in {_REPO_ROOT / 'config'}. "
            "Copy the file there or set ROAD_MODEL_FUEL_MAPPINGS."
        )
    return Path(hits[-1])  # alphabetically newest = latest date


# ---------------------------------------------------------------------------
# Fuel mapping loading
# ---------------------------------------------------------------------------

def load_esto_fuel_mapping(mappings_path: str | Path | None = None) -> dict[str, str]:
    """
    Return {esto_product_string: leap_fuel_name} for road-relevant fuels.

    Reads fuel_product_final_proposed from leap_mappings xlsx.
    Duplicate esto_product rows (e.g. "17 Electricity" appears twice) are resolved
    by preferring high-confidence entries; ties keep the first occurrence.

    Example output:
        {"07.01 Motor gasoline": "Motor gasoline",
         "07.07 Gas/diesel oil": "Gas and diesel oil",
         "17 Electricity":       "Electricity", ...}
    """
    xlsx_path = _find_leap_mappings_xlsx(mappings_path)
    log.info("Loading ESTO fuel mapping from %s", xlsx_path)
    df = pd.read_excel(xlsx_path, sheet_name="fuel_product_final_proposed")
    df = df[["esto_product", "leap_fuel_name", "fuel_confidence"]].dropna(subset=["esto_product", "leap_fuel_name"])
    # Sort by confidence then by row position (file order as tiebreaker) and keep first per product.
    confidence_order = {"high": 0, "medium": 1, "low": 2}
    df = df.copy()
    df["_conf_rank"] = df["fuel_confidence"].map(confidence_order).fillna(9)
    df["_row"]       = range(len(df))
    df = df.sort_values(["_conf_rank", "_row"]).drop_duplicates("esto_product", keep="first")
    mapping = dict(zip(df["esto_product"], df["leap_fuel_name"]))
    log.info("Loaded %d ESTO -> fuel mappings", len(mapping))
    return mapping


def load_ninth_fuel_mapping(mappings_path: str | Path | None = None) -> dict[str, str]:
    """
    Return {ninth_edition_fuel_code: leap_fuel_name}.

    Reads fuel_ninth_final_proposed from leap_mappings xlsx.
    Use this when consuming 9th-edition model outputs directly.

    Example output:
        {"07_01_motor_gasoline": "Motor gasoline",
         "17_electricity":       "Electricity", ...}
    """
    xlsx_path = _find_leap_mappings_xlsx(mappings_path)
    log.info("Loading 9th-edition fuel mapping from %s", xlsx_path)
    df = pd.read_excel(xlsx_path, sheet_name="fuel_ninth_final_proposed")
    df = df[["ninth_fuel", "leap_fuel_name", "fuel_confidence"]].dropna(subset=["ninth_fuel", "leap_fuel_name"])
    confidence_order = {"high": 0, "medium": 1, "low": 2}
    df = df.copy()
    df["_conf_rank"] = df["fuel_confidence"].map(confidence_order).fillna(9)
    df["_row"]       = range(len(df))
    df = df.sort_values(["_conf_rank", "_row"]).drop_duplicates("ninth_fuel", keep="first")
    mapping = dict(zip(df["ninth_fuel"], df["leap_fuel_name"]))
    log.info("Loaded %d 9th-edition -> fuel mappings", len(mapping))
    return mapping


# ---------------------------------------------------------------------------
# Macro data
# ---------------------------------------------------------------------------

def load_population(
    economy: str,
    macro_csv: str | Path | None = None,
    scenario: str = "Reference",
) -> pd.Series:
    """
    Population Series indexed by year (persons).

    9th_macro_data.csv Population column is in thousands; multiplied by 1 000.
    """
    csv = _resolve_path(macro_csv, "ROAD_MODEL_MACRO_CSV", _DEFAULT_MACRO_CSV)
    if not csv.exists():
        raise FileNotFoundError(f"Macro CSV not found: {csv}. Set ROAD_MODEL_MACRO_CSV.")
    df = pd.read_csv(csv)
    mask = (df["Economy"] == economy) & (df["Scenario"] == scenario)
    sub = df[mask].set_index("Date")["Population"].sort_index()
    if sub.empty:
        raise ValueError(f"No population data for economy='{economy}' scenario='{scenario}' in {csv}")
    return (sub * 1_000).rename("population")


def load_gdp(
    economy: str,
    macro_csv: str | Path | None = None,
    scenario: str = "Reference",
) -> pd.Series:
    """GDP Series indexed by year (billions USD, 2017 PPP)."""
    csv = _resolve_path(macro_csv, "ROAD_MODEL_MACRO_CSV", _DEFAULT_MACRO_CSV)
    if not csv.exists():
        raise FileNotFoundError(f"Macro CSV not found: {csv}. Set ROAD_MODEL_MACRO_CSV.")
    df = pd.read_csv(csv)
    mask = (df["Economy"] == economy) & (df["Scenario"] == scenario)
    sub = df[mask].set_index("Date")["Gdp"].sort_index()
    if sub.empty:
        raise ValueError(f"No GDP data for economy='{economy}' scenario='{scenario}' in {csv}")
    return sub.rename("gdp")


# ---------------------------------------------------------------------------
# ESTO data
# ---------------------------------------------------------------------------

# Default passenger share of total road energy when no transport-type split is available.
# APEC ESTO reports only aggregate road totals (flow "15.02 Road"); this split is applied
# to produce separate passenger / freight energy series for Module 3 calibration.
# TODO: replace with per-economy values from transport_data_system combined_data once
# that pipeline produces passenger/freight splits for all APEC economies.
_DEFAULT_PAX_SHARE = 0.73


def _esto_economy_code(economy: str) -> str:
    """Convert canonical economy code (e.g. '20_USA') to ESTO code ('20USA')."""
    return economy.replace("_", "")


def load_esto_road_energy(
    economy: str,
    esto_csv: str | Path | None = None,
    pax_share: float | None = None,
) -> pd.DataFrame:
    """
    Historical road energy by transport type for Module 3 calibration.

    APEC ESTO has no passenger/freight road split, so pax_share is applied to
    the "15.02 Road / 19 Total" rows across all historical years.

    Returns DataFrame with columns [year, transport_type, energy_pj].
    """
    csv = _resolve_path(esto_csv, "ROAD_MODEL_ESTO_CSV", _DEFAULT_ESTO_CSV)
    if not csv.exists():
        raise FileNotFoundError(f"ESTO CSV not found: {csv}. Set ROAD_MODEL_ESTO_CSV.")

    econ_esto = _esto_economy_code(economy)
    if pax_share is None:
        pax_share = _DEFAULT_PAX_SHARE
        log.warning(
            "No passenger/freight energy split provided for %s; "
            "using default %.0f%% / %.0f%% approximation.",
            economy, pax_share * 100, (1 - pax_share) * 100,
        )

    df = pd.read_csv(csv, low_memory=False)
    year_cols = sorted([c for c in df.columns if c.isdigit() and int(c) <= 2022], key=int)

    road_total = df[
        (df["economy"] == econ_esto)
        & (df["flows"] == "15.02 Road")
        & (df["products"] == "19 Total")
    ]
    if road_total.empty:
        raise ValueError(f"No '15.02 Road / 19 Total' rows for {econ_esto} in {csv}")

    melted = road_total.melt(
        id_vars=["economy"],
        value_vars=year_cols,
        var_name="year",
        value_name="total_pj",
    )
    melted["year"] = melted["year"].astype(int)
    melted["total_pj"] = pd.to_numeric(melted["total_pj"], errors="coerce").fillna(0)

    rows = []
    for _, r in melted.iterrows():
        rows.append({"year": r["year"], "transport_type": "passenger", "energy_pj": r["total_pj"] * pax_share})
        rows.append({"year": r["year"], "transport_type": "freight",   "energy_pj": r["total_pj"] * (1 - pax_share)})
    return pd.DataFrame(rows)


def load_esto_fuel_totals(
    economy: str,
    base_year: int = 2022,
    esto_csv: str | Path | None = None,
    mappings_path: str | Path | None = None,
) -> pd.DataFrame:
    """
    Base-year road fuel totals for Module 6 reconciliation.

    Returns DataFrame with columns [fuel, energy_pj] using LEAP canonical fuel
    names from fuel_product_final_proposed in leap_mappings xlsx.
    """
    csv = _resolve_path(esto_csv, "ROAD_MODEL_ESTO_CSV", _DEFAULT_ESTO_CSV)
    if not csv.exists():
        raise FileNotFoundError(f"ESTO CSV not found: {csv}. Set ROAD_MODEL_ESTO_CSV.")

    econ_esto = _esto_economy_code(economy)
    fuel_map = load_esto_fuel_mapping(mappings_path)
    year_col = str(base_year)

    df = pd.read_csv(csv, low_memory=False)
    if year_col not in df.columns:
        raise ValueError(f"Year column '{year_col}' not found in {csv}")

    road = df[
        (df["economy"] == econ_esto)
        & (df["flows"] == "15.02 Road")
        & (~df["is_subtotal"])
    ][["products", year_col]].copy()

    road["fuel"] = road["products"].map(fuel_map)
    road = road.dropna(subset=["fuel"])
    road["energy_pj"] = pd.to_numeric(road[year_col], errors="coerce").fillna(0)
    road = road[road["energy_pj"] > 0][["fuel", "energy_pj"]]

    result = road.groupby("fuel", as_index=False)["energy_pj"].sum()
    log.info("ESTO fuel totals for %s base year %d: %d fuel rows", economy, base_year, len(result))
    return result
