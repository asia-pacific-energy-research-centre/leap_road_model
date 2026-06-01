"""Generate the Module 1 test fixture CSV for dashboard testing.

Creates a representative dummy CSV covering all variable types that appear in a
real Module 1 defaults file. Branch definitions are data-driven so every
drive×fuel branch automatically gets Stock, Fuel Economy and Sales Share rows,
and every vehicle type gets a Mileage row. Survival rates, vintage profiles and
scalar parameters are also included.

Some rows are intentionally blank to exercise missing-row detection, and some
carry researcher comments to exercise the comments table.

Run from the repo root:
    python scripts/generate_module1_test_fixture.py
"""

import csv
import math
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "codebase" / "tests" / "fixtures" / "module1_test_dummy.csv"

HEADERS = [
    "Branch Path", "Variable", "Scenario", "Region", "Scale", "Units", "2022",
    "input_source", "source_type", "source_name", "source_scope", "default_version",
    "researcher_review_recommended", "review_reason",
]

_SRC_NAME = {
    "default":    "multinode_energy_balance",
    "researcher": "transport_model_leap_export",
}
_SRC_TYPE = {
    "default":    "default_input_workbook",
    "researcher": "transport_leap_export",
}
_INPUT_SOURCE = {
    "default":    "default_filled",
    "researcher": "transport_leap_export",
}


def _row(branch, variable, value="", scale="", units="", src="default",
         review=False, note=""):
    return {
        "Branch Path": branch,
        "Variable": variable,
        "Scenario": "Reference",
        "Region": "20_USA",
        "Scale": scale,
        "Units": units,
        "2022": str(value) if value != "" else "",
        "input_source": _INPUT_SOURCE[src],
        "source_type": _SRC_TYPE[src],
        "source_name": _SRC_NAME[src],
        "source_scope": "20_USA",
        "default_version": "v2025_01",
        "researcher_review_recommended": "True" if review else "",
        "review_reason": note,
    }


def _survival(age: int) -> float:
    return round(1 / (1 + math.exp(0.4 * (age - 12))), 4)


def _vintage_shares(n: int = 31) -> list[float]:
    raw = [max(0.0, 1 - abs(a - 8) / 12) for a in range(n)]
    total = sum(raw)
    return [round(v / total, 6) for v in raw]


VINTAGE = _vintage_shares()
N_AGES = 31


def _survival_rows(transport: str, note: str = "") -> list[dict]:
    base = f"Demand\\{transport} road"
    return [_row(f"{base}\\Age {a}", "Survival Rate", _survival(a), units="Rate", note=note)
            for a in range(N_AGES)]


def _vintage_rows(transport: str, note: str = "") -> list[dict]:
    base = f"Demand\\{transport} road"
    return [_row(f"{base}\\Age {a}", "Vintage Profile Share", VINTAGE[a], units="Share", note=note)
            for a in range(N_AGES)]


# =============================================================================
# Branch definitions
# =============================================================================
# Each entry covers one drive×fuel branch. All three per-branch measures
# (Stock, Fuel Economy, Sales Share) are generated from the same definition,
# so nothing can be accidentally omitted.
#
# Fields:
#   transport   "Passenger" | "Freight"
#   vt          vehicle type label
#   drive       drive type + size, e.g. "ICE medium"
#   fuel        fuel label, e.g. "Motor gasoline"
#   stock       2022 value (Thousand), or "" for missing
#   eff         2022 efficiency value, or "" for missing
#   eff_units   "MJ/100 km" or "km/GJ"
#   ss          sales share (fraction), or None to omit (sums ≠ 1 is fine for fixture)
#   src         "default" | "researcher"
#   review      flag researcher review recommended
#   note        review_reason text (applies to all measures for this branch)
#   stock_note  override note for stock row only
#   eff_note    override note for efficiency row only
# =============================================================================

