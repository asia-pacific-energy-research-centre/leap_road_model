#%%
"""
Gauge how far reconciled Module 1 reimport runs drift from the first model run.

This is a notebook-style utility. Edit the constants near the bottom or call
run_roundtrip_gauge_for_all() from an interactive session.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import sys

import numpy as np
import pandas as pd


# --- Paths ---

REPO_ROOT = Path(__file__).resolve().parents[1]
CODEBASE_DIR = REPO_ROOT / "codebase"
if str(CODEBASE_DIR) not in sys.path:
    sys.path.insert(0, str(CODEBASE_DIR))

from road_workflow import run_for_economy  # noqa: E402


# --- Constants ---

ALL_ECONOMIES = [
    "01_AUS", "02_BD", "03_CDA", "04_CHL", "05_PRC",
    "06_HKC", "07_INA", "08_JPN", "09_ROK", "10_MAS",
    "11_MEX", "12_NZ", "13_PNG", "14_PE", "15_PHL",
    "16_RUS", "17_SGP", "18_CT", "19_THA", "20_USA", "21_VN",
]

DEFAULTS_VERSION = "v2026_06_05_road_module1_sources"
OUTPUT_ROOT = REPO_ROOT / "results" / "roundtrip_reimport_gauge"
RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")


# --- Helpers ---

def _safe_rel_delta(abs_delta: pd.Series, denominator: pd.Series) -> pd.Series:
    denom = denominator.abs().replace(0, np.nan)
    return abs_delta / denom


def _compare_by_key(
    original: pd.DataFrame,
    reimport: pd.DataFrame,
    key_cols: list[str],
    value_col: str,
) -> pd.DataFrame:
    left = original[key_cols + [value_col]].rename(columns={value_col: "original"})
    right = reimport[key_cols + [value_col]].rename(columns={value_col: "reimport"})
    out = left.merge(right, on=key_cols, how="outer")
    out["original"] = pd.to_numeric(out["original"], errors="coerce").fillna(0.0)
    out["reimport"] = pd.to_numeric(out["reimport"], errors="coerce").fillna(0.0)
    out["abs_delta"] = (out["reimport"] - out["original"]).abs()
    out["rel_delta"] = _safe_rel_delta(out["abs_delta"], out["original"])
    return out


def _summarise_t11_aggregate(economy: str, original: pd.DataFrame, reimport: pd.DataFrame) -> pd.DataFrame:
    key_cols = ["scenario", "year", "variable"]
    left = original.groupby(key_cols, dropna=False)["value"].sum().reset_index()
    right = reimport.groupby(key_cols, dropna=False)["value"].sum().reset_index()
    compared = _compare_by_key(left, right, key_cols, "value")
    out = (
        compared.groupby("variable", dropna=False)
        .agg(
            rows=("abs_delta", "size"),
            sum_original=("original", "sum"),
            sum_reimport=("reimport", "sum"),
            max_abs_delta=("abs_delta", "max"),
            sum_abs_delta=("abs_delta", "sum"),
        )
        .reset_index()
    )
    out["sum_rel_delta"] = _safe_rel_delta(out["sum_abs_delta"], out["sum_original"])
    out.insert(0, "economy", economy)
    return out


def _summarise_t11_branch(economy: str, original: pd.DataFrame, reimport: pd.DataFrame) -> pd.DataFrame:
    key_cols = ["economy", "scenario", "leap_branch_path", "variable", "year"]
    left = original.groupby(key_cols, dropna=False)["value"].sum().reset_index()
    right = reimport.groupby(key_cols, dropna=False)["value"].sum().reset_index()
    compared = _compare_by_key(left, right, key_cols, "value")
    out = (
        compared.groupby("variable", dropna=False)
        .agg(
            rows=("abs_delta", "size"),
            changed=("abs_delta", lambda s: int((s > 1e-6).sum())),
            max_abs_delta=("abs_delta", "max"),
            p95_abs_delta=("abs_delta", lambda s: float(s.quantile(0.95))),
            max_rel_delta=("rel_delta", "max"),
            p95_rel_delta=("rel_delta", lambda s: float(s.quantile(0.95))),
        )
        .reset_index()
    )
    out.insert(0, "economy", economy)
    return out


def _summarise_t12_fuel(economy: str, original: pd.DataFrame, reimport: pd.DataFrame) -> pd.DataFrame:
    key_cols = ["economy", "scenario", "fuel"]
    compared = _compare_by_key(original, reimport, key_cols, "post_reconciliation_model_pj")
    keep_original = original[key_cols + ["esto_total_pj", "gap_pct"]].rename(columns={"gap_pct": "original_gap_pct"})
    keep_reimport = reimport[key_cols + ["gap_pct"]].rename(columns={"gap_pct": "reimport_gap_pct"})
    out = compared.merge(keep_original, on=key_cols, how="left").merge(keep_reimport, on=key_cols, how="left")
    out.insert(0, "run_economy", economy)
    return out


def _summarise_t9_fields(economy: str, original: pd.DataFrame, reimport: pd.DataFrame) -> pd.DataFrame:
    key_cols = ["economy", "scenario", "leap_branch_path"]
    rows = []
    fields = [
        "stock",
        "adjusted_stock",
        "mileage_km_per_year",
        "adjusted_mileage_km_per_year",
        "efficiency_km_per_gj",
        "adjusted_efficiency_km_per_gj",
        "final_branch_fuel_pj",
    ]
    for field in fields:
        compared = _compare_by_key(original, reimport, key_cols, field)
        rows.append({
            "economy": economy,
            "field": field,
            "rows": len(compared),
            "changed": int((compared["abs_delta"] > 1e-6).sum()),
            "max_abs_delta": float(compared["abs_delta"].max()),
            "p95_abs_delta": float(compared["abs_delta"].quantile(0.95)),
            "max_rel_delta": float(compared["rel_delta"].max(skipna=True)),
            "p95_rel_delta": float(compared["rel_delta"].quantile(0.95)),
        })
    return pd.DataFrame(rows)


def _value_from_variable_summary(df: pd.DataFrame, variable: str, column: str) -> float:
    rows = df[df["variable"].astype(str) == variable]
    if rows.empty or column not in rows.columns:
        return np.nan
    return float(rows[column].iloc[0])


def _build_economy_summary(
    economy: str,
    t11_aggregate: pd.DataFrame,
    t11_branch: pd.DataFrame,
    t12_fuel: pd.DataFrame,
    t9_fields: pd.DataFrame,
) -> dict[str, object]:
    fuel_non_electric = t12_fuel[t12_fuel["fuel"].astype(str) != "Electricity"].copy()
    return {
        "economy": economy,
        "t11_stock_sum_rel_delta": _value_from_variable_summary(t11_aggregate, "Stock", "sum_rel_delta"),
        "t11_stock_max_branch_rel_delta": _value_from_variable_summary(t11_branch, "Stock", "max_rel_delta"),
        "t11_fuel_economy_sum_rel_delta": _value_from_variable_summary(t11_aggregate, "Fuel Economy", "sum_rel_delta"),
        "t11_fuel_economy_max_branch_rel_delta": _value_from_variable_summary(t11_branch, "Fuel Economy", "max_rel_delta"),
        "t11_mileage_sum_rel_delta": _value_from_variable_summary(t11_aggregate, "Mileage", "sum_rel_delta"),
        "t11_sales_sum_rel_delta": _value_from_variable_summary(t11_aggregate, "Sales", "sum_rel_delta"),
        "t11_sales_share_sum_rel_delta": _value_from_variable_summary(t11_aggregate, "Sales Share", "sum_rel_delta"),
        "t12_max_post_model_abs_delta_pj": float(t12_fuel["abs_delta"].max()),
        "t12_max_non_electric_post_model_abs_delta_pj": float(fuel_non_electric["abs_delta"].max()) if not fuel_non_electric.empty else np.nan,
        "t12_max_reimport_gap_pct": float(t12_fuel["reimport_gap_pct"].max()),
        "t12_max_non_electric_reimport_gap_pct": float(fuel_non_electric["reimport_gap_pct"].max()) if not fuel_non_electric.empty else np.nan,
        "t9_adjusted_stock_max_rel_delta": float(t9_fields.loc[t9_fields["field"] == "adjusted_stock", "max_rel_delta"].iloc[0]),
        "t9_final_branch_fuel_pj_max_abs_delta": float(t9_fields.loc[t9_fields["field"] == "final_branch_fuel_pj", "max_abs_delta"].iloc[0]),
        "t9_final_branch_fuel_pj_max_rel_delta": float(t9_fields.loc[t9_fields["field"] == "final_branch_fuel_pj", "max_rel_delta"].iloc[0]),
    }


def run_roundtrip_gauge_for_economy(
    economy: str,
    work_root: Path,
    output_dir: Path,
    defaults_version: str = DEFAULTS_VERSION,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, object]]:
    print(f"[gauge] Running {economy}")
    economy_work = work_root / economy
    original = run_for_economy(
        economy,
        scenario="Reference",
        enable_visualisations=False,
        output_root=economy_work / "original",
        module1_defaults_version=defaults_version,
        save_csv_outputs=True,
        run_m7=False,
    )

    reimport_csv = Path(original["module1_reimport_reconciled_path"])
    package_dir = economy_work / "module1_reimport_package" / "vtest" / economy
    package_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(reimport_csv, package_dir / f"road_module1_values_{economy}.csv")

    reimport = run_for_economy(
        economy,
        scenario="Reference",
        enable_visualisations=False,
        output_root=economy_work / "reimport",
        module1_defaults_dir=economy_work / "module1_reimport_package",
        module1_defaults_version="vtest",
        save_csv_outputs=True,
        run_m7=False,
    )

    t11_aggregate = _summarise_t11_aggregate(economy, original["T11"], reimport["T11"])
    t11_branch = _summarise_t11_branch(economy, original["T11"], reimport["T11"])
    t12_fuel = _summarise_t12_fuel(economy, original["T12"], reimport["T12"])
    t9_fields = _summarise_t9_fields(economy, original["T9"], reimport["T9"])
    economy_summary = _build_economy_summary(economy, t11_aggregate, t11_branch, t12_fuel, t9_fields)

    return t11_aggregate, t11_branch, t12_fuel, t9_fields, economy_summary


def write_markdown_summary(summary: pd.DataFrame, output_path: Path) -> None:
    display_cols = [
        "economy",
        "t11_stock_sum_rel_delta",
        "t11_fuel_economy_sum_rel_delta",
        "t11_mileage_sum_rel_delta",
        "t12_max_non_electric_post_model_abs_delta_pj",
        "t12_max_non_electric_reimport_gap_pct",
        "t9_final_branch_fuel_pj_max_abs_delta",
    ]
    table = summary[display_cols].copy()
    for col in display_cols:
        if col == "economy":
            continue
        table[col] = table[col].map(lambda x: "" if pd.isna(x) else f"{float(x):.6g}")
    markdown_table = _dataframe_to_markdown_table(table)

    lines = [
        "# Reconciled Module 1 Reimport Roundtrip Gauge",
        "",
        f"Run ID: `{RUN_ID}`",
        "",
        "This compares a normal model run with a second run started from the reconciled Module 1 reimport CSV.",
        "Values are deltas from original run to reimport run.",
        "",
        markdown_table,
        "",
    ]
    output_path.write_text("\n".join(lines), encoding="utf-8")


def _dataframe_to_markdown_table(df: pd.DataFrame) -> str:
    """Format a small DataFrame as a markdown table without optional dependencies."""
    columns = [str(col) for col in df.columns]
    rows = [[str(value) for value in row] for row in df.to_numpy()]
    widths = [
        max(len(columns[i]), *(len(row[i]) for row in rows)) if rows else len(columns[i])
        for i in range(len(columns))
    ]

    def _format_row(values: list[str]) -> str:
        return "| " + " | ".join(value.ljust(widths[i]) for i, value in enumerate(values)) + " |"

    separator = "| " + " | ".join("-" * width for width in widths) + " |"
    return "\n".join([_format_row(columns), separator, *[_format_row(row) for row in rows]])


def run_roundtrip_gauge_for_all(
    economies: list[str],
    output_root: Path = OUTPUT_ROOT,
    run_id: str = RUN_ID,
    defaults_version: str = DEFAULTS_VERSION,
) -> Path:
    output_dir = output_root / run_id
    work_root = output_dir / "work"
    output_dir.mkdir(parents=True, exist_ok=True)
    work_root.mkdir(parents=True, exist_ok=True)

    t11_aggregate_rows = []
    t11_branch_rows = []
    t12_fuel_rows = []
    t9_field_rows = []
    summary_rows = []
    failures = []

    for economy in economies:
        try:
            t11_aggregate, t11_branch, t12_fuel, t9_fields, economy_summary = run_roundtrip_gauge_for_economy(
                economy,
                work_root=work_root,
                output_dir=output_dir,
                defaults_version=defaults_version,
            )
            t11_aggregate_rows.append(t11_aggregate)
            t11_branch_rows.append(t11_branch)
            t12_fuel_rows.append(t12_fuel)
            t9_field_rows.append(t9_fields)
            summary_rows.append(economy_summary)
        except Exception as exc:
            print(f"[gauge] FAILED {economy}: {exc}")
            failures.append({"economy": economy, "error": str(exc)})

    summary = pd.DataFrame(summary_rows)
    t11_aggregate = pd.concat(t11_aggregate_rows, ignore_index=True) if t11_aggregate_rows else pd.DataFrame()
    t11_branch = pd.concat(t11_branch_rows, ignore_index=True) if t11_branch_rows else pd.DataFrame()
    t12_fuel = pd.concat(t12_fuel_rows, ignore_index=True) if t12_fuel_rows else pd.DataFrame()
    t9_fields = pd.concat(t9_field_rows, ignore_index=True) if t9_field_rows else pd.DataFrame()

    summary.to_csv(output_dir / "economy_summary.csv", index=False)
    t11_aggregate.to_csv(output_dir / "t11_aggregate_by_variable.csv", index=False)
    t11_branch.to_csv(output_dir / "t11_branch_by_variable.csv", index=False)
    t12_fuel.to_csv(output_dir / "t12_fuel_check.csv", index=False)
    t9_fields.to_csv(output_dir / "t9_field_summary.csv", index=False)
    pd.DataFrame(failures).to_csv(output_dir / "failures.csv", index=False)
    write_markdown_summary(summary, output_dir / "README.md")

    print(f"[gauge] Wrote outputs to {output_dir}")
    return output_dir


#%%
# --- Run block ---

RUN_ALL_ECONOMIES = True
ECONOMIES_TO_RUN = ALL_ECONOMIES

if __name__ == "__main__" and RUN_ALL_ECONOMIES:
    run_roundtrip_gauge_for_all(ECONOMIES_TO_RUN)

#%%
