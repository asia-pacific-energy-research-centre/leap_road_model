from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "audit_drive_addition.py"
SPEC = importlib.util.spec_from_file_location("audit_drive_addition", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_expected_rows_cover_two_sizes_and_three_fuels():
    rows = MODULE.expected_rows(
        parent_path=MODULE.DEFAULT_PARENT_PATH,
        drive=MODULE.DEFAULT_DRIVE,
        sizes=MODULE.DEFAULT_SIZES,
        fuels=MODULE.DEFAULT_FUELS,
        scenario="Target",
    )

    assert len(rows) == 20
    assert (
        "Demand\\Freight road\\Trucks\\PHEV heavy",
        "Sales Share",
        "Target",
    ) in rows
    assert (
        "Demand\\Freight road\\Trucks\\PHEV medium\\Biodiesel",
        "Device Share",
        "Target",
    ) in rows
    assert all(row[2] == "Target" for row in rows)
