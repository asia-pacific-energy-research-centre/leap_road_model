from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_PATH = (
    REPO_ROOT
    / "config"
    / "test_templates"
    / "road_model_leap_export_truck_phev_synthetic_test.xlsx"
)
TRUCK_PHEV_PREFIX = r"Demand\Freight road\Trucks\PHEV"


def test_synthetic_truck_phev_reference_contract() -> None:
    metadata = pd.read_excel(REFERENCE_PATH, header=None, nrows=1)
    assert metadata.iloc[0, 5] == "PHEV TEST"

    reference = pd.read_excel(REFERENCE_PATH, header=2)
    truck_phev = reference[
        reference["Branch Path"].fillna("").astype(str).str.startswith(TRUCK_PHEV_PREFIX)
    ].copy()

    assert len(truck_phev) == 116
    assert set(pd.to_numeric(truck_phev["BranchID"])) == {-1}
    assert set(pd.to_numeric(truck_phev["ScenarioID"])) == {1, 2, 3}
    assert set(pd.to_numeric(truck_phev["RegionID"])) == {1}
    assert set(pd.to_numeric(truck_phev["VariableID"])) == {
        1061,
        1185,
        1424,
        1428,
        1661,
        1667,
        2165,
    }
    assert set(truck_phev["Scenario"]) == {"Current Accounts", "Reference", "Target"}
    assert set(
        truck_phev.loc[
            truck_phev["Branch Path"].str.count(r"\\") == 4,
            "Level 5",
        ]
    ) == {"Electricity", "Gas and diesel oil", "Biodiesel", "Efuel"}
    assert not truck_phev.duplicated(["Branch Path", "Variable", "Scenario", "Region"]).any()
