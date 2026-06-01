import pytest
import pandas as pd

from diagnostics.plotly_dashboard import module3_figures, _can_plot


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
            },
            {
                "year": 2022,
                "transport_type": "passenger",
                "vehicle_type": "Buses",
                "target_stock": 1.0,
                "motorisation_level": 0.9,
                "saturation_level": 1.1,
            },
        ]
    )

    figs = module3_figures(t5)
    motorisation_fig = next(item[1] for item in figs if item[0] == "Passenger X-LPV-equivalent vehicles vs saturation")

    line_trace = next(trace for trace in motorisation_fig.data if trace.name == "Projected X-LPV-equivalent vehicles")
    assert list(line_trace.y) == pytest.approx([900.0])
