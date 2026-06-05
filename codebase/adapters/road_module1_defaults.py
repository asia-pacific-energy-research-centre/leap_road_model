"""
Adapter — road_model_inputs_interface default inputs loader.

Loads Module 1 CSV packages produced by road_model_inputs_interface and returns
a long-format DataFrame.

Supported package formats:
1. Canonical long CSV:
    Economy, Scenario, Branch Path, Variable, Year, Value, Units, ...
2. Legacy LEAP workbook style:
    Branch Path, Variable, Scenario, Region, Scale, Units, Per...,
    2022, [2030, 2040, 2050, ...], input_source, ..., default_version,
    researcher_review_recommended, review_reason

Economy folder names use no-underscore format (e.g. '12NZ').
Economy codes are converted to canonical '12_NZ' format on load.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

# Default file name within each economy folder.
# Current generator usually writes economy-suffixed files:
#   road_module1_default_filled_inputs_<ECONOMY>.csv
# while older/legacy paths may still use the unsuffixed name.
_DEFAULT_FILE = "road_module1_default_filled_inputs.csv"
_DEFAULT_FILE_PREFIX = "road_module1_default_filled_inputs_"
_VALUES_FILE_PREFIX = "road_module1_values_"

_PASSENGER_VEHICLE_TYPES = ("LPVs", "Motorcycles", "Buses")
_FREIGHT_VEHICLE_TYPES = ("Trucks", "LCVs")
_VEHICLE_TYPE_STOCK_SHARE_BRANCHES = {
    "Demand\\Passenger road\\LPVs": ("passenger", "LPVs"),
    "Demand\\Passenger road\\Motorcycles": ("passenger", "Motorcycles"),
    "Demand\\Passenger road\\Buses": ("passenger", "Buses"),
    "Demand\\Freight road\\Trucks": ("freight", "Trucks"),
    "Demand\\Freight road\\LCVs": ("freight", "LCVs"),
}

# Default reconciliation split used when Module 1 provides only aggregate
# reconciliation_weight values.
_DEFAULT_RECONCILIATION_WEIGHTS = {
    "stock": 0.50,
    "mileage": 0.25,
    "efficiency": 0.25,
}

# Year columns present in the wide format
_YEAR_COLS = ["2022", "2030", "2040", "2050"]

_WIDE_ID_COLS = ["Branch Path", "Variable", "Scenario", "Region", "Scale", "Units", "Per..."]
_LONG_REQUIRED_COLS = {"Branch Path", "Variable", "Year", "Value"}
_LONG_COLUMN_ALIASES = {
    "Economy": ["Economy", "economy", "Region", "region"],
    "Scenario": ["Scenario", "scenario"],
    "Branch Path": ["Branch Path", "branch_path", "leap_branch_path"],
    "Variable": ["Variable", "variable"],
    "Year": ["Year", "year"],
    "Value": ["Value", "value"],
    "Units": ["Units", "Unit", "unit"],
    "Source": ["Source", "source", "source_name"],
    "Comment": ["Comment", "comment", "notes", "review_reason"],
    "Input Status": ["Input Status", "input_status", "input_source"],
    "Source Method": ["Source Method", "source_method", "source_type"],
    "Original Value": ["Original Value", "original_value"],
    "Validation Message": ["Validation Message", "validation_message"],
    "Last Updated": ["Last Updated", "last_updated", "source_date"],
    "Version": ["Version", "version", "default_version"],
    "Scale": ["Scale", "scale"],
    "Per...": ["Per...", "Per", "per", "per_unit"],
}

# Map multinode Variable names → T2 variable names where they differ
_VARIABLE_MAP = {
    "Fuel Economy":                "efficiency",
    "Final On-Road Fuel Economy":   "efficiency",
    "Mileage":                      "mileage",
    "Stock":                        "stock",
    "Sales Share":                  "sales_share",
    "Vehicle Equivalent Weight":    "vehicle_equivalent_weight",
    "Vehicle Equivalent Weight Lower Bound": "vehicle_equivalent_weight_lower_bound",
    "Vehicle Equivalent Weight Upper Bound": "vehicle_equivalent_weight_upper_bound",
    "Passenger Saturation":         "saturation_level",
    "Passenger Vehicle Saturation": "saturation_level",
    "Passenger Saturation Reached": "passenger_saturation_reached",
    "PHEV Electric Driving Share":  "phev_electric_utilisation_rate",
    "PHEV Electric Utilisation Rate": "phev_electric_utilisation_rate",
    "PHEV Electric Utilization Rate": "phev_electric_utilisation_rate",
    "Survival Rate":                "survival_rate",
    "Vintage Profile Share":        "vintage_share",
    "Reconciliation Bound Lower":   "reconciliation_bound_lower",
    "Reconciliation Bound Upper":   "reconciliation_bound_upper",
    "Reconciliation Weight":        "reconciliation_weight",
}

# Unit conversions: multinode uses MJ/100km; model uses km/GJ
# km/GJ = 10_000 / (MJ/100km)
_EFFICIENCY_UNIT = "MJ/100 km"

_PROFILE_PREFIXES = ("Age Profile", "Vintage Profile")

# Base drive-type scope used by the road model. LEAP branch labels append size
# later for sized buckets, e.g. Trucks/BEV/heavy -> "BEV heavy".
_VALID_BASE_DRIVES_BY_VEHICLE_TYPE = {
    "LPVs": {"ICE", "HEV", "EREV", "PHEV", "BEV", "FCEV"},
    "Motorcycles": {"ICE", "BEV", "FCEV"},
    "Buses": {"ICE", "BEV", "FCEV"},
    "Trucks": {"ICE", "BEV", "FCEV"},
    "LCVs": {"ICE", "PHEV", "BEV", "FCEV"},
}


def _split_profile_branch_path(branch_path: str) -> tuple[str, int | None, str]:
    """
    Return (profile_kind, profile_index, rest_of_path) for profile-prefixed paths.

    Canonical long Module 1 profile rows use:
        Age Profile\\<index>

    Legacy wide packages use paths such as Demand\\Passenger road\\Age 5.
    """
    path_text = str(branch_path or "")
    match = re.match(r"^(Age Profile|Vintage Profile)[\\/](\d+)(?:[\\/](.*))?$", path_text)
    if match:
        try:
            index = int(match.group(2))
        except ValueError:
            index = None
        return match.group(1), index, match.group(3) or ""
    return "", None, path_text


def _extract_profile_age(branch_path: str) -> int | None:
    """Extract profile age from canonical prefix or legacy Age N branch paths."""
    _, profile_index, _ = _split_profile_branch_path(branch_path)
    if profile_index is not None:
        return profile_index
    match = re.search(r"Age\s+(\d+)", str(branch_path or ""))
    return int(match.group(1)) if match else None


def _folder_to_economy_code(folder_name: str) -> str:
    """
    Convert multinode economy folder name (e.g. '12NZ') to canonical code ('12_NZ').

    Handles the multinode convention of omitting the underscore after the
    two-digit economy number. Leaves already-canonical codes unchanged.
    """
    if "_" in folder_name:
        return folder_name
    match = re.match(r"^(\d{2})([A-Z].*)$", folder_name)
    if match:
        return f"{match.group(1)}_{match.group(2)}"
    return folder_name


def _infer_economy_from_filename(path: Path) -> str | None:
    """Infer an economy code from Module 1 package filenames."""
    stem = path.stem
    for prefix in (_VALUES_FILE_PREFIX, _DEFAULT_FILE_PREFIX):
        if not stem.startswith(prefix):
            continue
        remainder = stem[len(prefix):]
        match = re.match(r"^(\d{2}_?[A-Z]+)", remainder)
        if match:
            return _folder_to_economy_code(match.group(1))
    return None


def _has_module1_csvs(folder: Path) -> bool:
    """True when a folder directly contains Module 1 package CSV files."""
    return any(folder.glob(f"{_VALUES_FILE_PREFIX}*.csv")) or any(folder.glob(f"{_DEFAULT_FILE_PREFIX}*.csv"))


def _resolve_package_root(defaults_dir: Path, version: str | None) -> Path:
    """
    Resolve the Module 1 package root.

    Supports both current versioned packages and the planned stable package
    layout where CSVs may live directly under module1_defaults.
    """
    if version is not None:
        version_dir = defaults_dir / version
        if version_dir.exists():
            return version_dir
        if _has_module1_csvs(defaults_dir):
            log.info("Version %s not found; using flat Module 1 package root %s", version, defaults_dir)
            return defaults_dir
        raise FileNotFoundError(f"Version folder not found: {version_dir}")

    if _has_module1_csvs(defaults_dir):
        return defaults_dir

    candidates = [p for p in defaults_dir.iterdir() if p.is_dir()]
    if not candidates:
        raise FileNotFoundError(f"No Module 1 package folders or CSVs in {defaults_dir}")
    version_dir = max(candidates, key=lambda p: p.stat().st_mtime)
    log.info("Using most recent Module 1 package folder: %s", version_dir.name)
    return version_dir


def _iter_package_csvs(package_root: Path, economy_filter: list[str] | None = None) -> list[tuple[str, Path]]:
    """
    Return (economy_code, csv_path) pairs for versioned, economy-folder, or flat packages.
    """
    pairs: list[tuple[str, Path]] = []
    seen_paths: set[Path] = set()

    for econ_dir in sorted([p for p in package_root.iterdir() if p.is_dir()]):
        economy_code = _folder_to_economy_code(econ_dir.name)
        if economy_filter is not None and economy_code not in economy_filter:
            continue
        csv_path = _find_default_inputs_csv(econ_dir, economy_code)
        if csv_path is not None:
            pairs.append((economy_code, csv_path))
            seen_paths.add(csv_path.resolve())

    direct_files = sorted(
        [
            *package_root.glob(f"{_VALUES_FILE_PREFIX}*.csv"),
            *package_root.glob(f"{_DEFAULT_FILE_PREFIX}*.csv"),
        ],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for csv_path in direct_files:
        if csv_path.resolve() in seen_paths:
            continue
        economy_code = _infer_economy_from_filename(csv_path)
        if economy_code is None and economy_filter and len(economy_filter) == 1:
            economy_code = economy_filter[0]
        if economy_code is None:
            log.warning("Could not infer economy code from Module 1 file name: %s", csv_path.name)
            continue
        if economy_filter is not None and economy_code not in economy_filter:
            continue
        pairs.append((economy_code, csv_path))
        seen_paths.add(csv_path.resolve())

    return pairs


def _normalise_variable_name(variable_raw: str, branch_path: str) -> str:
    """Normalise Module 1 variable names and infer component pseudo-branch variables."""
    variable = _VARIABLE_MAP.get(variable_raw, variable_raw.lower().replace("-", " ").replace("/", " ").replace(" ", "_"))
    path_lower = str(branch_path or "").replace("\\", "/").lower()

    if variable in {"reconciliation_weight", "reconciliation_bound_lower", "reconciliation_bound_upper"}:
        component_map = {
            "stock": "stock",
            "mileage": "mileage",
            "fuel economy": "efficiency",
            "efficiency": "efficiency",
        }
        for token, component in component_map.items():
            if token in path_lower:
                return f"{variable}_{component}"

    return variable


def _parse_branch_path(branch_path: str) -> dict[str, str | None]:
    """
    Extract vehicle_type, drive_type, size, and fuel from a LEAP branch path.

    Handles up to 5 levels: Demand / transport_road / vehicle_type / technology / fuel

    Returns dict with keys: transport_type, vehicle_type, technology, size, fuel
    """
    _, _, path_for_parse = _split_profile_branch_path(branch_path)
    parts = path_for_parse.split("\\")
    result: dict[str, str | None] = {
        "transport_type": None,
        "vehicle_type":   None,
        "technology":     None,   # e.g. "ICE medium", "BEV large"
        "drive_type":     None,   # e.g. "ICE", "BEV"
        "size":           None,   # e.g. "medium", "large", "heavy"
        "fuel":           None,
    }

    # Level 1: "Demand"
    # Level 2: "Passenger road" / "Freight road"
    if len(parts) >= 2:
        transport_raw = parts[1].lower()
        if "passenger" in transport_raw:
            result["transport_type"] = "passenger"
        elif "freight" in transport_raw:
            result["transport_type"] = "freight"

    # Level 3: vehicle type (LPVs, Buses, Motorcycles, Trucks, LCVs, PHEV aggregate…)
    if len(parts) >= 3:
        vt = parts[2]
        # Skip age rows ("Age 0", "Age 1", …) and size-label rows
        # ("Passenger cars", "SUV and light trucks", "Heavy trucks", "Medium trucks")
        known_buckets = {"LPVs", "Buses", "Motorcycles", "Trucks", "LCVs"}
        if vt in known_buckets:
            result["vehicle_type"] = vt
        elif vt in ("PHEV",):
            # Aggregate PHEV rows (e.g. PHEV Electric Driving Share at road level)
            result["vehicle_type"] = None
        else:
            result["vehicle_type"] = None   # size-label or age row; caller drops these

    # Level 4: technology label e.g. "ICE medium", "BEV large", "ICE", "BEV"
    if len(parts) >= 4 and result["vehicle_type"] is not None:
        tech = parts[3]
        result["technology"] = tech
        tokens = tech.split()
        if tokens:
            result["drive_type"] = tokens[0]   # ICE, BEV, PHEV, FCEV, HEV
            result["size"] = tokens[1] if len(tokens) > 1 else None

    # Level 5: fuel
    if len(parts) >= 5 and result["vehicle_type"] is not None:
        result["fuel"] = parts[4]

    return result


def _is_out_of_scope_model_branch(branch_path: str) -> bool:
    """True when a Module 1 branch uses a drive outside this model's scope."""
    parsed = _parse_branch_path(branch_path)
    vehicle_type = parsed["vehicle_type"]
    drive_type = parsed["drive_type"]
    if vehicle_type is None or drive_type is None:
        return False

    allowed_drives = _VALID_BASE_DRIVES_BY_VEHICLE_TYPE.get(vehicle_type)
    if allowed_drives is None:
        return False
    return drive_type not in allowed_drives


