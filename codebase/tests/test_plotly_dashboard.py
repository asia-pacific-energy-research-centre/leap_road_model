import pandas as pd
import pytest

from diagnostics.plotly_dashboard import _can_plot, module3_figures, module5_figures, module6_figures, write_module_pages
from road_workflow import run_for_economy


@pytest.mark.skipif(not _can_plot(), reason="plotly not installed")
def test_module3_stock_trajectory_legend_includes_freight_vehicle_types():
    t5 = pd.DataFrame(
        [
            {"year": 2022, "transport_type": "passenger", "vehicle_type": "LPVs", "target_stock": 10.0},
            {"year": 2023, "transport_type": "passenger", "vehicle_type": "LPVs", "target_stock": 11.0},
            {"year": 2022, "transport_type": "freight", "vehicle_type": "LCVs", "target_stock": 3.0},
            {"year": 2023, "transport_type": "freight", "vehicle_type": "LCVs", "target_stock": 4.0},
            {"year": 2022, "transport_type": "freight", "vehicle_type": "Trucks", "target_stock": 2.0},
            {"year": 2023, "transport_type": "freight", "vehicle_type": "Trucks", "target_stock": 2.5},
        ]
    )

    figs = module3_figures(t5)
    stock_fig = next(item[1] for item in figs if item[0] == "Target stock trajectories")

    visible_legend_names = {trace.name for trace in stock_fig.data if trace.showlegend}
    assert visible_legend_names == {"LPVs", "LCVs", "Trucks"}


@pytest.mark.skipif(not _can_plot(), reason="plotly not installed")
def test_module3_motorisation_chart_uses_per_year_level_not_row_sum():
    # T5 repeats the same motorisation/saturation values across passenger vehicle rows.
    # The chart should show the per-year level once, not sum across those duplicated rows.
    t5 = pd.DataFrame(
        [
            {
                "year": 2022,
                "transport_type": "passenger",
                "vehicle_type": "LPVs",
                "target_stock": 1.0,
                "motorisation_level": 0.9,
                "saturation_level": 1.1,
                "original_vehicle_equivalent_weight": 1.0,
                "adjusted_vehicle_equivalent_weight": 1.0,
                "weight_calibration_applied": True,
            },
            {
                "year": 2022,
                "transport_type": "passenger",
                "vehicle_type": "Buses",
                "target_stock": 1.0,
                "motorisation_level": 0.9,
                "saturation_level": 1.1,
                "original_vehicle_equivalent_weight": 12.0,
                "adjusted_vehicle_equivalent_weight": 15.0,
                "weight_calibration_applied": True,
            },
        ]
    )

    figs = module3_figures(t5)
    motorisation_fig = next(item[1] for item in figs if item[0] == "Passenger X-LPV-equivalent vehicles vs saturation")

    line_trace = next(trace for trace in motorisation_fig.data if trace.name == "Projected X-LPV-equivalent vehicles")
    assert list(line_trace.y) == pytest.approx([900.0])

    weight_fig = next(item[1] for item in figs if item[0] == "Passenger X-LPV weight calibration")
    adjusted_trace = next(trace for trace in weight_fig.data if trace.name == "Adjusted X-LPV weight")
    assert max(adjusted_trace.y) == pytest.approx(15.0)


@pytest.mark.skipif(not _can_plot(), reason="plotly not installed")
def test_module3_population_chart_uses_macro_population_in_millions():
    t5 = pd.DataFrame(
        [
            {
                "year": 2022,
                "transport_type": "passenger",
                "vehicle_type": "LPVs",
                "target_stock": 1.0,
            }
        ]
    )
    population = pd.Series([25_000_000, 26_500_000], index=[2022, 2023])

    figs = module3_figures(t5, population=population)
    population_fig = next(item[1] for item in figs if item[0] == "Population")
    population_trace = next(trace for trace in population_fig.data if trace.name == "Population")

    assert list(population_trace.x) == [2022, 2023]
    assert list(population_trace.y) == pytest.approx([25.0, 26.5])


@pytest.mark.skipif(not _can_plot(), reason="plotly not installed")
def test_module5_base_sales_share_chart_is_horizontal_and_largest_first():
    t7 = pd.DataFrame([
        {"year": 2022, "vehicle_type": "Small", "drive_type": "ICE", "sales_share": 0.8},
        {"year": 2022, "vehicle_type": "Small", "drive_type": "BEV", "sales_share": 0.2},
        {"year": 2022, "vehicle_type": "Large", "drive_type": "ICE", "sales_share": 0.9},
        {"year": 2022, "vehicle_type": "Large", "drive_type": "BEV", "sales_share": 0.3},
    ])

    figs = module5_figures(t7, pd.DataFrame())
    fig = next(item[1] for item in figs if item[0] == "Sales shares (base-year) (2022)")

    assert fig.data[0].orientation == "h"
    assert list(fig.data[0].y) == ["Large", "Small"]