BRANCHES = [
    # --- Passenger / LPVs -------------------------------------------------------
    dict(transport="Passenger", vt="LPVs",
         drive="ICE small",   fuel="Motor gasoline",
         stock=85000,  eff=7.2,  eff_units="MJ/100 km", ss=0.28,
         src="default"),
    dict(transport="Passenger", vt="LPVs",
         drive="ICE medium",  fuel="Motor gasoline",
         stock=135000, eff=8.5,  eff_units="MJ/100 km", ss=0.40,
         src="default",
         eff_note="Efficiency looks high for US market — EPA combined fleet average is closer to 8.0",
         eff_review=True),
    dict(transport="Passenger", vt="LPVs",
         drive="ICE large",   fuel="Motor gasoline",
         stock=28000,  eff=10.8, eff_units="MJ/100 km", ss=0.08,
         src="default"),
    dict(transport="Passenger", vt="LPVs",
         drive="HEV medium",  fuel="Motor gasoline",
         stock=9500,   eff=4.9,  eff_units="MJ/100 km", ss=0.06,
         src="default"),
    dict(transport="Passenger", vt="LPVs",
         drive="PHEV medium", fuel="Motor gasoline",
         stock=1800,   eff=5.5,  eff_units="MJ/100 km", ss=0.05,
         src="researcher"),
    dict(transport="Passenger", vt="LPVs",
         drive="PHEV medium", fuel="Electricity",
         stock=1800,   eff=380,  eff_units="km/GJ",     ss=None,
         src="researcher"),  # PHEV electricity share implicit — no separate SS
    dict(transport="Passenger", vt="LPVs",
         drive="BEV small",   fuel="Electricity",
         stock=800,    eff=490,  eff_units="km/GJ",     ss=0.05,
         src="researcher",
         stock_note="Updated from 2023 EV registration data — small BEV share higher than multinode default",
         stock_review=True),
    dict(transport="Passenger", vt="LPVs",
         drive="BEV medium",  fuel="Electricity",
         stock=2100,   eff=440,  eff_units="km/GJ",     ss=0.07,
         src="researcher",
         stock_note="Default underestimated total BEV uptake",
         stock_review=True),
    dict(transport="Passenger", vt="LPVs",
         drive="BEV large",   fuel="Electricity",
         stock=300,    eff=390,  eff_units="km/GJ",     ss=0.01,
         src="researcher"),
    dict(transport="Passenger", vt="LPVs",
         drive="FCEV medium", fuel="Hydrogen",
         stock="",     eff="",   eff_units="km/GJ",     ss=0.00,
         src="default"),   # no 2022 data — missing rows for stock + efficiency

    # --- Passenger / Motorcycles -------------------------------------------------
    dict(transport="Passenger", vt="Motorcycles",
         drive="ICE medium",  fuel="Motor gasoline",
         stock=10200,  eff=3.1,  eff_units="MJ/100 km", ss=0.92,
         src="default"),
    dict(transport="Passenger", vt="Motorcycles",
         drive="BEV medium",  fuel="Electricity",
         stock="",     eff=520,  eff_units="km/GJ",     ss=0.08,
         src="default"),   # BEV stock not yet measurable — missing

    # --- Passenger / Buses -------------------------------------------------------
    dict(transport="Passenger", vt="Buses",
         drive="ICE large",   fuel="Gas and diesel oil",
         stock=800,    eff=38,   eff_units="MJ/100 km", ss=0.88,
         src="default"),
    dict(transport="Passenger", vt="Buses",
         drive="BEV large",   fuel="Electricity",
         stock="",     eff=180,  eff_units="km/GJ",     ss=0.12,
         src="default"),   # missing stock

    # --- Freight / Trucks --------------------------------------------------------
    dict(transport="Freight", vt="Trucks",
         drive="ICE medium",  fuel="Gas and diesel oil",
         stock=4800,   eff=45,   eff_units="MJ/100 km", ss=0.55,
         src="default"),
    dict(transport="Freight", vt="Trucks",
         drive="ICE heavy",   fuel="Gas and diesel oil",
         stock=8200,   eff=62,   eff_units="MJ/100 km", ss=0.35,
         src="default"),
    dict(transport="Freight", vt="Trucks",
         drive="BEV heavy",   fuel="Electricity",
         stock="",     eff=140,  eff_units="km/GJ",     ss=0.06,
         src="default"),   # missing stock
    dict(transport="Freight", vt="Trucks",
         drive="FCEV heavy",  fuel="Hydrogen",
         stock="",     eff=120,  eff_units="km/GJ",     ss=0.04,
         src="default"),   # missing stock

    # --- Freight / LCVs ----------------------------------------------------------
    dict(transport="Freight", vt="LCVs",
         drive="ICE medium",  fuel="Motor gasoline",
         stock=11500,  eff=12,   eff_units="MJ/100 km", ss=0.45,
         src="default"),
    dict(transport="Freight", vt="LCVs",
         drive="ICE medium",  fuel="Gas and diesel oil",
         stock=3200,   eff=11,   eff_units="MJ/100 km", ss=0.30,
         src="default"),
    dict(transport="Freight", vt="LCVs",
         drive="BEV medium",  fuel="Electricity",
         stock=420,    eff=320,  eff_units="km/GJ",     ss=0.25,
         src="default"),
]