def _filter_out_of_scope_model_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Drop Module 1 rows whose branch drive is outside the current model scope."""
    if "Branch Path" not in df.columns or df.empty:
        return df

    out_of_scope = df["Branch Path"].astype(str).apply(_is_out_of_scope_model_branch)
    if out_of_scope.any():
        log.info("Dropped %d out-of-scope Module 1 branch row(s)", int(out_of_scope.sum()))
    return df.loc[~out_of_scope].copy()


def _find_default_inputs_csv(econ_dir: Path, economy_code: str) -> Path | None:
    """
    Resolve the default-filled inputs CSV inside one economy folder.

    Supports both naming conventions:
      - road_module1_values_<ECONOMY>_<VERSION>_<YYYYMMDD>.csv  (canonical)
      - road_module1_default_filled_inputs.csv                  (legacy)
      - road_module1_default_filled_inputs_<ECONOMY>.csv        (legacy)
    """
    economy_no_underscore = economy_code.replace("_", "")
    long_globs = [
        f"{_VALUES_FILE_PREFIX}{economy_no_underscore}_*.csv",
        f"{_VALUES_FILE_PREFIX}{economy_code}_*.csv",
        f"{_VALUES_FILE_PREFIX}*.csv",
    ]
    for pattern in long_globs:
        matches = sorted(econ_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        if matches:
            return matches[0]

    candidates = [
        econ_dir / _DEFAULT_FILE,
        econ_dir / f"{_DEFAULT_FILE_PREFIX}{econ_dir.name}.csv",
        econ_dir / f"{_DEFAULT_FILE_PREFIX}{economy_no_underscore}.csv",
        econ_dir / f"{_DEFAULT_FILE_PREFIX}{economy_code}.csv",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    globbed = sorted(econ_dir.glob(f"{_DEFAULT_FILE_PREFIX}*.csv"))
    if globbed:
        return globbed[0]
    return None


def _find_col(df: pd.DataFrame, canonical_name: str) -> str | None:
    """Return the actual column name matching a canonical Module 1 column."""
    aliases = _LONG_COLUMN_ALIASES.get(canonical_name, [canonical_name])
    lookup = {str(col).strip().lower(): col for col in df.columns}
    for alias in aliases:
        found = lookup.get(alias.strip().lower())
        if found is not None:
            return str(found)
    return None


def _looks_like_long_module1_csv(df: pd.DataFrame) -> bool:
    """True when a DataFrame uses the canonical long Module 1 shape."""
    return all(_find_col(df, col) is not None for col in _LONG_REQUIRED_COLS)


def _normalise_long_module1_df(
    df: pd.DataFrame,
    economy_code: str,
    version_name: str,
) -> pd.DataFrame:
    """Normalise canonical long Module 1 rows into local column names."""
    out = pd.DataFrame(index=df.index)
    for canonical in _LONG_COLUMN_ALIASES:
        source_col = _find_col(df, canonical)
        if source_col is not None:
            out[canonical] = df[source_col]

    out["Region"] = out.get("Economy", economy_code)
    out["Scenario"] = out.get("Scenario", "Reference")
    out["Scale"] = out.get("Scale", "")
    out["Units"] = out.get("Units", "")
    out["Per..."] = out.get("Per...", "")

    if "Source" in out.columns:
        out["source_name"] = out["Source"]
    else:
        out["source_name"] = "road_module1_values"

    if "Source Method" in out.columns:
        out["source_type"] = out["Source Method"]
    else:
        out["source_type"] = "module1_long_csv"

    if "Input Status" in out.columns:
        out["input_source"] = out["Input Status"]
    else:
        out["input_source"] = "provided"

    if "Comment" in out.columns:
        out["review_reason"] = out["Comment"]
        out["notes"] = out["Comment"]
    else:
        out["review_reason"] = ""
        out["notes"] = ""

    if "Version" in out.columns:
        out["default_version"] = out["Version"]
    else:
        out["default_version"] = version_name

    out["researcher_review_recommended"] = False

    keep = [
        "Branch Path", "Variable", "Scenario", "Region", "Scale", "Units", "Per...",
        "Year", "Value", "input_source", "source_type", "source_name", "source_scope",
        "source_date", "default_version", "researcher_review_recommended", "review_reason",
        "notes",
    ]
    return out[[col for col in keep if col in out.columns]].copy()


def _long_to_legacy_wide(long_df: pd.DataFrame) -> pd.DataFrame:
    """Convert canonical long Module 1 rows to the legacy wide reader shape."""
    long_df = long_df.copy()
    long_df["Year"] = pd.to_numeric(long_df["Year"], errors="coerce")
    long_df = long_df.dropna(subset=["Year"])
    long_df["Year"] = long_df["Year"].astype(int).astype(str)

    metadata_cols = [
        col for col in [
            *_WIDE_ID_COLS,
            "input_source", "source_type", "source_name", "source_scope",
            "source_date", "default_version", "researcher_review_recommended",
            "review_reason", "notes",
        ]
        if col in long_df.columns
    ]
    wide = (
        long_df.pivot_table(
            index=metadata_cols,
            columns="Year",
            values="Value",
            aggfunc="first",
            dropna=False,
        )
        .reset_index()
        .rename_axis(columns=None)
    )
    return wide


def _read_module1_csv_as_wide(
    csv_path: Path,
    economy_code: str,
    version_name: str,
) -> pd.DataFrame:
    """Read either canonical long or legacy wide Module 1 CSV as legacy wide."""
    df = pd.read_csv(csv_path, low_memory=False)
    if _looks_like_long_module1_csv(df):
        long_df = _normalise_long_module1_df(df, economy_code=economy_code, version_name=version_name)
        return _filter_out_of_scope_model_rows(_long_to_legacy_wide(long_df))
    return _filter_out_of_scope_model_rows(df)


def load_road_module1_defaults(
    defaults_dir: str | Path,
    version: str | None = None,
    economy_filter: list[str] | None = None,
    include_survival_curves: bool = True,
    include_reconciliation_params: bool = True,
) -> pd.DataFrame:
    """
    Load road module default inputs from multinode_energy_balance outputs.

    Scans `defaults_dir/{version}/{economy}/road_module1_default_filled_inputs.csv`
    for all available economies and returns a T2-compatible DataFrame.

    Args:
        defaults_dir: Path to `back-end/outputs/road_module1_defaults/`.
        version: Version folder name (e.g. 'v2026_05_25_best_guess').
            If None, uses the most recently modified version folder.
        economy_filter: Optional list of canonical economy codes to load
            (e.g. ['12_NZ', '01_AUS']). If None, loads all economies.
        include_survival_curves: If False, drop Survival Rate and Vintage
            Profile Share rows (useful when loading only scalar defaults).
        include_reconciliation_params: If False, drop reconciliation bound
            and weight rows.

    Returns:
        DataFrame with columns:
        [economy, version, scope, variable, transport_type, vehicle_type,
         drive_type, size, fuel, leap_branch_path, value_2022, unit,
         source, review_recommended, notes]

        Efficiency values are converted from MJ/100km → km/GJ.
    """
    defaults_dir = Path(defaults_dir)

    package_root = _resolve_package_root(defaults_dir, version)
    economy_csvs = _iter_package_csvs(package_root, economy_filter=economy_filter)
    log.info("Found %d Module 1 CSV file(s) in %s", len(economy_csvs), package_root)

    frames = []
    for economy_code, csv_path in economy_csvs:
        try:
            df = _load_single_economy(csv_path, economy_code, package_root.name)
            frames.append(df)
        except Exception as exc:
            log.warning("Failed to load %s: %s", economy_code, exc)

    if not frames:
        raise RuntimeError(f"No economy defaults could be loaded from {package_root}")

    result = pd.concat(frames, ignore_index=True)

    if not include_survival_curves:
        result = result[~result["variable"].isin(["survival_rate", "vintage_share"])].copy()

    if not include_reconciliation_params:
        excl_prefixes = ("reconciliation_bound_lower", "reconciliation_bound_upper", "reconciliation_weight")
        result = result[~result["variable"].astype(str).str.startswith(excl_prefixes)].copy()

    log.info("Loaded %d default rows across %d economies", len(result), result["economy"].nunique())
    return result


def _load_single_economy(
    csv_path: Path,
    economy_code: str,
    version_name: str,
) -> pd.DataFrame:
    """Load one economy's default CSV and parse into long format."""
    df = _read_module1_csv_as_wide(csv_path, economy_code=economy_code, version_name=version_name)

    # Filter to year 2022 (base year) — other years (2030, 2040, 2050) are projection
    # assumptions that go through Module 5's future-share logic, not the T2 defaults path.
    # Survival curves and vintage profiles use 2022 as age-0 anchor.
    if "2022" not in df.columns:
        log.warning("%s: no '2022' column found — skipping", csv_path)
        return pd.DataFrame()

    rows = []
    for _, row in df.iterrows():
        branch_path = str(row.get("Branch Path", ""))
        variable_raw = str(row.get("Variable", ""))
        variable = _normalise_variable_name(variable_raw, branch_path)
        unit = str(row.get("Units", ""))
        per_unit = str(row.get("Per...", ""))
        review = row.get("researcher_review_recommended", False)
        notes = str(row.get("review_reason", ""))
        source = str(row.get("source_name", "multinode_energy_balance"))
        value_2022 = row.get("2022")

        if pd.isna(value_2022):
            continue

        # Convert efficiency: MJ/100km → km/GJ
        if unit == _EFFICIENCY_UNIT:
            if value_2022 > 0:
                value_2022 = 10_000 / value_2022
            unit = "km/GJ"
            variable = "efficiency"

        # Passenger saturation in Module 1 defaults is commonly stored as
        # devices per 1000 people. Module 3 expects per-capita values.
        if variable == "saturation_level":
            per_lower = per_unit.strip().lower()
            if "1000" in per_lower and "people" in per_lower:
                value_2022 = float(value_2022) / 1000.0
                unit = "Device"

        parsed = _parse_branch_path(branch_path)

        # Drop rows without a recognisable vehicle type (age rows, size-label rows, etc.)
        # unless they are survival/vintage rows (which use Age N in branch path)
        if parsed["vehicle_type"] is None and variable not in (
            "survival_rate", "vintage_share",
            "reconciliation_bound_lower", "reconciliation_bound_upper",
            "reconciliation_weight", "reconciliation_bound_lower_stock",
            "reconciliation_bound_lower_mileage", "reconciliation_bound_lower_efficiency",
            "reconciliation_bound_upper_stock", "reconciliation_bound_upper_mileage",
            "reconciliation_bound_upper_efficiency", "reconciliation_weight_stock",
            "reconciliation_weight_mileage", "reconciliation_weight_efficiency",
            "saturation_level", "passenger_saturation_reached",
            "phev_electric_utilisation_rate",
        ):
            continue

        rows.append({
            "economy":           economy_code,
            "version":           version_name,
            "scope":             economy_code,
            "year":              int(row.get("_source_year", 2022)),
            "variable":          variable,
            "transport_type":    parsed["transport_type"],
            "vehicle_type":      parsed["vehicle_type"],
            "drive_type":        parsed["drive_type"],
            "size":              parsed["size"],
            "fuel":              parsed["fuel"],
            "leap_branch_path":  branch_path,
            "value":             value_2022,
            "unit":              unit,
            "source":            source,
            "review_recommended": bool(review),
            "notes":             notes,
        })

    return pd.DataFrame(rows)


