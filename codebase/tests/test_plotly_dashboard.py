import pytest
import pandas as pd

from diagnostics.plotly_dashboard import module3_figures, module5_figures, _can_plot


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
