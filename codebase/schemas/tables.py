"""
Data contract schemas for the road transport model.

Each schema is a dict describing a table's columns, required status, and dtype.
These are the T1–T13 schemas from the transition audit report.

Usage:
    from schemas.tables import SCHEMAS
    schema = SCHEMAS["T5_stock_targets"]
    # schema["columns"] lists required and optional columns
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Canonical dimension values
# ---------------------------------------------------------------------------

VALID_TRANSPORT_TYPES = {"passenger", "freight"}

VALID_VEHICLE_TYPES = {"LPVs", "Motorcycles", "Buses", "Trucks", "LCVs"}

VALID_DRIVE_TYPES = {"ICE", "BEV", "PHEV", "FCEV"}

VALID_SCENARIOS = {"Reference", "Target", "Current Accounts"}

VALID_SOURCE_FLAGS = {
    "researcher",
    "observed",
    "iea_ev",
    "stock_proportion",
    "regional_default",
    "global_default",
    "fallback",
    "9th_edition_model",
    "benchmark_combined_export",
}

VALID_ROAD_FUELS = {
    "Motor gasoline",
    "Gas and diesel oil",
    "LPG",
    "Natural gas",
    "LNG",
    "Electricity",
    "Hydrogen",
    "Biodiesel",
    "Biogasoline",
    "Biogas",
    "Efuel",
}

# ---------------------------------------------------------------------------
# Column spec helpers
# ---------------------------------------------------------------------------

def _col(dtype: str, required: bool = True, description: str = "") -> dict:
    return {"dtype": dtype, "required": required, "description": description}


# ---------------------------------------------------------------------------
# Table schemas T1–T13
# ---------------------------------------------------------------------------

SCHEMAS: dict[str, dict] = {

    # ------------------------------------------------------------------
    # T1 — Raw researcher input table (Module 1 input)
    # ------------------------------------------------------------------
    "T1_researcher_inputs": {
        "purpose": "Researcher-provided inputs before merging with defaults.",
        "grain": "economy × scenario × year × transport_type × vehicle_type × drive_type × variable",
        "columns": {
            "economy":         _col("str",   True,  "Economy code e.g. '01_AUS'"),
            "scenario":        _col("str",   True,  "Scenario label"),
            "year":            _col("int",   True,  "Year (base year for most variables)"),
            "transport_type":  _col("str",   True,  "'passenger' or 'freight'"),
            "vehicle_type":    _col("str",   True,  "LEAP vehicle type label"),
            "drive_type":      _col("str",   True,  "Drive type"),
            "variable":        _col("str",   True,  "Variable name"),
            "value":           _col("float", True,  "Variable value"),
            "unit":            _col("str",   True,  "Explicit unit"),
            "source_flag":     _col("str",   True,  "Always 'researcher' in this table"),
            "comment":         _col("str",   False, "Optional researcher note"),
        },
        "valid_variables": [
            "stock", "mileage", "efficiency", "saturation_level",
            "fleet_age_shift_years", "survival_multiplier",
            "freight_elasticity_override", "ev_sales_share",
            "phev_electric_utilisation_rate",
        ],
    },

    # ------------------------------------------------------------------
    # T2 — Default assumption table (Module 1 defaults)
    # ------------------------------------------------------------------
    "T2_defaults": {
        "purpose": "Documented defaults for variables that may be missing from researcher inputs.",
        "grain": "scope × variable × vehicle_type × drive_type",
        "columns": {
            "scope":               _col("str",   True,  "'global', 'regional', or economy code"),
            "variable":            _col("str",   True,  "Variable name"),
            "vehicle_type":        _col("str",   True,  "Vehicle type or 'all'"),
            "drive_type":          _col("str",   True,  "Drive type or 'all'"),
            "value":               _col("float", True,  "Default value"),
            "unit":                _col("str",   True,  "Explicit unit"),
            "source":              _col("str",   True,  "Source of the default"),
            "version":             _col("str",   True,  "Default version date"),
            "review_recommended":  _col("bool",  True,  "Whether researcher review is recommended"),
        },
    },

    # ------------------------------------------------------------------
    # T3 — Merged input table (Module 1 output)
    # ------------------------------------------------------------------
    "T3_merged_inputs": {
        "purpose": "Researcher inputs merged with defaults; source-flagged.",
        "grain": "Same as T1",
        "columns": {
            "economy":         _col("str",   True),
            "scenario":        _col("str",   True),
            "year":            _col("int",   True),
            "transport_type":  _col("str",   True),
            "vehicle_type":    _col("str",   True),
            "drive_type":      _col("str",   True),
            # size is optional: 'medium', 'large', 'heavy', or None.
            # Present when source data distinguishes LPV/Truck sizes.
            "size":            _col("str",   False, "'medium', 'large', 'heavy', or null"),
            "variable":        _col("str",   True),
            "value":           _col("float", True),
            "unit":            _col("str",   True),
            "source_flag":     _col("str",   True,  "Origin of this value"),
            "is_default":      _col("bool",  True,  "True if a default was used"),
            "default_scope":   _col("str",   False, "Scope of the default applied"),
            "comment":         _col("str",   False),
        },
        "validation_rules": [
            "value is not null",
            "unit is not null",
            "source_flag is not null",
            "efficiency > 0 where variable == 'efficiency'",
            "stock >= 0 where variable == 'stock'",
        ],
    },

    # ------------------------------------------------------------------
    # T4 — Base-year road branch table (Module 2 output)
    # ------------------------------------------------------------------
    "T4_base_year_branches": {
        "purpose": "Base-year road structure with all branches populated.",
        "grain": "economy × scenario × transport_type × vehicle_type × size × drive_type × fuel",
        "columns": {
            "economy":              _col("str",   True),
            "scenario":             _col("str",   True),
            "base_year":            _col("int",   True),
            "transport_type":       _col("str",   True),
            "vehicle_type":         _col("str",   True),
            # size: 'medium', 'large', 'heavy', or None for unsplit vehicle types
            "size":                 _col("str",   False, "'medium', 'large', 'heavy', or null"),
            "drive_type":           _col("str",   True),
            "fuel":                 _col("str",   True),
            "leap_branch_path":     _col("str",   True,  "Full backslash-separated LEAP path"),
            "stock":                _col("float", True,  "Base-year vehicle count"),
            "mileage_km_per_year":  _col("float", True,  "Annual km per vehicle"),
            "efficiency_km_per_gj": _col("float", True,  "Vehicle efficiency"),
            "stock_source_flag":    _col("str",   True),
            "mileage_source_flag":  _col("str",   True),
            "efficiency_source_flag": _col("str", True),
            # Optional
            "branch_id":                 _col("float", False, "LEAP internal branch ID (from workbook join)"),
            "vehicle_equivalent_weight": _col("float", False),
            "capacity_share":            _col("float", False),
            "stock_per_thousand_capita": _col("float", False),
        },
        "validation_rules": [
            "stock >= 0",
            "mileage_km_per_year > 0",
            "efficiency_km_per_gj > 0",
            "no duplicate (economy, scenario, transport_type, vehicle_type, size, drive_type, fuel)",
        ],
    },

    # ------------------------------------------------------------------
    # T5 — Stock target projection table (Module 3 output)
    # ------------------------------------------------------------------
    "T5_stock_targets": {
        "purpose": "Annual target stocks by vehicle type from Module 3.",
        "grain": "economy × scenario × year × transport_type × vehicle_type",
        "columns": {
            "economy":          _col("str",   True),
            "scenario":         _col("str",   True),
            "year":             _col("int",   True),
            "transport_type":   _col("str",   True),
            "vehicle_type":     _col("str",   True),
            "target_stock":     _col("float", True,  "Target vehicle count"),
            # Diagnostic columns (optional but recommended)
            "motorisation_level":     _col("float", False, "Car-equiv per capita (passenger only)"),
            "saturation_level":       _col("float", False, "Saturation car-equiv per capita"),
            "k_used":                 _col("float", False, "S-curve steepness parameter"),
            "gdp_elasticity_used":    _col("float", False, "GDP elasticity (freight only)"),
            "saturation_source_flag": _col("str",   False, "Source of saturation assumption"),
            "k_clamped":              _col("bool",  False, "True if k was clamped to bounds"),
            "is_saturated":           _col("bool",  False, "True if economy treated as saturated"),
            "original_vehicle_equivalent_weight": _col("float", False, "Pre-calibration X-LPV-equivalent weight"),
            "adjusted_vehicle_equivalent_weight": _col("float", False, "Post-calibration X-LPV-equivalent weight"),
            "weight_calibration_applied": _col("bool", False, "True if passenger saturation weight calibration ran"),
            "weight_calibration_target": _col("float", False, "Target weighted passenger stock from saturation"),
            "weight_calibration_gap": _col("float", False, "Adjusted weighted passenger stock minus target"),
        },
        "validation_rules": [
            "target_stock >= 0",
            "motorisation_level <= saturation_level unless is_saturated",
        ],
    },

    # ------------------------------------------------------------------
    # T6 — Sales, survival, and vintage table (Module 4 output)
    # ------------------------------------------------------------------
    "T6_sales_turnover": {
        "purpose": "Annual sales, retirements, and surviving stock from stock-flow accounting.",
        "grain": "economy × scenario × year × transport_type × vehicle_type",
        "columns": {
            "economy":               _col("str",   True),
            "scenario":              _col("str",   True),
            "year":                  _col("int",   True),
            "transport_type":        _col("str",   True),
            "vehicle_type":          _col("str",   True),
            "drive_type":            _col("str",   False, "Not produced by Module 4 (vehicle_type level)"),
            "target_stock":          _col("float", True,  "From Module 3"),
            "surviving_stock":       _col("float", False, "After natural survival (optional)"),
            "new_sales":             _col("float", True,  "New vehicles sold"),
            "natural_retirements":   _col("float", True,  "Natural retirements from survival curve"),
            "additional_retirements":_col("float", True,  "Policy-driven extra retirements"),
            "total_retirements":     _col("float", True,  "natural + additional"),
            "stock":                 _col("float", True,  "Final stock after all adjustments"),
            # Diagnostic: turnover_rate = new_sales / surviving_stock. Not an input.
            "turnover_rate":         _col("float", False, "new_sales / surviving_stock (diagnostic)"),
            # Optional: explicit scrappage for LEAP. Complex to implement; may be dropped.
            "scrappage_for_leap":    _col("float", False, "Policy scrappage to pass to LEAP (optional)"),
        },
        "validation_rules": [
            "stock == surviving_stock + new_sales - additional_retirements (within tolerance)",
            "all values >= 0",
            "sales_shares sum to 1 within vehicle_type",
        ],
    },

    # T6v is stored separately as a vintage profile sub-table
    "T6v_vintage_profiles": {
        "purpose": "Vintage (age distribution) profile per vehicle type and drive.",
        "grain": "economy × scenario × vehicle_type × drive_type × age",
        "columns": {
            "economy":               _col("str",   True),
            "scenario":              _col("str",   True),
            "vehicle_type":          _col("str",   True),
            "drive_type":            _col("str",   True),
            "age":                   _col("int",   True,  "Vehicle age in years"),
            "vintage_share":         _col("float", True,  "Share of fleet at this age (0-1)"),
            "survival_probability":  _col("float", True,  "Cumulative survival to this age (0-1)"),
            "age_shift_applied_years": _col("float", False, "Age shift applied"),
        },
    },

    # ------------------------------------------------------------------
    # T7 — Base-year sales share table (Module 5 output)
    # ------------------------------------------------------------------
    "T7_sales_shares": {
        "purpose": "Base-year sales shares by vehicle type and drive.",
        "grain": "economy × scenario × vehicle_type × drive_type",
        "columns": {
            "economy":           _col("str",   True),
            "scenario":          _col("str",   True),
            "vehicle_type":      _col("str",   True),
            "drive_type":        _col("str",   True),
            "sales_share":       _col("float", True,  "Share of new sales (sums to 1 within vehicle_type)"),
            "ev_sales_share_used": _col("float", True, "EV sales share before remaining allocation"),
            "source_flag":       _col("str",   True),
        },
        "validation_rules": [
            "sales_share sums to 1.0 within (economy, scenario, vehicle_type)",
            "sales_share in [0, 1]",
            "ev_sales_share_used >= 0",
        ],
    },

    # ------------------------------------------------------------------
    # T8 — Fuel allocation table (Module 6 Step 4)
    # ------------------------------------------------------------------
    "T8_fuel_allocation": {
        "purpose": "Provisional allocation of ESTO fuel totals across eligible branches.",
        "grain": "economy × scenario × transport_type × vehicle_type × drive_type × fuel",
        "columns": {
            "economy":                  _col("str",   True),
            "scenario":                 _col("str",   True),
            "transport_type":           _col("str",   True),
            "vehicle_type":             _col("str",   True),
            "drive_type":               _col("str",   True),
            "fuel":                     _col("str",   True),
            "esto_fuel_total_pj":       _col("float", True,  "Total ESTO fuel for this fuel type"),
            "phev_liquid_subtracted_pj":_col("float", True,  "PHEV liquid fuel removed"),
            "remaining_esto_fuel_pj":   _col("float", True,  "Fuel available for normal reconciliation"),
            "branch_allocation_share":  _col("float", True,  "This branch's share of remaining fuel"),
            "allocated_branch_fuel_pj": _col("float", True,  "Allocated fuel energy (provisional)"),
            "allocation_rule":          _col("str",   True,  "Rule used for allocation"),
        },
    },

    # ------------------------------------------------------------------
    # T9 — Reconciliation scalar table (Module 6 Steps 5–6)
    # ------------------------------------------------------------------
    "T9_reconciliation_scalars": {
        "purpose": "Stock, mileage, and efficiency scalars from the reconciliation step.",
        "grain": "economy × scenario × transport_type × vehicle_type × drive_type × fuel",
        "columns": {
            "economy":                    _col("str",   True),
            "scenario":                   _col("str",   True),
            "transport_type":             _col("str",   True),
            "vehicle_type":               _col("str",   True),
            "drive_type":                 _col("str",   True),
            "fuel":                       _col("str",   True),
            "initial_branch_energy_pj":   _col("float", True),
            "allocated_branch_fuel_pj":   _col("float", True),
            "energy_correction_factor":   _col("float", True),
            "stock_scalar":               _col("float", True),
            "mileage_scalar":             _col("float", True),
            "efficiency_scalar":          _col("float", True),
            "stock_weight":               _col("float", True,  "Default 0.50"),
            "mileage_weight":             _col("float", True,  "Default 0.25"),
            "efficiency_weight":          _col("float", True,  "Default 0.25"),
            "adjusted_stock":             _col("float", True),
            "adjusted_mileage_km_per_year":  _col("float", True),
            "adjusted_efficiency_km_per_gj": _col("float", True),
            "final_branch_fuel_pj":       _col("float", True),
            "scalars_within_bounds":      _col("bool",  True),
        },
    },

    # ------------------------------------------------------------------
    # T10 — Device Share table (Module 6 Step 8)
    # ------------------------------------------------------------------
    "T10_device_shares": {
        "purpose": "Final calibrated Device Shares by branch.",
        "grain": "economy × scenario × transport_type × vehicle_type × drive_type × fuel",
        "columns": {
            "economy":                    _col("str",   True),
            "scenario":                   _col("str",   True),
            "transport_type":             _col("str",   True),
            "vehicle_type":               _col("str",   True),
            "drive_type":                 _col("str",   True),
            "fuel":                       _col("str",   True),
            "leap_branch_path":           _col("str",   True),
            "implied_vehicles_using_fuel":_col("float", True),
            "adjusted_total_vehicles":    _col("float", True),
            "device_share":               _col("float", True),
        },
        "validation_rules": [
            "device_share sums to 1.0 within (economy, scenario, transport_type, vehicle_type, drive_type)",
            "device_share in [0, 1]",
            "implied_vehicles_using_fuel >= 0",
        ],
    },

    # ------------------------------------------------------------------
    # T11 — LEAP-ready output table (Module 6 final output)
    # ------------------------------------------------------------------
    "T11_leap_ready": {
        "purpose": "Complete LEAP-ready input package in tidy long format.",
        "grain": "economy × scenario × year × leap_branch_path × variable",
        "columns": {
            "economy":          _col("str",   True),
            "scenario":         _col("str",   True),
            "year":             _col("int",   True),
            "leap_branch_path": _col("str",   True,  "Full backslash-separated LEAP path"),
            "variable":         _col("str",   True,  "LEAP variable name"),
            "value":            _col("float", True),
            "unit":             _col("str",   True,  "LEAP unit string"),
        },
        "valid_variables": [
            "Sales", "Sales Share", "Stock", "Stock Share",
            "Mileage", "Average Mileage", "Fuel Economy",
            "Device Share", "Activity Level", "Final Energy Intensity",
        ],
        "validation_rules": [
            "Sales Share sums to 1 within (economy, scenario, year, vehicle_type)",
            "Device Share sums to 1 within parent branch",
            "no negative values",
            "year range 2022-2060 complete with no gaps",
        ],
    },

    # ------------------------------------------------------------------
    # T12 — Reconciliation diagnostic table (Module 6)
    # ------------------------------------------------------------------
    "T12_reconciliation_diagnostics": {
        "purpose": "Audit trail for the reconciliation. Not passed to LEAP.",
        "grain": "economy × scenario × fuel",
        "columns": {
            "economy":                     _col("str",   True),
            "scenario":                    _col("str",   True),
            "fuel":                        _col("str",   True),
            "esto_total_pj":               _col("float", True),
            "phev_liquid_pj":              _col("float", True),
            "remaining_esto_pj":           _col("float", True),
            "pre_reconciliation_model_pj": _col("float", True),
            "post_reconciliation_model_pj":_col("float", True),
            "gap_pj":                      _col("float", True),
            "gap_pct":                     _col("float", True),
            "reconciliation_status":       _col("str",   True,
                                               "'ok', 'large_adjustment', or 'failed'"),
        },
    },

    # ------------------------------------------------------------------
    # T13 — Optional Python mirror output (Module 7)
    # ------------------------------------------------------------------
    "T13_mirror_outputs": {
        "purpose": "Python mirror of LEAP road calculation for QA.",
        "grain": "economy × scenario × year × transport_type × vehicle_type × drive_type",
        "columns": {
            "economy":          _col("str",   True),
            "scenario":         _col("str",   True),
            "year":             _col("int",   True),
            "transport_type":   _col("str",   True),
            "vehicle_type":     _col("str",   True),
            "drive_type":       _col("str",   True),
            "mirror_stock":     _col("float", True),
            "mirror_vehicle_km":_col("float", True),
            "mirror_energy_pj": _col("float", True),
            "leap_stock":       _col("float", False, "LEAP extracted stock (if available)"),
            "leap_vehicle_km":  _col("float", False, "LEAP extracted activity (if available)"),
            "leap_energy_pj":   _col("float", False, "LEAP extracted energy (if available)"),
            "stock_difference": _col("float", False),
            "energy_difference_pj": _col("float", False),
        },
    },
}