def get_survival_curves(
    defaults_df: pd.DataFrame,
    economy: str,
    transport_type: str,
    vehicle_type: str | None = None,
) -> pd.DataFrame:
    """
    Extract survival rate profile for a given economy / transport type.

    Args:
        defaults_df: Output of load_road_module1_defaults().
        economy: Economy code e.g. '12_NZ'.
        transport_type: 'passenger' or 'freight'.
        vehicle_type: Optional LEAP vehicle type label. If None, returns
            the aggregate transport-level curve.

    Returns:
        DataFrame with columns [age, survival_rate] sorted by age.
        Age values are parsed from the leap_branch_path 'Age N' segment.
    """
    mask = (
        (defaults_df["economy"] == economy)
        & (defaults_df["transport_type"] == transport_type)
        & (defaults_df["variable"] == "survival_rate")
    )
    if vehicle_type is not None:
        mask &= defaults_df["vehicle_type"] == vehicle_type

    sub = defaults_df[mask].copy()
    if sub.empty:
        global_mask = (
            (defaults_df["economy"] == economy)
            & (defaults_df["variable"] == "survival_rate")
            & (defaults_df["transport_type"].isna())
            & (defaults_df["vehicle_type"].isna())
        )
        sub = defaults_df[global_mask].copy()
    if sub.empty:
        log.warning("No survival curve found for %s / %s / %s", economy, transport_type, vehicle_type)
        return pd.DataFrame(columns=["age", "survival_rate"])

    sub["age"] = sub["leap_branch_path"].apply(_extract_profile_age)
    sub = sub.dropna(subset=["age"])
    sub["age"] = sub["age"].astype(int)
    out = sub[["age", "value"]].rename(columns={"value": "survival_rate"})
    return out.sort_values("age").reset_index(drop=True)