@pytest.mark.skipif(not _can_plot(), reason="plotly not installed")
def test_module6_final_fuel_share_chart_uses_t9_final_energy():
    t8 = pd.DataFrame(
        [
            {
                "vehicle_type": "LPVs",
                "drive_type": "ICE",
                "fuel": "Motor gasoline",
                "allocated_branch_fuel_pj": 99.0,
            },
            {
                "vehicle_type": "LPVs",
                "drive_type": "ICE",
                "fuel": "Electricity",
                "allocated_branch_fuel_pj": 1.0,
            },
        ]
    )
    t9 = pd.DataFrame(
        [
            {
                "vehicle_type": "LPVs",
                "drive_type": "ICE",
                "fuel": "Motor gasoline",
                "final_branch_fuel_pj": 25.0,
            },
            {
                "vehicle_type": "LPVs",
                "drive_type": "ICE",
                "fuel": "Electricity",
                "final_branch_fuel_pj": 75.0,
            },
        ]
    )

    figs = module6_figures({"T8": t8, "T9": t9})
    fig = next(item[1] for item in figs if item[0] == "Final fuel allocation share by vehicle type and drive (2022)")

    shares = {trace.name: list(trace.y)[0] for trace in fig.data}
    assert shares == pytest.approx({"Electricity": 75.0, "Motor gasoline": 25.0})


@pytest.mark.skipif(not _can_plot(), reason="plotly not installed")
def test_dashboard_diagrams_are_written_to_shared_assets(tmp_path):
    dashboard_dir = tmp_path / "results" / "05_PRC" / "diagnostics" / "dashboard"

    write_module_pages({}, dashboard_dir=dashboard_dir, economy="05_PRC")

    shared_assets = tmp_path / "results" / "shared" / "dashboard_assets"
    assert (shared_assets / "end_to_end_road_model_workflow.png").exists()
    assert (shared_assets / "road_transport_model_researcher_detail.png").exists()
    assert not (dashboard_dir / "end_to_end_road_model_workflow.png").exists()

    index_html = (dashboard_dir / "index.html").read_text(encoding="utf-8")
    assert "../../../shared/dashboard_assets/end_to_end_road_model_workflow.png" in index_html
    assert "../../../shared/dashboard_assets/road_transport_model_researcher_detail.png" in index_html
    assert "/road-model-docs/road_transport_model_simplified.md" in index_html


@pytest.mark.skipif(not _can_plot(), reason="plotly not installed")
def test_dashboard_writes_pre_and_post_reconciliation_stock_pages(tmp_path):
    dashboard_dir = tmp_path / "results" / "01_AUS" / "diagnostics" / "dashboard"
    t5_pre = pd.DataFrame(
        [
            {
                "year": 2022,
                "transport_type": "freight",
                "vehicle_type": "Trucks",
                "target_stock": 100.0,
                "gdp_elasticity_used": 0.8,
                "gdp_index": 100.0,
                "freight_raw_elasticity": 0.75,
                "freight_elasticity_clamped": False,
                "freight_energy_growth_rate": 0.015,
                "freight_gdp_growth_rate": 0.02,
                "freight_elasticity_adjustment": 1.0,
                "freight_elasticity_data_source": "historical",
                "freight_elasticity_note": "",
            },
            {
                "year": 2023,
                "transport_type": "freight",
                "vehicle_type": "Trucks",
                "target_stock": 110.0,
                "gdp_elasticity_used": 0.8,
                "gdp_index": 112.0,
                "freight_raw_elasticity": 0.75,
                "freight_elasticity_clamped": False,
                "freight_energy_growth_rate": 0.015,
                "freight_gdp_growth_rate": 0.02,
                "freight_elasticity_adjustment": 1.0,
                "freight_elasticity_data_source": "historical",
                "freight_elasticity_note": "",
            },
        ]
    )
    t5_post = t5_pre.copy()
    t5_post["target_stock"] = [80.0, 88.0]

    written = write_module_pages(
        {
            "T5_pre_reconciliation": t5_pre,
            "T5_post_reconciliation": t5_post,
            "T5": t5_post,
        },
        dashboard_dir=dashboard_dir,
        economy="01_AUS",
    )

    written_names = {path.name for path in written}
    assert "module3.html" in written_names
    assert "module3_post_reconciliation.html" in written_names

    module3_html = (dashboard_dir / "module3.html").read_text(encoding="utf-8")
    post_html = (dashboard_dir / "module3_post_reconciliation.html").read_text(encoding="utf-8")
    assert "Post-reconciliation stocks" in module3_html
    assert "Post-reconciliation stocks & turnover" in post_html
    assert "Freight stock growth assumption" in post_html
    assert "Freight stock growth compared with GDP" in post_html
    assert "Show elasticity calculation details" in post_html
    assert "Freight elasticity by vehicle type" not in post_html
    assert "Freight elasticity diagnostics" not in post_html


def test_run_for_economy_defaults_to_visualisations():
    assert run_for_economy.__defaults__[3] is None
