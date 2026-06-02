from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from road_workflow import _autodiscover_future_sales_shares, _candidate_future_sales_paths


def _future_sales_row(year_col: str = "2025") -> dict[str, object]:
    return {
        "Branch Path": "Demand\\Passenger road\\LPVs\\BEV medium",
        "Variable": "Sales Share",
        "Scenario": "Target",
        "Region": "United States",
        "2022": 7.0,
        year_col: 25.0,
    }


def test_autodiscover_from_env_path_with_placeholders(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "leap_road_model"
    repo_root.mkdir(parents=True)

    candidate = tmp_path / "future_20_USA.csv"
    pd.DataFrame([_future_sales_row()]).to_csv(candidate, index=False)

    monkeypatch.setenv("ROAD_MODEL_FUTURE_SALES_SHARES_PATH", str(tmp_path / "future_{economy}.csv"))

    df, source = _autodiscover_future_sales_shares(
        repo_root=repo_root,
        economy="20_USA",
        base_year=2022,
    )

    assert df is not None
    assert source == candidate
    assert "2025" in df.columns


def test_autodiscover_skips_base_year_only_static_json(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "leap_road_model"
    static_dir = tmp_path / "road_model_inputs_interface" / "front-end" / "road-module1-static" / "v1"
    static_dir.mkdir(parents=True)

    payload = {"rows": [_future_sales_row(year_col="2022")]}
    (static_dir / "20USA.json").write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.delenv("ROAD_MODEL_FUTURE_SALES_SHARES_PATH", raising=False)

    df, source = _autodiscover_future_sales_shares(
        repo_root=repo_root,
        economy="20_USA",
        base_year=2022,
    )

    assert df is None
    assert source is None


def test_autodiscover_finds_static_json_with_future_years(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "leap_road_model"
    static_dir = tmp_path / "road_model_inputs_interface" / "front-end" / "road-module1-static" / "v1"
    static_dir.mkdir(parents=True)

    payload = {"rows": [_future_sales_row(year_col="2030")]}
    source_file = static_dir / "20USA.json"
    source_file.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.delenv("ROAD_MODEL_FUTURE_SALES_SHARES_PATH", raising=False)

    df, source = _autodiscover_future_sales_shares(
        repo_root=repo_root,
        economy="20_USA",
        base_year=2022,
    )

    assert source == source_file
    assert df is not None
    assert "2030" in df.columns


def test_candidate_paths_prioritise_leap_transport_domestic_export(tmp_path: Path) -> None:
    repo_root = tmp_path / "leap_road_model"
    repo_root.mkdir(parents=True)

    candidates = _candidate_future_sales_paths(
        repo_root=repo_root,
        economy="20_USA",
        scenario="Target",
    )

    assert candidates, "Expected at least one candidate path"
    expected = (
        tmp_path
        / "leap_transport"
        / "results"
        / "domestic_exports"
        / "20_USA_transport_leap_export_Target.xlsx"
    )
    assert candidates[0] == expected
