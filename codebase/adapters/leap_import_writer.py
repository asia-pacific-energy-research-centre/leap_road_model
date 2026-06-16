"""
Adapter A9 — strict LEAP import workbook writer.

Builds LEAP-ready Excel workbooks from T11_leap_ready by joining model rows to
a reference LEAP export ID table. The output has LEAP's required metadata rows,
ID columns, fixed column order, a compact LEAP sheet with Data(...) expressions,
and a FOR_VIEWING sheet with annual columns.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from adapters.leap_expressions import to_leap_expression


ROAD_BRANCH_PREFIXES = ("Demand\\Passenger road", "Demand\\Freight road")
LEAP_IMPORT_COLUMNS = [
    "BranchID",
    "VariableID",
    "ScenarioID",
    "RegionID",
    "Branch Path",
    "Variable",
    "Scenario",
    "Region",
    "Scale",
    "Units",
    "Per...",
    "Expression",
]
LEVEL_COLUMNS = [
    "Level 1",
    "Level 2",
    "Level 3",
    "Level 4",
    "Level 5",
    "Level 6",
    "Level 7",
    "Level 8...",
]
LEAP_LEVEL_SPACER_COLUMN = ""
LEAP_OUTPUT_COLUMNS = [*LEAP_IMPORT_COLUMNS, LEAP_LEVEL_SPACER_COLUMN, *LEVEL_COLUMNS]
NOT_NEEDED_COLUMNS = [
    "side",
    "reason",
    "Branch Path",
    "Variable",
    "Scenario",
    "message",
]
ROW_COVERAGE_DIAGNOSTIC_COLUMNS = [
    "diagnostic_status",
    "severity",
    "type",
    "side",
    "reason",
    "Branch Path",
    "Variable",
    "Scenario",
    "message",
]
MANUAL_MISSING_ROW_COLUMNS = [
    "Economy",
    "Branch Path",
    "Variable",
    "Scenario",
    "Year",
    "Value",
    "Units",
    "notes",
    "DO_NOT_USE",
]
DEFAULT_MANUAL_MISSING_ROWS_PATH = (
    Path(__file__).resolve().parents[3]
    / "road_model_inputs_interface"
    / "back-end"
    / "data"
    / "road_model"
    / "manually_filled_rows"
    / "manually_entered_missing_rows.csv"
)
REFERENCE_RENAME = {
    "BranchID": "BranchID",
    "VariableID": "VariableID",
    "ScenarioID": "ScenarioID",
    "RegionID": "RegionID",
    "Branch Path": "Branch Path",
    "Variable": "Variable",
    "Scenario": "Scenario",
    "Region": "Region",
    "Scale": "Scale",
    "Units": "Units",
    "Per...": "Per...",
}
ACTIVE_IMPORT_VARIABLES = {
    "Stock",
    "Sales",
    "Sales Share",
    "Stock Share",
    "Mileage",
    "Fuel Economy",
    "Mileage Correction Factor",
    "Fuel Economy Correction Factor",
    "Device Share",
}
IGNORED_REFERENCE_VARIABLES = {
    "Average Mileage",
    "Final On-Road Mileage",
    "Final On-Road Fuel Economy",
    "Demand Cost",
    "First Sales Year",
    "Scrappage",
    "Fraction of Scrapped Replaced",
    "Max Scrappage Fraction",
}
VALID_DRIVES_BY_VEHICLE_TYPE = {
    "LPVs": {"ICE", "HEV", "EREV", "PHEV", "BEV", "FCEV"},
    "Motorcycles": {"ICE", "BEV", "FCEV"},
    "Buses": {"ICE", "BEV", "FCEV"},
    "Trucks": {"ICE", "BEV", "FCEV"},
    "LCVs": {"ICE", "PHEV", "BEV", "FCEV"},
}
VALID_SIZES_BY_VEHICLE_TYPE = {
    "LPVs": {"small", "medium", "large"},
    "Motorcycles": {""},
    "Buses": {""},
    "Trucks": {"medium", "heavy"},
    "LCVs": {""},
}
VALID_FUELS_BY_DRIVE = {
    "ICE": {"Motor gasoline", "Gas and diesel oil", "Natural gas", "LPG", "LNG", "Biogasoline", "Biodiesel", "Biogas", "Efuel"},
    "HEV": {"Motor gasoline", "Gas and diesel oil", "Natural gas", "LPG", "LNG", "Biogasoline", "Biodiesel", "Biogas", "Efuel"},
    "BEV": {"Electricity"},
    "PHEV": {"Electricity", "Motor gasoline", "Gas and diesel oil", "Biogasoline", "Biodiesel", "Efuel"},
    "EREV": {"Electricity", "Motor gasoline", "Gas and diesel oil", "Biogasoline", "Biodiesel", "Efuel"},
    "FCEV": {"Hydrogen"},
}

SCALE_MULTIPLIERS = {
    "": 1.0,
    "%": 1.0,
    "thousand": 1_000.0,
    "thousands": 1_000.0,
    "million": 1_000_000.0,
    "millions": 1_000_000.0,
    "billion": 1_000_000_000.0,
    "billions": 1_000_000_000.0,
}


def _scale_multiplier(scale: object) -> float:
    if pd.isna(scale):
        return 1.0
    return SCALE_MULTIPLIERS.get(str(scale).strip().lower(), 1.0)


def _scale_label_for_export(scale: object, export_values_in_raw_units: bool) -> str:
    scale_text = "" if pd.isna(scale) else str(scale).strip()
    if not export_values_in_raw_units:
        return scale_text
    return "%" if scale_text == "%" else ""


def _pair_key(df: pd.DataFrame) -> pd.Series:
    return df["Branch Path"].fillna("").astype(str) + "\u241f" + df["Variable"].fillna("").astype(str)


def _first_text(df: pd.DataFrame, column: str) -> str:
    if column not in df.columns:
        return ""
    values = df[column].fillna("").astype(str).str.strip()
    values = values[values.ne("")]
    return values.iloc[0] if not values.empty else ""


def _branch_level_values(branch_path: object, level_count: int = len(LEVEL_COLUMNS)) -> list[str]:
    parts = [part.strip() for part in str(branch_path or "").split("\\") if part.strip()]
    values = parts[:level_count]
    return values + [""] * (level_count - len(values))


def _add_level_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out[LEAP_LEVEL_SPACER_COLUMN] = ""
    level_rows = out["Branch Path"].map(_branch_level_values).tolist()
    levels = pd.DataFrame(level_rows, columns=LEVEL_COLUMNS, index=out.index)
    for column in LEVEL_COLUMNS:
        out[column] = levels[column]
    return out


def load_reference_id_table(
    reference_path: str | Path,
    sheet_name: str = "LEAP",
    header_row: int = 2,
    road_only: bool = True,
) -> pd.DataFrame:
    """Load LEAP BranchID/VariableID/ScenarioID metadata from a reference export."""
    path = Path(reference_path)
    for name in [sheet_name, "Export", 0]:
        try:
            df = pd.read_excel(path, sheet_name=name, header=header_row)
            break
        except ValueError:
            continue
    else:
        raise ValueError(f"Could not find a usable sheet in {path}")

    missing = [column for column in REFERENCE_RENAME if column not in df.columns]
    if missing:
        raise ValueError(f"Reference LEAP export is missing required columns: {missing}")

    df = df[list(REFERENCE_RENAME)].rename(columns=REFERENCE_RENAME).copy()
    df["Branch Path"] = df["Branch Path"].fillna("").astype(str).str.strip()
    df["Variable"] = df["Variable"].fillna("").astype(str).str.strip()
    df["Scenario"] = df["Scenario"].fillna("").astype(str).str.strip()
    df = df[df["Branch Path"].ne("") & df["Variable"].ne("") & df["Scenario"].ne("")]
    if road_only:
        df = df[df["Branch Path"].str.startswith(ROAD_BRANCH_PREFIXES)].copy()
    id_columns = ["BranchID", "VariableID", "ScenarioID", "RegionID"]
    for column in id_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    return df.drop_duplicates(subset=["Branch Path", "Variable", "Scenario"]).reset_index(drop=True)


def _normalise_t11(leap_ready: pd.DataFrame) -> pd.DataFrame:
    """Normalise T11 column names to the LEAP writer contract."""
    rename = {
        "leap_branch_path": "Branch Path",
        "variable": "Variable",
        "scenario": "Scenario",
        "unit": "Units",
        "scale": "Scale",
    }
    df = leap_ready.rename(columns={k: v for k, v in rename.items() if k in leap_ready.columns}).copy()
    required = ["Branch Path", "Variable", "Scenario", "year", "value"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"T11_leap_ready is missing required columns: {missing}")
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["year", "value"])
    df["year"] = df["year"].astype(int)
    if "Units" not in df.columns:
        df["Units"] = ""
    if "Scale" not in df.columns:
        df["Scale"] = ""
    return df


def _parse_road_branch(branch_path: object) -> dict[str, str | None]:
    parts = [part.strip() for part in str(branch_path or "").split("\\") if part.strip()]
    result: dict[str, str | None] = {
        "transport_type": None,
        "vehicle_type": None,
        "drive_type": None,
        "size": None,
        "fuel": None,
    }
    if len(parts) < 2 or parts[0] != "Demand":
        return result
    if parts[1] == "Passenger road":
        result["transport_type"] = "passenger"
    elif parts[1] == "Freight road":
        result["transport_type"] = "freight"
    else:
        return result
    if len(parts) >= 3:
        result["vehicle_type"] = parts[2]
    if len(parts) >= 4:
        tech_tokens = parts[3].split()
        if tech_tokens:
            result["drive_type"] = tech_tokens[0]
            result["size"] = " ".join(tech_tokens[1:]) or ""
    if len(parts) >= 5:
        result["fuel"] = parts[4]
    return result


def _branch_without_fuel(branch_path: object) -> str:
    parts = [part.strip() for part in str(branch_path or "").split("\\") if part.strip()]
    return "\\".join(parts[:4]) if len(parts) >= 4 else str(branch_path or "").strip()


def _vehicle_branch(branch_path: object) -> str:
    parts = [part.strip() for part in str(branch_path or "").split("\\") if part.strip()]
    return "\\".join(parts[:3]) if len(parts) >= 3 else str(branch_path or "").strip()


def _fuel_group(fuel: str | None) -> str:
    if fuel == "Electricity":
        return "electric"
    if fuel == "Hydrogen":
        return "hydrogen"
    if fuel:
        return "liquid"
    return ""


def _is_active_scope_row(row: pd.Series) -> bool:
    """True when a coverage warning should be shown to reviewers."""
    variable = str(row.get("Variable", "") or "").strip()
    if variable in IGNORED_REFERENCE_VARIABLES:
        return False
    if variable not in ACTIVE_IMPORT_VARIABLES:
        return False

    branch_path = str(row.get("Branch Path", "") or "").strip()
    parsed = _parse_road_branch(branch_path)
    if parsed["transport_type"] is None:
        return False

    vehicle_type = parsed["vehicle_type"]
    drive_type = parsed["drive_type"]
    size = parsed["size"]
    fuel = parsed["fuel"]

    if vehicle_type is None:
        return True
    if vehicle_type not in VALID_DRIVES_BY_VEHICLE_TYPE:
        return False
    if drive_type is None:
        return True
    if drive_type not in VALID_DRIVES_BY_VEHICLE_TYPE[vehicle_type]:
        return False
    if size not in VALID_SIZES_BY_VEHICLE_TYPE.get(vehicle_type, {""}):
        return False
    if fuel is None:
        return True
    return fuel in VALID_FUELS_BY_DRIVE.get(drive_type, set())


def _is_not_needed_reference_row(row: pd.Series) -> tuple[bool, str, str]:
    variable = str(row.get("Variable", "") or "").strip()
    scenario = str(row.get("Scenario", "") or "").strip()
    parsed = _parse_road_branch(row.get("Branch Path", ""))
    if (
        variable == "Stock Share"
        and scenario == "Current Accounts"
        and parsed["drive_type"] is not None
    ):
        return (
            True,
            "current_accounts_lower_level_stock_share",
            "Lower-level Current Accounts Stock Share rows are not imported; vehicle-type Stock Share rows are canonical.",
        )
    return False, "", ""


def _expand_metric_rows_to_reference_fuels(df: pd.DataFrame, reference_ids: pd.DataFrame) -> pd.DataFrame:
    """
    Add missing fuel-level Mileage/Fuel Economy rows when a matching model value exists.

    Module 2/6 may carry mileage at a sibling fuel row after broad vehicle-type
    defaults are split into fuel-level branches. LEAP, however, expects explicit
    rows on every valid fuel branch. Fuel economy is copied only within the same
    technology branch, and plug-in liquid/electric values are not crossed.
    """
    if df.empty or reference_ids.empty:
        return df

    key_columns = ["Branch Path", "Variable", "Scenario"]
    existing = set(df[key_columns].astype(str).agg("\u241f".join, axis=1))
    metric_refs = reference_ids[
        reference_ids["Variable"].isin(["Mileage", "Fuel Economy"])
        & reference_ids.apply(_is_active_scope_row, axis=1)
    ].copy()
    if metric_refs.empty:
        return df

    model = df.copy()
    model["_tech_path"] = model["Branch Path"].map(_branch_without_fuel)
    model["_vehicle_path"] = model["Branch Path"].map(_vehicle_branch)
    model["_fuel"] = model["Branch Path"].map(lambda value: _parse_road_branch(value)["fuel"])
    model["_fuel_group"] = model["_fuel"].map(_fuel_group)

    additions: list[pd.DataFrame] = []
    for _, ref in metric_refs.iterrows():
        ref_key = "\u241f".join(str(ref[column]) for column in key_columns)
        if ref_key in existing:
            continue
        parsed = _parse_road_branch(ref["Branch Path"])
        if parsed["fuel"] is None:
            continue

        target_tech = _branch_without_fuel(ref["Branch Path"])
        target_vehicle = _vehicle_branch(ref["Branch Path"])
        target_fuel_group = _fuel_group(parsed["fuel"])
        candidates = model[
            model["Variable"].eq(ref["Variable"])
            & model["Scenario"].eq(ref["Scenario"])
        ].copy()
        if candidates.empty:
            continue

        if ref["Variable"] == "Fuel Economy":
            candidates = candidates[candidates["_tech_path"].eq(target_tech)]
            if parsed["drive_type"] in {"PHEV", "EREV"}:
                candidates = candidates[candidates["_fuel_group"].eq(target_fuel_group)]
        else:
            same_tech = candidates[candidates["_tech_path"].eq(target_tech)]
            candidates = same_tech if not same_tech.empty else candidates[candidates["_vehicle_path"].eq(target_vehicle)]

        if candidates.empty:
            continue

        source = candidates.sort_values(["year", "Branch Path"]).copy()
        source["Branch Path"] = ref["Branch Path"]
        if not str(source["Units"].dropna().astype(str).iloc[0] if not source["Units"].dropna().empty else ""):
            source["Units"] = ref.get("Units", source.get("Units", ""))
        additions.append(source[[*key_columns, "year", "value", "Units"]])
        existing.add(ref_key)

    if not additions:
        return df
    expanded = pd.concat([df, *additions], ignore_index=True)
    return expanded.drop_duplicates(subset=[*key_columns, "year"], keep="first").reset_index(drop=True)


def _not_needed_row(row: pd.Series, side: str, reason: str, message: str) -> dict[str, object]:
    return {
        "side": side,
        "reason": reason,
        "Branch Path": row.get("Branch Path", ""),
        "Variable": row.get("Variable", ""),
        "Scenario": row.get("Scenario", ""),
        "message": message,
    }


def build_leap_import_tables(
    leap_ready: pd.DataFrame,
    reference_ids: pd.DataFrame,
    economy_long_name: str,
    region_id: int | None = None,
    export_values_in_raw_units: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, object]], pd.DataFrame]:
    """Build LEAP/FOR_VIEWING sheets plus coverage warnings and suppressed rows."""
    df = _expand_metric_rows_to_reference_fuels(_normalise_t11(leap_ready), reference_ids)
    key_columns = ["Branch Path", "Variable", "Scenario"]
    grouped_rows = []
    for key, group in df.groupby(key_columns, dropna=False):
        branch_path, variable, scenario = key
        series = group.sort_values("year").set_index("year")["value"]
        grouped_rows.append(
            {
                "Branch Path": branch_path,
                "Variable": variable,
                "Scenario": scenario,
                "Units": _first_text(group, "Units"),
                "Scale": _first_text(group, "Scale"),
                "Expression": to_leap_expression(series),
            }
        )
    model_rows = pd.DataFrame(grouped_rows)

    merged = model_rows.merge(
        reference_ids,
        on=key_columns,
        how="left",
        suffixes=("", "_reference"),
        indicator=True,
    )

    warnings: list[dict[str, object]] = []
    not_needed_rows: list[dict[str, object]] = []
    reference_pairs = set(_pair_key(reference_ids))
    reference_branches = set(reference_ids["Branch Path"].fillna("").astype(str))
    extra_candidates = merged[merged["_merge"].eq("left_only")].copy()
    extra_candidates["_pair_key"] = _pair_key(extra_candidates)
    for _, row in extra_candidates.iterrows():
        if not _is_active_scope_row(row):
            not_needed_rows.append(_not_needed_row(row, "model", "outside_active_scope", "Model row is outside the active LEAP road import scope."))
            continue
        if row["_pair_key"] in reference_pairs:
            not_needed_rows.append(_not_needed_row(row, "model", "scenario_only_mismatch", "Branch and variable exist in the reference under another scenario."))
            continue
        if str(row["Branch Path"]) not in reference_branches:
            not_needed_rows.append(_not_needed_row(row, "model", "branch_not_in_reference", "Model branch is not present in the reference export."))
            continue
        warnings.append(
            {
                "severity": "warning",
                "type": "model_row_not_in_leap_reference",
                "Branch Path": row["Branch Path"],
                "Variable": row["Variable"],
                "Scenario": row["Scenario"],
                "message": "Model produced a row LEAP does not recognise; excluded from import.",
            }
        )

    model_pairs = set(_pair_key(model_rows))
    model_branches = set(model_rows["Branch Path"].fillna("").astype(str))
    missing_rows = reference_ids.merge(model_rows[key_columns], on=key_columns, how="left", indicator=True)
    missing_rows = missing_rows[missing_rows["_merge"].eq("left_only")].copy()
    missing_rows["_pair_key"] = _pair_key(missing_rows)
    for _, row in missing_rows.iterrows():
        is_not_needed, reason, message = _is_not_needed_reference_row(row)
        if is_not_needed:
            not_needed_rows.append(_not_needed_row(row, "reference", reason, message))
            continue
        if not _is_active_scope_row(row):
            not_needed_rows.append(_not_needed_row(row, "reference", "outside_active_scope", "Reference row is outside the active LEAP road import scope."))
            continue
        if row["_pair_key"] in model_pairs:
            not_needed_rows.append(_not_needed_row(row, "reference", "scenario_only_mismatch", "Branch and variable are produced by the model under another scenario."))
            continue
        if str(row["Branch Path"]) not in model_branches:
            not_needed_rows.append(_not_needed_row(row, "reference", "branch_not_in_model", "Reference branch is not produced by the model."))
            continue
        warnings.append(
            {
                "severity": "warning",
                "type": "leap_reference_row_not_in_model",
                "Branch Path": row["Branch Path"],
                "Variable": row["Variable"],
                "Scenario": row["Scenario"],
                "message": "LEAP expects this row but the model did not produce it.",
            }
        )

    matched = merged[merged["_merge"].eq("both")].copy()
    if matched.empty:
        raise ValueError("No T11 rows matched the LEAP reference ID table.")

    for column in ["Scale", "Units", "Per..."]:
        ref_col = f"{column}_reference"
        if ref_col in matched.columns:
            model_values = matched[column] if column in matched.columns else ""
            matched[column] = model_values.where(model_values.fillna("").astype(str).str.strip().ne(""), matched[ref_col])
        elif column not in matched.columns:
            matched[column] = ""
        matched[column] = matched[column].fillna("")

    matched["Scale"] = matched["Scale"].map(
        lambda scale: _scale_label_for_export(scale, export_values_in_raw_units)
    )
    scale_by_key = matched[key_columns + ["Scale"]].drop_duplicates(subset=key_columns)
    df_for_values = df.merge(scale_by_key, on=key_columns, how="left", suffixes=("", "_matched"))
    df_for_values["Scale"] = df_for_values["Scale_matched"].fillna(df_for_values.get("Scale", ""))
    if not export_values_in_raw_units:
        df_for_values["value"] = df_for_values["value"] / df_for_values["Scale"].map(_scale_multiplier)

    expression_rows = []
    for key, group in df_for_values.groupby(key_columns, dropna=False):
        branch_path, variable, scenario = key
        series = group.set_index("year")["value"].sort_index()
        expression_rows.append(
            {
                "Branch Path": branch_path,
                "Variable": variable,
                "Scenario": scenario,
                "Expression": to_leap_expression(series),
            }
        )
    expression_df = pd.DataFrame(expression_rows)
    matched = matched.drop(columns=["Expression"], errors="ignore").merge(expression_df, on=key_columns, how="left")

    matched["Region"] = economy_long_name
    if region_id is not None:
        matched["RegionID"] = region_id
    else:
        warnings.append(
            {
                "severity": "warning",
                "type": "region_id_from_reference",
                "message": "RegionID was copied from the reference export; verify for this LEAP area.",
            }
        )

    leap_sheet = _add_level_columns(matched[LEAP_IMPORT_COLUMNS])
    id_columns = ["BranchID", "VariableID", "ScenarioID", "RegionID"]
    for column in id_columns:
        leap_sheet[column] = pd.to_numeric(leap_sheet[column], errors="coerce").astype("Int64")
    leap_sheet = leap_sheet.sort_values(["BranchID", "VariableID", "ScenarioID"]).reset_index(drop=True)

    viewing_values = df_for_values[key_columns + ["year", "value"]].merge(
        leap_sheet.drop(columns=["Expression"]),
        on=key_columns,
        how="inner",
    )
    viewing = (
        viewing_values.pivot_table(
            index=[column for column in LEAP_OUTPUT_COLUMNS if column != "Expression"],
            columns="year",
            values="value",
            aggfunc="first",
        )
        .reset_index()
        .rename_axis(columns=None)
    )
    year_columns = sorted([column for column in viewing.columns if isinstance(column, int)])
    viewing_sheet = viewing[
        [column for column in LEAP_OUTPUT_COLUMNS if column != "Expression"] + year_columns
    ]
    not_needed_sheet = pd.DataFrame(not_needed_rows, columns=NOT_NEEDED_COLUMNS)
    return leap_sheet, viewing_sheet, warnings, not_needed_sheet


def _write_sheet_with_metadata(
    writer: pd.ExcelWriter,
    sheet_name: str,
    df: pd.DataFrame,
    area_name: str,
    version: str = "",
) -> None:
    df.to_excel(writer, sheet_name=sheet_name, index=False, startrow=2)
    worksheet = writer.sheets[sheet_name]
    worksheet.cell(row=1, column=5, value="Area:")
    worksheet.cell(row=1, column=6, value=area_name)
    worksheet.cell(row=1, column=7, value="Ver:")
    worksheet.cell(row=1, column=8, value=version)


def _build_row_coverage_diagnostics(
    warnings: list[dict[str, object]],
    not_needed_sheet: pd.DataFrame,
) -> pd.DataFrame:
    """Combine missing required rows and suppressed rows into one diagnostic table."""
    pieces: list[pd.DataFrame] = []
    if warnings:
        warning_rows = pd.DataFrame(warnings).copy()
        warning_rows["diagnostic_status"] = warning_rows["type"].map(
            lambda value: "missing_required" if value in {"leap_reference_row_not_in_model", "model_row_not_in_leap_reference"} else "notice"
        )
        warning_rows["side"] = warning_rows["type"].map(
            lambda value: "reference" if value == "leap_reference_row_not_in_model" else ("model" if value == "model_row_not_in_leap_reference" else "")
        )
        warning_rows["reason"] = warning_rows["type"].fillna("")
        pieces.append(warning_rows)
    if not_needed_sheet is not None and not not_needed_sheet.empty:
        not_needed = not_needed_sheet.copy()
        not_needed["diagnostic_status"] = "not_needed"
        not_needed["severity"] = "info"
        not_needed["type"] = "row_not_needed"
        pieces.append(not_needed)

    if not pieces:
        return pd.DataFrame(columns=ROW_COVERAGE_DIAGNOSTIC_COLUMNS)
    out = pd.concat(pieces, ignore_index=True, sort=False)
    for column in ROW_COVERAGE_DIAGNOSTIC_COLUMNS:
        if column not in out.columns:
            out[column] = ""
    return out[ROW_COVERAGE_DIAGNOSTIC_COLUMNS].sort_values(
        ["diagnostic_status", "side", "reason", "Branch Path", "Variable", "Scenario"],
        na_position="last",
    ).reset_index(drop=True)


def _missing_diagnostics_to_blank_manual_rows(
    diagnostics: pd.DataFrame,
    economy: str,
    year: int = 2022,
) -> pd.DataFrame:
    """Return blank manual-source rows for required LEAP rows missing from the model."""
    if diagnostics.empty:
        return pd.DataFrame(columns=MANUAL_MISSING_ROW_COLUMNS)

    required = diagnostics[
        diagnostics["diagnostic_status"].eq("missing_required")
        & diagnostics["side"].eq("reference")
        & diagnostics["type"].eq("leap_reference_row_not_in_model")
    ].copy()
    if required.empty:
        return pd.DataFrame(columns=MANUAL_MISSING_ROW_COLUMNS)

    out = pd.DataFrame(
        {
            "Economy": economy,
            "Branch Path": required["Branch Path"].fillna("").astype(str).str.strip(),
            "Variable": required["Variable"].fillna("").astype(str).str.strip(),
            "Scenario": required["Scenario"].fillna("").astype(str).str.strip(),
            "Year": year,
            "Value": pd.NA,
            "Units": "",
            "notes": "Automatically added from LEAP row coverage diagnostics; fill Value to activate.",
            "DO_NOT_USE": "",
        }
    )
    out = out[out["Branch Path"].ne("") & out["Variable"].ne("") & out["Scenario"].ne("")]
    return out[MANUAL_MISSING_ROW_COLUMNS].drop_duplicates(
        subset=["Economy", "Branch Path", "Variable", "Scenario", "Year"],
        keep="first",
    )


def update_manual_missing_rows_file(
    diagnostics: pd.DataFrame,
    economy: str,
    output_path: str | Path = DEFAULT_MANUAL_MISSING_ROWS_PATH,
    year: int = 2022,
) -> Path:
    """
    Merge required missing LEAP rows into the shared manual-fill source file.

    Rows are written with blank Value cells so the interface loader ignores them
    until a researcher enters a value.
    """
    output_path = Path(output_path)
    new_rows = _missing_diagnostics_to_blank_manual_rows(diagnostics, economy=economy, year=year)
    if output_path.exists():
        existing = pd.read_csv(output_path)
    else:
        existing = pd.DataFrame(columns=MANUAL_MISSING_ROW_COLUMNS)

    existing = existing.rename(
        columns={
            "DO NOT USE": "DO_NOT_USE",
            "do_not_use": "DO_NOT_USE",
            "do not use": "DO_NOT_USE",
        }
    )
    for column in MANUAL_MISSING_ROW_COLUMNS:
        if column not in existing.columns:
            existing[column] = pd.NA
    existing = existing[MANUAL_MISSING_ROW_COLUMNS].copy()
    combined = pd.concat([existing, new_rows], ignore_index=True)
    combined["_has_value"] = combined["Value"].notna() & combined["Value"].astype(str).str.strip().ne("")
    combined = combined.sort_values(
        ["Economy", "Branch Path", "Variable", "Scenario", "Year", "_has_value"],
        ascending=[True, True, True, True, True, False],
    )
    combined = combined.drop_duplicates(
        subset=["Economy", "Branch Path", "Variable", "Scenario", "Year"],
        keep="first",
    ).drop(columns=["_has_value"])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined[MANUAL_MISSING_ROW_COLUMNS].to_csv(output_path, index=False)
    return output_path


def write_leap_import_workbook(
    leap_ready: pd.DataFrame,
    output_path: str | Path,
    reference_path: str | Path,
    economy_long_name: str,
    area_name: str | None = None,
    region_id: int | None = None,
    version: str = "2",
    coverage_diagnostics_path: str | Path | None = None,
    manual_missing_rows_path: str | Path | None = DEFAULT_MANUAL_MISSING_ROWS_PATH,
    economy_code: str | None = None,
    export_values_in_raw_units: bool = False,
) -> list[dict[str, object]]:
    """Write a strict LEAP import workbook and return structured warnings."""
    reference_ids = load_reference_id_table(reference_path)
    leap_sheet, viewing_sheet, warnings, not_needed_sheet = build_leap_import_tables(
        leap_ready=leap_ready,
        reference_ids=reference_ids,
        economy_long_name=economy_long_name,
        region_id=region_id,
        export_values_in_raw_units=export_values_in_raw_units,
    )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        _write_sheet_with_metadata(writer, "LEAP", leap_sheet, area_name or economy_long_name, version=version)
    if coverage_diagnostics_path is not None:
        coverage_path = Path(coverage_diagnostics_path)
        coverage_path.parent.mkdir(parents=True, exist_ok=True)
        coverage_diagnostics = _build_row_coverage_diagnostics(warnings, not_needed_sheet)
        coverage_diagnostics.to_csv(coverage_path, index=False)
        if manual_missing_rows_path is not None:
            update_manual_missing_rows_file(
                diagnostics=coverage_diagnostics,
                economy=economy_code or economy_long_name,
                output_path=manual_missing_rows_path,
            )
    return warnings