def get_vintage_profiles(
    defaults_df: pd.DataFrame,
    economy: str,
    transport_type: str,
    vehicle_type: str | None = None,
) -> pd.DataFrame:
    """
    Extract vintage profile (fleet age distribution) for a given economy / transport type.

    Args:
        defaults_df: Output of load_road_module1_defaults().
        economy: Economy code e.g. '12_NZ'.
        transport_type: 'passenger' or 'freight'.
        vehicle_type: Optional vehicle type label. If None, returns
            the aggregate transport-level profile.

    Returns:
        DataFrame with columns [age, vintage_share] sorted by age.
    """
    mask = (
        (defaults_df["economy"] == economy)
        & (defaults_df["transport_type"] == transport_type)
        & (defaults_df["variable"] == "vintage_share")
    )
    if vehicle_type is not None:
        mask &= defaults_df["vehicle_type"] == vehicle_type

    sub = defaults_df[mask].copy()
    if sub.empty:
        global_mask = (
            (defaults_df["economy"] == economy)
            & (defaults_df["variable"] == "vintage_share")
            & (defaults_df["transport_type"].isna())
            & (defaults_df["vehicle_type"].isna())
        )
        sub = defaults_df[global_mask].copy()
    if sub.empty:
        log.warning("No vintage profile found for %s / %s / %s", economy, transport_type, vehicle_type)
        return pd.DataFrame(columns=["age", "vintage_share"])

    sub["age"] = sub["leap_branch_path"].apply(_extract_profile_age)
    sub = sub.dropna(subset=["age"])
    sub["age"] = sub["age"].astype(int)
    out = sub[["age", "value"]].rename(columns={"value": "vintage_share"})
    return out.sort_values("age").reset_index(drop=True)


