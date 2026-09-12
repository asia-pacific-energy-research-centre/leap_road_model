from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from road_workflow import (
    _autodiscover_future_sales_shares,
    _candidate_future_sales_paths,
    _module1_future_sales_share_rows,
    _select_future_sales_share_rows,
)


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


def test_candidate_paths_put_interface_before_leap_transport(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "leap_road_model"
    repo_root.mkdir(parents=True)
    static_dir = tmp_path / "road_model_inputs_interface" / "front-end" / "road-module1-static" / "v1"
    static_dir.mkdir(parents=True)
    static_file = static_dir / "20USA.csv"
    static_file.touch()
    monkeypatch.delenv("ROAD_MODEL_FUTURE_SALES_SHARES_PATH", raising=False)

    candidates = _candidate_future_sales_paths(
        repo_root=repo_root,
        economy="20_USA",
        scenario="Target",
    )

    leap_transport_file = (
        tmp_path / "leap_transport" / "results" / "domestic_exports"
        / "20_USA_transport_leap_export_Target.xlsx"
    )
    assert candidates.index(static_file) < candidates.index(leap_transport_file)


def test_candidate_paths_prioritise_configured_environment_path(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "leap_road_model"
    repo_root.mkdir(parents=True)
    configured = tmp_path / "configured_20_USA.csv"
    monkeypatch.setenv(
        "ROAD_MODEL_FUTURE_SALES_SHARES_PATH",
        str(tmp_path / "configured_{economy}.csv"),
    )

    candidates = _candidate_future_sales_paths(
        repo_root=repo_root,
        economy="20_USA",
        scenario="Target",
    )

    assert candidates[0] == configured


def test_module1_future_sales_rows_beat_legacy_fallback() -> None:
    module1 = pd.DataFrame([_future_sales_row(year_col="2060")])
    legacy = pd.DataFrame([{**_future_sales_row(year_col="2060"), "2060": 99.0}])

    selected, source = _select_future_sales_share_rows(
        explicit_table=None,
        module1_table=module1,
        legacy_fallback_table=legacy,
        base_year=2022,
    )

    assert source == "module1"
    assert selected is not None
    assert selected.loc[selected["year"].eq(2060), "sales_share"].iloc[0] == 25.0


def test_explicit_future_sales_rows_beat_module1() -> None:
    explicit = pd.DataFrame([{**_future_sales_row(year_col="2060"), "2060": 10.0}])
    module1 = pd.DataFrame([_future_sales_row(year_col="2060")])

    selected, source = _select_future_sales_share_rows(
        explicit_table=explicit,
        module1_table=module1,
        legacy_fallback_table=None,
        base_year=2022,
    )

    assert source == "explicit"
    assert selected is not None
    assert selected.loc[selected["year"].eq(2060), "sales_share"].iloc[0] == 10.0


def test_empty_explicit_table_does_not_silently_fall_back() -> None:
    module1 = pd.DataFrame([_future_sales_row(year_col="2060")])

    selected, source = _select_future_sales_share_rows(
        explicit_table=pd.DataFrame(),
        module1_table=module1,
        legacy_fallback_table=None,
        base_year=2022,
    )

    assert source == "explicit"
    assert selected is None


def test_legacy_future_sales_rows_are_used_when_module1_has_no_projection() -> None:
    module1 = pd.DataFrame([_future_sales_row(year_col="2022")])
    legacy = pd.DataFrame([{**_future_sales_row(year_col="2060"), "2060": 40.0}])

    selected, source = _select_future_sales_share_rows(
        explicit_table=None,
        module1_table=module1,
        legacy_fallback_table=legacy,
        base_year=2022,
    )

    assert source == "legacy_fallback"
    assert selected is not None
    assert selected.loc[selected["year"].eq(2060), "sales_share"].iloc[0] == 40.0


def test_module1_long_rows_feed_future_sales_share_projection() -> None:
    raw_leap_df = pd.DataFrame(
        [
            {
                "Branch Path": "Demand\\Passenger road\\LPVs\\ICE",
                "Variable": "Sales Share",
                "Scenario": "Target",
                "Region": "20_USA",
                "Scale": "%",
                "Units": "Share",
                "2022": 80.0,
                "2023": 75.0,
                "2060": 20.0,
            },
            {
                "Branch Path": "Demand\\Passenger road\\LPVs\\BEV",
                "Variable": "Sales Share",
                "Scenario": "Target",
                "Region": "20_USA",
                "Scale": "%",
                "Units": "Share",
                "2022": 20.0,
                "2023": 25.0,
                "2060": 80.0,
            },
        ]
    )

    future_sales = _module1_future_sales_share_rows(raw_leap_df, base_year=2022)

    assert not future_sales.empty
    assert set(future_sales["year"]) == {2023, 2060}
    assert not future_sales["drive_type"].isna().any()
    assert future_sales.loc[
        future_sales["drive_type"].eq("BEV") & future_sales["year"].eq(2060),
        "sales_share",
    ].iloc[0] == 80.0
