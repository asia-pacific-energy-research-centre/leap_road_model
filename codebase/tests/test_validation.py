import pandas as pd

from schemas.validation import validate_table


def _t11_rows(years: list[int]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "economy": "20_USA",
                "scenario": "Target",
                "year": year,
                "leap_branch_path": "Demand\\Passenger road",
                "variable": "Stock",
                "value": 1.0,
                "unit": "Vehicle",
            }
            for year in years
        ]
    )


def test_t11_year_validation_accepts_dynamic_base_year():
    errors = validate_table(_t11_rows(list(range(2024, 2061))), "T11_leap_ready")

    assert not any("Missing years" in error for error in errors)


def test_t11_year_validation_still_reports_internal_gap():
    years = [year for year in range(2024, 2061) if year != 2030]

    errors = validate_table(_t11_rows(years), "T11_leap_ready")

    assert "[T11] Missing years in output: [2030]..." in errors