def build_survival_curves(defaults_df: pd.DataFrame, economy: str) -> dict[str, pd.Series]:
    """
    Build survival_curves dict for all vehicle types for the given economy.

    Returns:
        Dict mapping vehicle_type → pd.Series indexed by age (survival probability 0–1).
    """
    result: dict[str, pd.Series] = {}

    # Standard Module 1 representation is transport-level age-series rows:
    #   Demand\Passenger road\Age N
    #   Demand\Freight road\Age N
    # These are intentionally transport-level (not vehicle-level).
    transport_to_vehicle_types = {
        "passenger": _PASSENGER_VEHICLE_TYPES,
        "freight": _FREIGHT_VEHICLE_TYPES,
    }
    for transport_type, vehicle_types in transport_to_vehicle_types.items():
        rows = get_survival_curves(
            defaults_df,
            economy=economy,
            transport_type=transport_type,
            vehicle_type=None,
        )
        if rows.empty:
            continue
        series = rows.set_index("age")["survival_rate"]
        for vt in vehicle_types:
            result[vt] = series.copy()

    # If any vehicle-specific curves exist, let them override transport-level curves.
    sub = defaults_df[
        (defaults_df["economy"] == economy)
        & (defaults_df["variable"] == "survival_rate")
        & (defaults_df["vehicle_type"].notna())
    ]
    for vt in sub["vehicle_type"].dropna().unique():
        tt_vals = sub[sub["vehicle_type"] == vt]["transport_type"].dropna()
        if tt_vals.empty:
            continue
        tt = tt_vals.iloc[0]
        rows = get_survival_curves(defaults_df, economy, tt, vt)
        if not rows.empty:
            result[vt] = rows.set_index("age")["survival_rate"]

    if not result:
        log.warning("No survival curves found for economy %s", economy)
    return result


def build_vintage_profiles(defaults_df: pd.DataFrame, economy: str) -> dict[str, pd.Series]:
    """
    Build vintage_profiles dict for all vehicle types for the given economy.

    Returns:
        Dict mapping vehicle_type → pd.Series indexed by age (normalised share 0–1).
    """
    result: dict[str, pd.Series] = {}

    # Standard Module 1 representation is transport-level age-series rows:
    #   Demand\Passenger road\Age N
    #   Demand\Freight road\Age N
    # Copy transport-level profiles to model vehicle buckets.
    transport_to_vehicle_types = {
        "passenger": _PASSENGER_VEHICLE_TYPES,
        "freight": _FREIGHT_VEHICLE_TYPES,
    }
    for transport_type, vehicle_types in transport_to_vehicle_types.items():
        rows = get_vintage_profiles(
            defaults_df,
            economy=economy,
            transport_type=transport_type,
            vehicle_type=None,
        )
        if rows.empty:
            continue
        series = rows.set_index("age")["vintage_share"]
        for vt in vehicle_types:
            result[vt] = series.copy()

    # If any vehicle-specific profiles exist, let them override transport-level profiles.
    sub = defaults_df[
        (defaults_df["economy"] == economy)
        & (defaults_df["variable"] == "vintage_share")
        & (defaults_df["vehicle_type"].notna())
    ]
    for vt in sub["vehicle_type"].dropna().unique():
        tt_vals = sub[sub["vehicle_type"] == vt]["transport_type"].dropna()
        if tt_vals.empty:
            continue
        tt = tt_vals.iloc[0]
        rows = get_vintage_profiles(defaults_df, economy, tt, vt)
        if not rows.empty:
            result[vt] = rows.set_index("age")["vintage_share"]

    if not result:
        log.warning("No vintage profiles found for economy %s", economy)
    return result


