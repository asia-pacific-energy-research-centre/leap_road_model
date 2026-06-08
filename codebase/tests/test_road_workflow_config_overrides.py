from __future__ import annotations

from pathlib import Path

import pandas as pd

import adapters.esto_inputs as esto_inputs
import road_workflow
from road_workflow import RoadWorkflowInputs, run_for_economy


def test_run_for_economy_allows_module1_defaults_dir_override(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    years = [2022, 2023]
    monkeypatch.setattr(esto_inputs, "load_population", lambda economy, scenario: pd.Series([1.0, 1.1], index=years))
    monkeypatch.setattr(esto_inputs, "load_gdp", lambda economy, scenario: pd.Series([2.0, 2.2], index=years))
    monkeypatch.setattr(
        esto_inputs,
        "load_esto_road_energy",
        lambda economy: pd.DataFrame(
            [
                {"year": 2022, "transport_type": "passenger", "energy_pj": 1.0},
                {"year": 2023, "transport_type": "passenger", "energy_pj": 1.1},
            ]
        ),
    )
    monkeypatch.setattr(
        esto_inputs,
        "load_esto_fuel_totals",
        lambda economy, base_year: pd.DataFrame([{"fuel": "Electricity", "energy_pj": 1.0}]),
    )
    monkeypatch.setattr(road_workflow, "_validate_macro_inputs", lambda population, gdp, energy, years: None)

    def fake_run_with_config(config: road_workflow.RoadWorkflowConfig, inputs: RoadWorkflowInputs) -> dict:
        captured["config"] = config
        captured["inputs"] = inputs
        return {"timings": {"test": 1.0}}

    monkeypatch.setattr(road_workflow, "run_with_config", fake_run_with_config)

    module1_dir = tmp_path / "module1_defaults"
    result = run_for_economy(
        "15_PHL",
        final_year=2023,
        enable_visualisations=False,
        output_root=tmp_path / "outputs",
        auto_load_future_sales_shares=False,
        module1_defaults_dir=module1_dir,
        module1_defaults_version="v_test",
    )

    config = captured["config"]
    assert result["timings"]["test"] == 1.0
    assert isinstance(config, road_workflow.RoadWorkflowConfig)
    assert Path(config.module1_defaults_dir) == module1_dir
    assert config.module1_defaults_version == "v_test"


def test_run_for_economy_reads_workflow_defaults_yaml(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    years = [2022, 2023]

    monkeypatch.setattr(road_workflow, "_validate_macro_inputs", lambda population, gdp, energy, years: None)
    monkeypatch.setattr(
        "adapters.esto_inputs.load_population",
        lambda economy, scenario: pd.Series([1.0, 1.1], index=years),
    )
    monkeypatch.setattr(
        "adapters.esto_inputs.load_gdp",
        lambda economy, scenario: pd.Series([2.0, 2.2], index=years),
    )
    monkeypatch.setattr(
        "adapters.esto_inputs.load_esto_road_energy",
        lambda economy: pd.DataFrame(
            [
                {"year": 2022, "transport_type": "passenger", "energy_pj": 1.0},
                {"year": 2023, "transport_type": "passenger", "energy_pj": 1.1},
            ]
        ),
    )
    monkeypatch.setattr(
        "adapters.esto_inputs.load_esto_fuel_totals",
        lambda economy, base_year: pd.DataFrame([{"fuel": "Electricity", "energy_pj": 1.0}]),
    )

    def fake_run_with_config(config: road_workflow.RoadWorkflowConfig, inputs: RoadWorkflowInputs) -> dict:
        captured["config"] = config
        return {"timings": {"test": 1.0}}

    monkeypatch.setattr(road_workflow, "run_with_config", fake_run_with_config)

    config_path = tmp_path / "workflow_defaults.yaml"
    config_path.write_text(
        "\n".join(
            [
                "scenario: Target",
                "base_year: 2022",
                "final_year: 2023",
                "module1_defaults_dir: custom_module1",
                "module1_defaults_version: v_yaml",
                "enable_visualisations: false",
                "save_csv_outputs: false",
                "show_progress: false",
                "write_leap_row_diagnostics: true",
                "auto_load_future_sales_shares: false",
                "run_modules:",
                "  m7: false",
                "module6:",
                "  match_tolerance: 0.123",
                "leap_import:",
                "  export_values_in_raw_units: true",
            ]
        ),
        encoding="utf-8",
    )

    run_for_economy(
        "15_PHL",
        workflow_config_path=config_path,
        output_root=tmp_path / "outputs",
        module1_defaults_version="v_explicit",
    )

    config = captured["config"]
    assert isinstance(config, road_workflow.RoadWorkflowConfig)
    assert Path(config.module1_defaults_dir) == road_workflow._REPO_ROOT / "custom_module1"
    assert config.module1_defaults_version == "v_explicit"
    assert config.enable_visualisations is False
    assert config.save_csv_outputs is False
    assert config.show_progress is False
    assert config.write_leap_row_diagnostics is True
    assert config.run_m7 is False
    assert config.module6_match_tolerance == 0.123
    assert config.leap_import_export_values_in_raw_units is True