# Mileage is at vehicle-type level, not per drive/fuel.
MILEAGE = [
    dict(transport="Passenger", vt="LPVs",        value=20000,
         review=True, note="FHWA 2022 aligns with default but flagged for cross-check against state-level data"),
    dict(transport="Passenger", vt="Motorcycles", value=8200),
    dict(transport="Passenger", vt="Buses",       value=42000),
    dict(transport="Freight",   vt="Trucks",      value=75000,
         src="researcher",
         review=True, note="IEA 2023 freight mileage for HDVs — researcher estimate higher than multinode default"),
    dict(transport="Freight",   vt="LCVs",        value=24000),
]


# =============================================================================
# Generate rows from branch definitions
# =============================================================================

rows: list[dict] = []


def _branch_path(transport: str, vt: str, drive: str, fuel: str) -> str:
    return f"Demand\\{transport} road\\{vt}\\{drive}\\{fuel}"


def _vt_path(transport: str, vt: str) -> str:
    return f"Demand\\{transport} road\\{vt}"


for b in BRANCHES:
    transport = b["transport"]
    vt        = b["vt"]
    drive     = b["drive"]
    fuel      = b["fuel"]
    src       = b.get("src", "default")
    path      = _branch_path(transport, vt, drive, fuel)

    stock_review = b.get("stock_review", b.get("review", False))
    stock_note   = b.get("stock_note",   b.get("note",   ""))
    eff_review   = b.get("eff_review",   b.get("review", False))
    eff_note     = b.get("eff_note",     b.get("note",   ""))

    rows.append(_row(path, "Stock",       b["stock"], "Thousand", src=src,
                     review=stock_review, note=stock_note))
    rows.append(_row(path, "Fuel Economy", b["eff"],  units=b["eff_units"], src=src,
                     review=eff_review, note=eff_note))
    if b.get("ss") is not None:
        rows.append(_row(path, "Sales Share", b["ss"], units="Share", src=src))

for m in MILEAGE:
    rows.append(_row(
        _vt_path(m["transport"], m["vt"]), "Mileage",
        m["value"], units="km per vehicle per year",
        src=m.get("src", "default"),
        review=m.get("review", False),
        note=m.get("note", ""),
    ))


# =============================================================================
# Survival rate curves
# Passenger and freight have full curves; BEV/FCEV-specific curves are listed
# in the model structure but have no data yet (blank 2022) — 31 missing rows
# each, which should collapse to one line in the dashboard.
# A comment on passenger rows tests the age-series collapse logic.
# =============================================================================