def get_passenger_saturation_level(defaults_df: pd.DataFrame, economy: str) -> float | None:
    """
    Extract passenger saturation level for Module 3.

    Returns:
        Saturation level value if present, else None.
    """
    mask = (
        (defaults_df["economy"] == economy)
        & (defaults_df["variable"] == "saturation_level")
        & (defaults_df["transport_type"] == "passenger")
    )
    sub = defaults_df[mask]["value"].dropna()
    if sub.empty:
        # Fallback to any saturation row for the economy if transport_type was not set.
        sub = defaults_df[
            (defaults_df["economy"] == economy)
            & (defaults_df["variable"] == "saturation_level")
        ]["value"].dropna()
    if sub.empty:
        log.warning("No passenger saturation level found for %s in Module 1 defaults", economy)
        return None
    value = float(sub.iloc[0])
    if value > 10.0:
        log.info(
            "Module 1 passenger saturation for %s appears to be vehicles per 1000 people; converting %.4f to per-capita",
            economy,
            value,
        )
        value = value / 1000.0
    log.info("Module 1 passenger saturation for %s: %.4f", economy, value)
    return value


def _parse_bool_value(value: object) -> bool:
    """Parse common Module 1 boolean encodings."""
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return False
    if isinstance(value, (int, float)):
        return float(value) != 0.0
    text = str(value).strip().lower()
    return text in {"true", "yes", "y", "1", "reached", "saturated"}


def get_passenger_saturation_reached(defaults_df: pd.DataFrame, economy: str) -> bool:
    """
    Extract explicit passenger saturation reached flag for Module 3.

    Returns False when the flag is absent so existing economies retain current behavior.
    """
    mask = (
        (defaults_df["economy"] == economy)
        & (defaults_df["variable"] == "passenger_saturation_reached")
    )
    sub = defaults_df[mask]["value"].dropna()
    if sub.empty:
        return False
    value = _parse_bool_value(sub.iloc[0])
    log.info("Module 1 passenger saturation reached flag for %s: %s", economy, value)
    return value


def get_vehicle_equivalent_weight_bounds(defaults_df: pd.DataFrame, economy: str) -> dict[str, tuple[float, float]]:
    """
    Extract calibration bounds for passenger vehicle-equivalent weights.

    Defaults apply when Module 1 does not provide explicit bounds.
    """
    bounds = {
        "Motorcycles": (0.05, 0.80),
        "Buses": (8.0, 30.0),
    }
    for vehicle_type in tuple(bounds):
        lower = defaults_df[
            (defaults_df["economy"] == economy)
            & (defaults_df["vehicle_type"] == vehicle_type)
            & (defaults_df["variable"] == "vehicle_equivalent_weight_lower_bound")
        ]["value"].dropna()
        upper = defaults_df[
            (defaults_df["economy"] == economy)
            & (defaults_df["vehicle_type"] == vehicle_type)
            & (defaults_df["variable"] == "vehicle_equivalent_weight_upper_bound")
        ]["value"].dropna()
        if not lower.empty and not upper.empty:
            bounds[vehicle_type] = (float(lower.iloc[0]), float(upper.iloc[0]))

    log.info("Module 1 vehicle equivalent calibration bounds for %s: %s", economy, bounds)
    return bounds


def get_reconciliation_weights(defaults_df: pd.DataFrame, economy: str) -> dict[str, float] | None:
    """
    Extract Module 6 reconciliation weights in {stock,mileage,efficiency} format.

    Module 1 currently usually provides aggregate `reconciliation_weight` rows
    (for passenger/freight scope), not component weights. If only aggregate
    weights are available, we retain the default component split while logging
    that component-level defaults were not supplied.
    """
    # Preferred future-friendly component variables, if present.
    component_var_map = {
        "reconciliation_weight_stock": "stock",
        "reconciliation_weight_mileage": "mileage",
        "reconciliation_weight_efficiency": "efficiency",
    }
    component_values: dict[str, float] = {}
    for var_name, key in component_var_map.items():
        sub = defaults_df[
            (defaults_df["economy"] == economy)
            & (defaults_df["variable"] == var_name)
        ]["value"].dropna()
        if not sub.empty:
            component_values[key] = float(sub.iloc[0])

    if len(component_values) == 3:
        total = sum(component_values.values())
        if total <= 0:
            log.warning("Component reconciliation weights sum to <=0 for %s; using defaults", economy)
            return dict(_DEFAULT_RECONCILIATION_WEIGHTS)
        return {k: v / total for k, v in component_values.items()}

    # Current Module 1 shape: aggregate reconciliation_weight rows.
    aggregate = defaults_df[
        (defaults_df["economy"] == economy)
        & (defaults_df["variable"] == "reconciliation_weight")
    ]["value"].dropna()
    if not aggregate.empty:
        log.info(
            "Module 1 provides aggregate reconciliation_weight for %s; "
            "using default component split stock/mileage/efficiency = %.2f/%.2f/%.2f",
            economy,
            _DEFAULT_RECONCILIATION_WEIGHTS["stock"],
            _DEFAULT_RECONCILIATION_WEIGHTS["mileage"],
            _DEFAULT_RECONCILIATION_WEIGHTS["efficiency"],
        )
        return dict(_DEFAULT_RECONCILIATION_WEIGHTS)

    log.warning("No reconciliation weights found for %s in Module 1 defaults", economy)
    return None


def get_phev_utilisation_rate(defaults_df: pd.DataFrame, economy: str) -> float:
    """
    Extract the PHEV electric driving share for the economy as a single float.

    Falls back to 0.50 if no row is found. If vehicle-type-specific rows are
    present instead of a single economy-level value, their mean is used and a
    warning is logged — supply a single economy-level row to avoid this.
    """
    mask = (
        (defaults_df["economy"] == economy)
        & (defaults_df["variable"] == "phev_electric_utilisation_rate")
    )
    sub = defaults_df[mask].dropna(subset=["value"])
    if sub.empty:
        log.warning(
            "No phev_electric_utilisation_rate found for %s in Module 1 defaults; using 0.50",
            economy,
        )
        return 0.50
    economy_level = sub[sub["vehicle_type"].isna()] if "vehicle_type" in sub.columns else sub
    if not economy_level.empty:
        rate = float(economy_level["value"].iloc[0])
    else:
        rate = float(sub["value"].mean())
        log.warning(
            "Only vehicle-type-specific PHEV rates found for %s; averaging to %.3f. "
            "Supply a single economy-level row instead.",
            economy, rate,
        )
    log.info("Module 1 PHEV utilisation rate for %s: %.3f", economy, rate)
    return rate


