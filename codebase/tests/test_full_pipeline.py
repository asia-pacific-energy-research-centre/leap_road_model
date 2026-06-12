"""
End-to-end integration tests for the road model pipeline.

Each test calls run_for_economy() with real Module 1 defaults and ESTO macro data,
verifies the full pipeline (modules 2–6) completes without error, and checks that
the key output tables are present and non-empty.

Run just the fast smoke test (12_NZ only):
    pytest codebase/tests/test_full_pipeline.py -k smoke

Run all 21 economies (slow, ~minutes):
    pytest codebase/tests/test_full_pipeline.py -m slow
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pandas as pd
import pytest

from adapters.module1_reimport_exporter import find_module1_source_csv
from road_workflow import run_for_economy

ALL_ECONOMIES = [
    "01_AUS", "02_BD",  "03_CDA", "04_CHL", "05_PRC",
    "06_HKC", "07_INA", "08_JPN", "09_ROK", "10_MAS",
    "11_MEX", "12_NZ",  "13_PNG", "14_PE",  "15_PHL",
    "16_RUS", "17_SGP", "18_CT",  "19_THA", "20_USA", "21_VN",
]


_DEFAULTS_VERSION = "v2026_06_05_road_module1_sources"
_ROUNDTRIP_ECONOMY = os.getenv("ROAD_MODEL_ROUNDTRIP_ECONOMY", "12_NZ")
_ROUNDTRIP_TABLES = ["T5", "T6", "T9", "T10", "T11", "T12"]


def _run_and_assert(economy: str, tmp_path: Path) -> None:
    result = run_for_economy(
        economy,
        scenario="Reference",
        enable_visualisations=False,
        output_root=tmp_path / economy,
        module1_defaults_version=_DEFAULTS_VERSION,
        save_csv_outputs=False,
    )
    assert "T4" in result, f"{economy}: T4 (base-year branches) missing"
    assert "T11" in result, f"{economy}: T11 (LEAP-ready table) missing"
    assert len(result["T11"]) > 0, f"{economy}: T11 is empty"
    assert "timings" in result, f"{economy}: timings missing"
    total_time = sum(result["timings"].values())
    assert total_time > 0, f"{economy}: timings all zero"


def test_full_pipeline_smoke_nz(tmp_path: Path) -> None:
    """Fast smoke test — 12_NZ with default scenario, no visualisations."""
    _run_and_assert("12_NZ", tmp_path)


def _copy_module1_csv_to_package(
    source_csv: Path,
    package_root: Path,
    *,
    version: str,
    economy: str,
) -> Path:
    """Simulate the interface writing an uploaded Module 1 long CSV for a run."""
    dest_dir = package_root / version / economy
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_csv = dest_dir / f"road_module1_values_{economy}.csv"
    shutil.copy2(source_csv, dest_csv)
    return dest_csv


def _normalise_for_output_compare(df: pd.DataFrame, table: str) -> pd.DataFrame:
    out = df.copy()
    out = out.reindex(sorted(out.columns), axis=1)
    if out.empty:
        return out.reset_index(drop=True)
    preferred_keys = {
        "T5": ["economy", "scenario", "transport_type", "vehicle_type", "year"],
        "T6": ["economy", "scenario", "transport_type", "vehicle_type", "drive_type", "size", "year"],
        "T9": ["economy", "scenario", "leap_branch_path"],
        "T10": ["economy", "scenario", "leap_branch_path"],
        "T11": ["economy", "scenario", "leap_branch_path", "variable", "year"],
        "T12": ["economy", "scenario", "fuel"],
    }
    key_cols = [col for col in preferred_keys.get(table, []) if col in out.columns]
    if key_cols and not out.duplicated(subset=key_cols).any():
        sort_cols = key_cols
    else:
        sort_cols = list(out.columns)
    return out.sort_values(
        by=sort_cols,
        key=lambda col: col.astype(str),
        na_position="first",
    ).reset_index(drop=True)


def _output_mismatch_summary(left: pd.DataFrame, right: pd.DataFrame) -> str:
    if left.shape != right.shape:
        return f"shape {left.shape} != {right.shape}"

    parts: list[str] = []
    numeric_cols = [
        col
        for col in left.columns
        if col in right.columns
        and (
            (
                pd.api.types.is_numeric_dtype(left[col])
                and not pd.api.types.is_bool_dtype(left[col])
            )
            or (
                pd.api.types.is_numeric_dtype(right[col])
                and not pd.api.types.is_bool_dtype(right[col])
            )
        )
    ]
    for col in numeric_cols:
        left_num = pd.to_numeric(left[col], errors="coerce")
        right_num = pd.to_numeric(right[col], errors="coerce")
        delta = (left_num - right_num).abs()
        denom = right_num.abs().where(right_num.abs() > 0, 1.0)
        rel = delta / denom
        max_abs = delta.max(skipna=True)
        max_rel = rel.max(skipna=True)
        parts.append(
            f"{col}: max_abs={float(max_abs) if pd.notna(max_abs) else 0.0:.6g}, "
            f"max_rel={float(max_rel) if pd.notna(max_rel) else 0.0:.6g}"
        )

    non_numeric_cols = [col for col in left.columns if col in right.columns and col not in numeric_cols]
    mismatch_count = 0
    for col in non_numeric_cols:
        left_text = left[col].fillna("").astype(str)
        right_text = right[col].fillna("").astype(str)
        mismatch_count += int((left_text != right_text).sum())
    if mismatch_count:
        parts.append(f"non_numeric_mismatches={mismatch_count}")
    return "; ".join(parts) if parts else "values differ"


def _assert_outputs_match(
    expected: dict,
    actual: dict,
    *,
    tables: list[str],
    label: str,
    rtol: float = 1e-9,
    atol: float = 1e-6,
) -> None:
    failures = []
    for table in tables:
        if table not in expected or table not in actual:
            failures.append(f"{table}: missing from one output set")
            continue
        left = _normalise_for_output_compare(expected[table], table)
        right = _normalise_for_output_compare(actual[table], table)
        try:
            pd.testing.assert_frame_equal(
                left,
                right,
                check_dtype=False,
                check_exact=False,
                rtol=rtol,
                atol=atol,
            )
        except AssertionError:
            failures.append(f"{table}: {_output_mismatch_summary(left, right)}")

    assert not failures, f"{label} output mismatch:\n" + "\n".join(failures)


@pytest.mark.slow
def test_module1_download_upload_and_reconciled_reimport_roundtrip(tmp_path: Path) -> None:
    """
    A filled Module 1 CSV should be stable through interface-style reupload, and
    the reconciled reimport CSV produced by a run should reproduce the same outputs.
    """
    source_root = Path("input_data") / "module1_defaults"
    original_csv = find_module1_source_csv(
        source_root,
        economy=_ROUNDTRIP_ECONOMY,
        version=_DEFAULTS_VERSION,
    )

    original = run_for_economy(
        _ROUNDTRIP_ECONOMY,
        scenario="Reference",
        enable_visualisations=False,
        output_root=tmp_path / "original_run",
        module1_defaults_version=_DEFAULTS_VERSION,
        save_csv_outputs=True,
        run_m7=False,
    )
    reimport_csv = original.get("module1_reimport_reconciled_path")
    assert reimport_csv is not None, "Original run did not write a reconciled Module 1 reimport CSV."
    reimport_csv = Path(reimport_csv)
    assert reimport_csv.exists(), f"Reconciled Module 1 reimport CSV was not written: {reimport_csv}"

    upload_root = tmp_path / "uploaded_module1"
    upload_version = "uploaded_roundtrip"
    _copy_module1_csv_to_package(
        original_csv,
        upload_root,
        version=upload_version,
        economy=_ROUNDTRIP_ECONOMY,
    )
    uploaded = run_for_economy(
        _ROUNDTRIP_ECONOMY,
        scenario="Reference",
        enable_visualisations=False,
        output_root=tmp_path / "uploaded_run",
        module1_defaults_dir=upload_root,
        module1_defaults_version=upload_version,
        save_csv_outputs=False,
        run_m7=False,
    )
    _assert_outputs_match(
        original,
        uploaded,
        tables=_ROUNDTRIP_TABLES,
        label="Downloaded/reuploaded Module 1 CSV",
    )

    reimport_root = tmp_path / "reimport_module1"
    reimport_version = "reconciled_reimport_roundtrip"
    _copy_module1_csv_to_package(
        reimport_csv,
        reimport_root,
        version=reimport_version,
        economy=_ROUNDTRIP_ECONOMY,
    )
    reimported = run_for_economy(
        _ROUNDTRIP_ECONOMY,
        scenario="Reference",
        enable_visualisations=False,
        output_root=tmp_path / "reimported_run",
        module1_defaults_dir=reimport_root,
        module1_defaults_version=reimport_version,
        save_csv_outputs=False,
        run_m7=False,
    )
    _assert_outputs_match(
        original,
        reimported,
        tables=_ROUNDTRIP_TABLES,
        label="Reconciled Module 1 reimport CSV",
    )


@pytest.mark.slow
@pytest.mark.parametrize("economy", ALL_ECONOMIES)
def test_full_pipeline_all_economies(economy: str, tmp_path: Path) -> None:
    """Full run for every APEC economy using the pre-generated Module 1 defaults."""
    _run_and_assert(economy, tmp_path)