rows.extend(_survival_rows(
    "Passenger",
    note="Sourced from 2022 IEA survival study — applies to all age steps",
))
rows.extend(_survival_rows("Freight"))

# BEV-specific passenger survival curve — no data yet
for a in range(N_AGES):
    rows.append(_row(f"Demand\\Passenger road\\BEV\\Age {a}", "Survival Rate", "", units="Rate"))

# FCEV-specific freight survival curve — no data yet
for a in range(N_AGES):
    rows.append(_row(f"Demand\\Freight road\\FCEV\\Age {a}", "Survival Rate", "", units="Rate"))

# =============================================================================
# Vintage profile shares
# A comment on freight rows tests collapse of a second profile variable.
# Hydrogen-vehicle profile listed but blank.
# =============================================================================

rows.extend(_vintage_rows("Passenger"))
rows.extend(_vintage_rows(
    "Freight",
    note="Freight age distribution updated from national truck census 2023",
))

# Hydrogen vintage profile — no data yet
for a in range(N_AGES):
    rows.append(_row(f"Demand\\Freight road\\Hydrogen\\Age {a}", "Vintage Profile Share", "", units="Share"))

# =============================================================================
# Scalar parameters
# =============================================================================

rows.append(_row("Demand\\Passenger road\\PHEV", "PHEV Electric Driving Share", 0.62,
                 units="Share", review=True,
                 note="PHEV utility factor from DOE 2023 — differs from APEC default of 0.50"))
rows.append(_row("Demand\\Passenger road", "Passenger Vehicle Saturation", 0.82, units="Device"))
rows.append(_row("Demand\\Passenger road", "Reconciliation Bound Lower", 0.80))
rows.append(_row("Demand\\Passenger road", "Reconciliation Bound Upper", 1.20))
rows.append(_row("Demand\\Freight road",   "Reconciliation Bound Lower", 0.75))
rows.append(_row("Demand\\Freight road",   "Reconciliation Bound Upper", 1.25))
rows.append(_row("Demand\\Passenger road\\Motorcycles", "Vehicle Equivalent Weight", 0.25))
rows.append(_row("Demand\\Passenger road\\Buses",       "Vehicle Equivalent Weight", 12.0))


# =============================================================================
# Validate completeness: every branch should have Stock, Fuel Economy, Sales Share
# =============================================================================

def _validate(branches: list[dict], generated: list[dict]) -> None:
    errors: list[str] = []
    for b in branches:
        path = _branch_path(b["transport"], b["vt"], b["drive"], b["fuel"])
        expected = {"Stock", "Fuel Economy"}
        if b.get("ss") is not None:
            expected.add("Sales Share")
        found = {r["Variable"] for r in generated if r["Branch Path"] == path}
        missing = expected - found
        if missing:
            errors.append(f"  {path}: missing {missing}")
    # Check every vt has Mileage
    for m in MILEAGE:
        vt_path = _vt_path(m["transport"], m["vt"])
        if not any(r["Branch Path"] == vt_path and r["Variable"] == "Mileage" for r in generated):
            errors.append(f"  {vt_path}: missing Mileage")
    if errors:
        raise AssertionError("Fixture completeness check failed:\n" + "\n".join(errors))


_validate(BRANCHES, rows)


# =============================================================================
# Write
# =============================================================================

FIXTURE.parent.mkdir(parents=True, exist_ok=True)
with open(FIXTURE, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=HEADERS)
    writer.writeheader()
    writer.writerows(rows)

n_total   = len(rows)
n_missing = sum(1 for r in rows if r["2022"] == "")
n_comments = sum(1 for r in rows if r["review_reason"])
print(f"Written {n_total} rows to {FIXTURE}")
print(f"  Rows with blank year value (missing): {n_missing}")
print(f"  Rows with researcher comment:          {n_comments}")
print("Completeness check passed.")