def get_scalar_bounds(
    defaults_df: pd.DataFrame,
    economy: str,
) -> tuple[float, float] | dict[str, tuple[float, float]] | None:
    """
    Extract reconciliation scalar bounds for the economy.

    Prefers per-component bounds (reconciliation_bound_lower/upper_mileage/efficiency).
    Falls back to aggregate bounds applied uniformly to mileage and efficiency.
    Stock is always left unbounded (0, inf) so it can absorb any residual.

    Returns a dict with per-scalar bounds for {stock, mileage, efficiency},
    or None if no bounds are present (Module 6 will use built-in defaults).
    """
    per_component: dict[str, tuple[float, float]] = {}
    for component in ("mileage", "efficiency"):
        lower_sub = defaults_df[
            (defaults_df["economy"] == economy)
            & (defaults_df["variable"] == f"reconciliation_bound_lower_{component}")
        ]["value"].dropna()
        upper_sub = defaults_df[
            (defaults_df["economy"] == economy)
            & (defaults_df["variable"] == f"reconciliation_bound_upper_{component}")
        ]["value"].dropna()
        if not lower_sub.empty and not upper_sub.empty:
            per_component[component] = (float(lower_sub.iloc[0]), float(upper_sub.iloc[0]))

    if len(per_component) == 2:
        bounds = {
            "stock": (0.0, float("inf")),
            "mileage": per_component["mileage"],
            "efficiency": per_component["efficiency"],
        }
        log.info("Module 1 per-component scalar bounds for %s: %s", economy, bounds)
        return bounds

    # Fall back to aggregate bounds
    lower_sub = defaults_df[
        (defaults_df["economy"] == economy)
        & (defaults_df["variable"] == "reconciliation_bound_lower")
    ]["value"].dropna()
    upper_sub = defaults_df[
        (defaults_df["economy"] == economy)
        & (defaults_df["variable"] == "reconciliation_bound_upper")
    ]["value"].dropna()

    if lower_sub.empty or upper_sub.empty:
        log.warning(
            "No reconciliation bounds found for %s in Module 1 defaults; "
            "Module 6 will use built-in defaults",
            economy,
        )
        return None

    lower = float(lower_sub.min())
    upper = float(upper_sub.max())
    bounds = {
        "stock": (0.0, float("inf")),
        "mileage": (lower, upper),
        "efficiency": (lower, upper),
    }
    log.info("Module 1 aggregate scalar bounds for %s mapped to per-scalar: %s", economy, bounds)
    return bounds


def get_vehicle_equivalent_weights(defaults_df: pd.DataFrame, economy: str) -> dict[str, float]:
    """
    Extract vehicle equivalent weights by vehicle_type for the economy.

    Returns dict mapping vehicle_type → weight, or empty dict if not present.
    """
    mask = (
        (defaults_df["economy"] == economy)
        & (defaults_df["variable"] == "vehicle_equivalent_weight")
    )
    sub = defaults_df[mask].dropna(subset=["vehicle_type"])
    if sub.empty:
        log.warning("No vehicle_equivalent_weight rows for %s; Module 3 will use built-in defaults", economy)
        return {}
    weights = sub.groupby("vehicle_type")["value"].first().to_dict()
    log.info("Module 1 vehicle equivalent weights for %s: %s", economy, weights)
    return weights


def get_vehicle_type_stock_shares(defaults_df: pd.DataFrame, economy: str) -> dict[str, pd.Series]:
    """
    Extract vehicle-type physical Stock Share rows from Module 1.

    Only the five LEAP vehicle-type branches are used:
    Passenger LPVs/Motorcycles/Buses and freight Trucks/LCVs. Lower-level
    drive/size Stock Share rows are intentionally ignored.
    Values are stored in Module 1 as LEAP-style percentages and returned here
    as fractions indexed by year.
    """
    required_columns = {"economy", "variable", "leap_branch_path", "value"}
    if defaults_df.empty or not required_columns.issubset(defaults_df.columns):
        return {}

    sub = defaults_df[
        (defaults_df["economy"] == economy)
        & (defaults_df["variable"] == "stock_share")
        & (defaults_df["leap_branch_path"].isin(_VEHICLE_TYPE_STOCK_SHARE_BRANCHES))
    ].copy()
    if sub.empty:
        return {}

    sub["year"] = pd.to_numeric(sub["year"], errors="coerce")
    sub["value"] = pd.to_numeric(sub["value"], errors="coerce")
    sub = sub.dropna(subset=["year", "value"])
    result: dict[str, pd.Series] = {}
    for branch_path, (_, vehicle_type) in _VEHICLE_TYPE_STOCK_SHARE_BRANCHES.items():
        rows = sub[sub["leap_branch_path"] == branch_path].sort_values("year")
        if rows.empty:
            continue
        series = rows.groupby("year")["value"].first().sort_index() / 100.0
        series.index = series.index.astype(int)
        result[vehicle_type] = series

    log.info("Module 1 vehicle-type Stock Share rows for %s: %s", economy, {k: v.to_dict() for k, v in result.items()})
    return result



def load_module1_leap_df(
    defaults_dir: str | Path,
    economy: str,
    version: str | None = None,
) -> pd.DataFrame:
    """
    Load the raw Module 1 defaults CSV for an economy in LEAP workbook format.

    Suitable for passing directly to parse_leap_format_inputs() in road_workflow.
    The 'Region' column is normalised to the canonical economy code so that
    parse_leap_format_inputs() works without a region_to_economy mapping.

    Args:
        defaults_dir: Path to the module1_defaults root directory.
        economy: Canonical economy code e.g. '12_NZ'.
        version: Version folder name. None = use most recently modified.

    Returns:
        Raw CSV DataFrame in LEAP workbook format.
    """
    defaults_dir = Path(defaults_dir)

    package_root = _resolve_package_root(defaults_dir, version)

    # Economy folder uses no-underscore convention (e.g. '12NZ') but may also exist as-is.
    # Planned long packages may also place road_module1_values_<ECONOMY>.csv
    # directly under the package root.
    economy_no_underscore = economy.replace("_", "")
    folder = next(
        (package_root / candidate for candidate in (economy, economy_no_underscore)
         if (package_root / candidate).is_dir()),
        None,
    )

    csv_path: Path | None = None
    if folder is not None:
        csv_path = _find_default_inputs_csv(folder, economy)
    else:
        direct_matches = [
            csv for found_economy, csv in _iter_package_csvs(package_root, economy_filter=[economy])
            if found_economy == economy
        ]
        if direct_matches:
            csv_path = direct_matches[0]

    if csv_path is None:
        raise FileNotFoundError(
            f"Module 1 defaults CSV not found for '{economy}' in {package_root}. "
            f"Tried folders: {economy}, {economy_no_underscore}; "
            f"and flat files matching road_module1_values_{economy}*.csv. "
            "Run scripts/generate_module1_defaults.py to generate defaults."
        )

    df = _read_module1_csv_as_wide(csv_path, economy_code=economy, version_name=package_root.name)
    # Normalise Region to economy code so parse_leap_format_inputs works without mapping
    if "Region" in df.columns:
        df = df.copy()
        df["Region"] = economy
    log.info("Loaded Module 1 LEAP CSV for %s from %s (%d rows)", economy, csv_path, len(df))
    return df


def load_module1_for_economy(
    defaults_dir: str | Path,
    economy: str,
    version: str | None = None,
) -> dict:
    """
    Load all Module 1 data needed by road_workflow for a single economy.

    This is the primary entry point for road_workflow to consume Module 1 outputs.
    Raises ValueError if no defaults are found, directing the user to the generate script.

    Args:
        defaults_dir: Path to the module1_defaults directory (contains version subfolders).
        economy: Canonical economy code e.g. '12_NZ'.
        version: Version folder name. None = use most recently modified.

    Returns:
        Dict with keys:
            raw_leap_df            : LEAP-format DataFrame, pass to parse_leap_format_inputs()
            survival_curves        : dict[vehicle_type → pd.Series by age]
            vintage_profiles       : dict[vehicle_type → pd.Series by age]
            phev_utilisation_rate  : float
            scalar_bounds          : tuple(lower, upper) or None
            passenger_saturation_level : float or None
            reconciliation_weights : dict{stock,mileage,efficiency} or None
            vehicle_equivalent_weights : dict[vehicle_type → float]
    """
    defaults_dir = Path(defaults_dir)
    if not defaults_dir.exists():
        raise FileNotFoundError(
            f"Module 1 defaults directory not found: {defaults_dir}\n"
            "Generate Module 1 defaults first by running:\n"
            "    python scripts/generate_module1_defaults.py"
        )

    defaults_df = load_road_module1_defaults(
        defaults_dir,
        version=version,
        economy_filter=[economy],
    )

    if defaults_df.empty:
        raise ValueError(
            f"No Module 1 defaults found for economy '{economy}' in {defaults_dir}.\n"
            "Generate them by running:\n"
            "    python scripts/generate_module1_defaults.py"
        )

    raw_leap_df = load_module1_leap_df(defaults_dir, economy, version)

    return {
        "raw_leap_df": raw_leap_df,
        "survival_curves": build_survival_curves(defaults_df, economy),
        "vintage_profiles": build_vintage_profiles(defaults_df, economy),
        "phev_utilisation_rate": get_phev_utilisation_rate(defaults_df, economy),
        "scalar_bounds": get_scalar_bounds(defaults_df, economy),
        "passenger_saturation_level": get_passenger_saturation_level(defaults_df, economy),
        "passenger_saturation_reached": get_passenger_saturation_reached(defaults_df, economy),
        "reconciliation_weights": get_reconciliation_weights(defaults_df, economy),
        "vehicle_equivalent_weights": get_vehicle_equivalent_weights(defaults_df, economy),
        "vehicle_equivalent_weight_bounds": get_vehicle_equivalent_weight_bounds(defaults_df, economy),
        "vehicle_type_stock_shares": get_vehicle_type_stock_shares(defaults_df, economy),
    }


def load_lifecycle_profile_factors(
    source_path: str | Path | None = None,
    economy: str | None = None,
    transport_type: str | None = None,
) -> pd.DataFrame:
    """
    Load lifecycle profile calibration factors from apec_lifecycle_profile_factors.csv.

    The CSV has global APEC-wide defaults (blank project_code/economy) plus optional
    economy-specific overrides. Economy-specific rows take priority over APEC defaults.

    Args:
        source_path: Explicit path to the CSV. When None, looks for the file
            relative to this adapter's standard data directory.
        economy: Optional economy code to filter (e.g. '12_NZ'). When provided,
            returns the economy-specific row if it exists, otherwise the APEC default.
        transport_type: Optional transport type to filter ('passenger' or 'freight').

    Returns:
        DataFrame with columns:
            project_code, economy, transport_type, data_year,
            turnover_rate_lower, turnover_rate_upper,
            fit_mode, scale_age_band_age_min, scale_age_band_age_max,
            scale_age_band_factor, smoothing_window,
            evidence_grade, estimation_status, source_note
        Each row represents calibration parameters for one transport_type.
        Returns empty DataFrame if file not found.
    """
    _LIFECYCLE_FACTORS_FILENAME = "apec_lifecycle_profile_factors.csv"

    if source_path is None:
        # Standard location relative to this file's package
        candidates = [
            Path(__file__).resolve().parents[3]
            / "road_model_inputs_interface" / "back-end" / "data" / "road_model"
            / _LIFECYCLE_FACTORS_FILENAME,
        ]
        source_path = next((p for p in candidates if p.exists()), None)

    if source_path is None:
        log.warning("lifecycle_profile_factors CSV not found; using no lifecycle calibration")
        return pd.DataFrame()

    df = pd.read_csv(Path(source_path))
    numeric_cols = [
        "turnover_rate_lower", "turnover_rate_upper",
        "scale_age_band_age_min", "scale_age_band_age_max",
        "scale_age_band_factor", "smoothing_window", "data_year",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Normalise text columns
    for col in ["project_code", "economy", "transport_type", "fit_mode"]:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()

    if transport_type is not None:
        df = df[df["transport_type"] == transport_type]

    if economy is not None and not df.empty:
        # Normalise the economy code for matching (strip underscores)
        economy_norm = economy.replace("_", "").upper()
        economy_rows = df[
            df["project_code"].str.replace("_", "").str.upper() == economy_norm
        ]
        apec_rows = df[df["project_code"] == ""]
        # Economy-specific rows override APEC defaults row-by-row per transport_type
        if not economy_rows.empty:
            present_types = set(economy_rows["transport_type"])
            fallback = apec_rows[~apec_rows["transport_type"].isin(present_types)]
            df = pd.concat([economy_rows, fallback], ignore_index=True)
        else:
            df = apec_rows

    return df.reset_index(drop=True)
