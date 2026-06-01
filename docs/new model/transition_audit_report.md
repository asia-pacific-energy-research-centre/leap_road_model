# Road Transport Model — Transition Audit Report and Proposed Data Contracts

**Date:** 2026-05-25
**Status:** Pre-implementation reference document — do not write new model code until this is reviewed

**Design source of truth:** `road_transport_model_workflow_guide md version.md`
**Audit scope:** What existing files, code, and outputs can support the new road model, and what must the new system produce.

---

## Contents

1. [Existing LEAP transport output inventory](#1-existing-leap-transport-output-inventory)
2. [LEAP workbook structure summary](#2-leap-workbook-structure-summary)
3. [Existing LEAP transport code inventory](#3-existing-leap-transport-code-inventory)
4. [9th edition transport output inventory](#4-9th-edition-transport-output-inventory)
5. [Lower-priority legacy context summary](#5-lower-priority-legacy-context-summary)
6. [Mapping from old system to new workflow modules](#6-mapping-from-old-system-to-new-workflow-modules)
7. [Proposed new data contracts](#7-proposed-new-data-contracts)
8. [Adapter functions needed](#8-adapter-functions-needed)
9. [Recommended implementation order](#9-recommended-implementation-order)
10. [Human review questions](#10-human-review-questions)

---

## 1. Existing LEAP transport output inventory

### Source location

`C:\Users\Work\github\leap_transport\results\combined_exports`

### Files inspected

22 Excel workbooks, one per APEC economy plus one APEC aggregate. All dated 20260514.

File naming pattern:
```
transport_leap_export_combined_{NN}_{ECON_CODE}_domestic_international_{TIMESTAMP}.xlsx
```

Economies covered: 00_APEC (aggregate), 01_AUS through 21_VN. All 21 individual APEC members present.

### Sheet structure

Each workbook contains two sheets:

**LEAP sheet** (2,493 rows × 21 columns)
- LEAP-compact format. Data stored as `Data(year, value, year, value, ...)` expression strings.
- This is the machine-readable format LEAP expects for import.

**FOR_VIEWING sheet** (2,493 rows × 56 columns)
- Same rows as LEAP sheet but with the expression column unpacked into individual year columns (approximately 38 columns, one per year 2022–2060).
- Human-readable; not the import format.

### Core columns (LEAP sheet)

| Column | Content |
|--------|---------|
| BranchID | LEAP internal branch identifier |
| VariableID | LEAP internal variable identifier |
| ScenarioID | LEAP internal scenario identifier |
| RegionID | LEAP internal region identifier |
| Branch Path | Full LEAP hierarchy path |
| Variable | Measure name |
| Scenario | Scenario label |
| Region | Economy name (long form, e.g. "Japan") |
| Scale | Unit scale multiplier |
| Units | Measurement unit |
| Per... | Per-unit specification |
| Expression | `Data(2022, v1, 2023, v2, ..., 2060, v39)` |
| Level 1–8 | Branch hierarchy decomposition |

### Years and scenarios

- **Year range:** 2022–2060 (39 annual time steps)
- **Base year:** 2022
- **Scenarios:** Current Accounts (ScenarioID=1), Reference (ScenarioID=2), Target (ScenarioID=3)

### Variables exported for road transport

12 variables are exported per branch:

| Variable | Units | Aggregation |
|----------|-------|-------------|
| Sales | Device (vehicles) | Sum |
| Sales Share | Share | Share |
| Stock | Device (vehicles) | Sum |
| Stock Share | Share | Share |
| Activity Level | Passenger-km or Tonne-km | Sum |
| Average Mileage | Kilometer | Weighted (Stocks) |
| Mileage | Kilometer | Weighted (Stocks) |
| Final On-Road Mileage | Kilometer | Weighted (Stocks) |
| Fuel Economy | MJ/100 km | Weighted (Activity) |
| Final On-Road Fuel Economy | MJ/100 km | Weighted (Activity) |
| Device Share | Share | Share |
| Final Energy Intensity | MJ/passenger-km or MJ/tonne-km | Weighted (Activity) |

**Unit note:** LEAP uses MJ/100 km for efficiency. The workflow guide uses km/GJ. Conversion: `km/GJ = 10,000 / (MJ/100km)`. This conversion must be applied at the LEAP export step.

### Road transport branch structure in exports

Demand hierarchy: `Transport Type → Vehicle Type → Technology+Size → Fuel`

**Passenger road vehicle types present:** LPVs, Buses, Motorcycles

**LPV technology-size-fuel combinations (examples):**
- `Demand\Passenger road\LPVs\ICE small\Motor gasoline`
- `Demand\Passenger road\LPVs\BEV small\Electricity`
- `Demand\Passenger road\LPVs\PHEV medium\Electricity`
- `Demand\Passenger road\LPVs\PHEV medium\Motor gasoline`
- `Demand\Passenger road\LPVs\HEV large\Gas and diesel oil`
- `Demand\Passenger road\LPVs\EREV small\Electricity`

**Bus technology-fuel combinations (examples):**
- `Demand\Passenger road\Buses\ICE\Gas and diesel oil`
- `Demand\Passenger road\Buses\BEV\Electricity`
- `Demand\Passenger road\Buses\FCEV\Hydrogen`

**Motorcycles (examples):**
- `Demand\Passenger road\Motorcycles\ICE\Motor gasoline`
- `Demand\Passenger road\Motorcycles\BEV\Electricity`

**Freight road vehicle types present:** Trucks, LCVs

**Trucks (examples):**
- `Demand\Freight road\Trucks\ICE heavy\Gas and diesel oil`
- `Demand\Freight road\Trucks\BEV medium\Electricity`
- `Demand\Freight road\Trucks\FCEV heavy\Hydrogen`

**LCVs (examples):**
- `Demand\Freight road\LCVs\ICE\Motor gasoline`
- `Demand\Freight road\LCVs\BEV\Electricity`

Total road transport leaf branches: approximately 250+ per economy (including biofuel variants).

### Downstream usefulness

These files are the primary benchmark for the new system. The new road model must be able to reproduce or improve on:
- The same 12 variables
- The same branch structure
- The same year range (2022–2060)
- The same expression format
- The same 21 economies

---

## 2. LEAP workbook structure summary

### Source location

`C:\Users\Work\github\leap_transport\data\import_files\DEFAULT_transport_leap_import_TGT_REF_CA.xlsx`

### Structure

Single sheet named **"Export"** with 5,515 rows × 30 columns.

Row layout:
- Row 1: Metadata header (Area, Version)
- Row 2: Blank separator
- Row 3: Column headers
- Row 4+: Data rows

### Required columns

| Column | Header | Description |
|--------|--------|-------------|
| 3 | BranchID | LEAP internal branch ID |
| 4 | VariableID | LEAP internal variable ID |
| 5 | ScenarioID | 1=Current Accounts, 2=Reference, 3=Target |
| 6 | RegionID | LEAP internal region ID |
| 7 | Branch Path | Full backslash-separated path |
| 8 | Variable | Variable name |
| 9 | Scenario | Scenario label text |
| 10 | Region | Economy long name |
| 11 | Scale | Scale multiplier |
| 12 | Units | Units string |
| 13 | Per... | Per-unit (e.g. "Vehicle") |
| 14 | Expression | `Data(year, value, ...)` string |
| 15 | (blank) | Separator |
| 16–21 | Level 1–6 | Branch hierarchy decomposed |

### Branch path format

```
Demand\{Transport Type}\{Vehicle Type}\{Technology}\{Fuel}
```

Examples:
```
Demand\Passenger road\LPVs\ICE small\Motor gasoline
Demand\Passenger road\Buses\BEV\Electricity
Demand\Freight road\Trucks\ICE heavy\Gas and diesel oil
Demand\Freight road\LCVs\BEV\Electricity
```

The backslash separator is significant. LEAP treats each segment as a distinct tree node.

### Expression format

```
Data(2022, 0, 2023, 8.77273e+07, 2024, 8.41715e+07, ..., 2060, 3.69785e+06)
```

Rules:
- Alternating year-value pairs
- No gaps in years allowed
- Scientific notation acceptable
- Entire time series for a branch-variable in one string

### Whether the workbook structure should influence intermediate data contracts

Yes — it should. The recommended approach is:

- Intermediate tables use **tidy/long format** with explicit columns per dimension.
- The final LEAP export step converts tidy long format into the `Data(...)` expression strings.
- This keeps intermediate tables readable and testable while the LEAP export step is isolated and replaceable.

The workbook structure defines the required output dimensions:
`economy × scenario × branch_path × variable × year × value`

which maps cleanly to:
`economy × scenario × transport_type × vehicle_type × drive_type × fuel × variable × year × value`

Modules 1–6 should use this tidy schema. The LEAP export adapter is the only step that writes `Data(...)` strings.

---

## 3. Existing LEAP transport code inventory

### Source location

`C:\Users\Work\github\leap_transport\codebase`

### Directory structure summary

```
codebase/
├── lifecycle_profile_workflow.py   ← standalone lifecycle entrypoint
├── sales_workflow.py               ← policy-aware sales estimation
├── transport_workflow.py           ← main domestic pipeline entrypoint
├── international_transport_workflow.py
├── config/
│   ├── transport_economy_config.py ← economy/scenario config
│   ├── basic_mappings.py           ← source data taxonomy and fuel mappings
│   ├── branch_mappings.py          ← LEAP branch path definitions
│   └── branch_expression_mapping.py← LEAP expression mappings
├── functions/
│   ├── sales_curve_estimate.py     ← core sales/turnover maths
│   ├── lifecycle_profile_editor.py ← profile manipulation and Excel I/O
│   ├── preprocessing.py            ← data cleaning helpers
│   ├── measures.py                 ← LEAP measure definitions
│   ├── measure_processing.py       ← measure processing pipelines
│   ├── leap_utilities_functions.py ← LEAP API wrappers
│   ├── transport_branch_paths.py   ← LEAP branch path management
│   ├── merged_energy_io.py         ← ESTO energy loading
│   ├── workflow_utilities.py       ← shared workflow utilities
│   ├── transport_workflow_pipeline.py ← main orchestration (LEAP-coupled)
│   └── [others]
└── results_analysis/               ← post-processing and dashboards
```

### Reusable functions

#### `lifecycle_profile_workflow.py` — REUSE DIRECTLY

**`run_with_config()`** — Entrypoint for survival curve editing and vintage profile generation. Orchestrates `lifecycle_profile_editor` functions. Keep as-is; it is already a clean wrapper.

Key assumption embedded: Steady-state vintage under constant stock and stationary survival. Vintage sums to 100% at base year (age=0).

#### `lifecycle_profile_editor.py` — REUSE DIRECTLY (with minor I/O adaptation)

All functions are reusable. Key functions:

| Function | Purpose | Status |
|----------|---------|--------|
| `load_lifecycle_profile_excel()` | Load LEAP-format profiles | Keep |
| `save_lifecycle_profile_excel()` | Save to LEAP format | Keep |
| `scale_age_band()` | Scale profile values in an age range | Keep |
| `smooth_profile()` | Moving-average smoothing | Keep |
| `apply_lifecycle_type_rules()` | Enforce monotonicity/normalisation constraints | Keep |
| `survival_profile_to_vintage_profile()` | Steady-state vintage from survival | Keep |
| `build_vintage_from_survival_excel()` | Main workflow: survival → vintage | Keep |
| `convert_cumulative_survival_to_annual()` | Cohort mechanics helper | Keep |
| `check_sum_100()`, `renormalize_to_100()` | Normalisation | Keep |

Excel format expected by these functions:
```
Row 0:  Area:       <area_name>
Row 1:  Profile:    <profile_name>
Row 2:  (blank)
Row 3:  Year        Value
Row 4+: <age>       <value>
```

Sheet name: "Lifecycle Profiles". Values in percentages (0–100).

Key assumption: Annual survival probability `p(age) = S(age+1) / S(age)` where S is cumulative survival.

#### `sales_workflow.py` — MIXED (some keep, some replace)

**Functions to keep and port directly:**

| Function | Purpose | Status | Notes |
|----------|---------|--------|-------|
| `derive_vehicle_turnover_policies_from_drive_policy()` | Convert drive-level policy to vehicle bucket retirement rates using stock shares | **Keep** | Core policy derivation; pure Python; excellent diagnostics |
| `derive_initial_fleet_age_shift_vintage_profiles()` | Shift base-year vintage profile forward/backward in age | **Keep** | Pure Python; directly supports Module 4.4 |
| `compute_sales_from_stock_targets()` | Cohort-based stock-flow: target stock → surviving stock → required sales | **Keep** | Core turnover; clean; handles policy parameters |
| `_merge_turnover_policies()` | Combine two policy dicts additively | **Keep** | Supports Module 4.6 |
| `_subtract_turnover_policies()` | Subtract one policy from another | **Keep** | Supports Module 4.6 |
| `_coerce_year_schedule()` | Normalise scalar/dict/Series inputs to pd.Series by year | **Keep** | Utility; clean |
| `_coerce_age_profile()` | Normalise various age-profile inputs | **Keep** | Utility; clean |
| `_shift_vintage_profile_by_age_years()` | Shift vintage profile by N years | **Keep** | Helper for age shifting |
| `_average_age_from_vintage_profile()` | Compute mean age from age-share profile | **Keep** | Diagnostic utility |

**Functions to simplify or replace:**

| Function | Problem | Status |
|----------|---------|--------|
| `build_passenger_sales_for_economy()` | High-level wrapper that mixes S-curve envelope, stock targeting, policy, and turnover in one call; too hard to test in isolation | **Refactor into separate functions** |
| `build_freight_sales_for_economy()` | Same problem as passenger | **Refactor into separate functions** |
| `derive_vehicle_turnover_policies_from_checkpoint()` | Reads from a pickle checkpoint; checkpoint format is 9th edition specific | **Replace with new input format** |
| `estimate_passenger_sales_from_files()`, `estimate_freight_sales_from_files()` | File path wrappers for 9th edition format | **Replace with new input format** |
| `run_passenger_policy_from_checkpoint()` | Same checkpoint dependency | **Replace** |

Recommended refactor for passenger/freight wrappers: extract the S-curve envelope logic into a standalone `estimate_passenger_motorisation_envelope()` function and a separate `project_stock_from_motorisation_envelope()` function, then call `compute_sales_from_stock_targets()` directly. This maps cleanly onto Modules 3 and 4 in the new guide.

#### `sales_curve_estimate.py` — REUSE DIRECTLY (replace I/O only)

Contains the core mathematical logic. All mathematical functions are reusable.

| Function | Purpose | Status |
|----------|---------|--------|
| `logistic_envelope_from_base()` | Generate S-curve from M_base, M_sat, k, base_year | **Keep** |
| `estimate_recent_energy_growth()` | Geometric average growth rate over recent years | **Keep** |
| `estimate_k_from_energy_trend()` | Calibrate k from energy growth rate | **Keep** |
| `load_survival_curve()`, `load_vintage_profile()` | Excel I/O for lifecycle profiles | **Keep math, adapt I/O** |
| `compute_base_capacity_index()` | Calculate M_base and capacity-weighted shares | **Keep** |
| `envelope_to_target_stocks()` | Convert M(year) → vehicle-specific stock targets | **Keep** |
| `initialise_cohorts()` | Create base-year cohort matrix from vintage profile | **Keep** |
| `compute_sales_from_stock_targets()` | Legacy version without policy; superseded by sales_workflow.py version | **Use sales_workflow.py version** |

#### `preprocessing.py` — REUSE AFTER SIMPLIFICATION

- `calculate_sales()` — Stock differencing (ΔStock). Simple but ignores turnover; use as reference.
- `allocate_fuel_alternatives_energy_and_activity()` — Fuel split logic. The pattern is reusable for Module 6.

#### `config/basic_mappings.py` — ADAPT

Contains `SOURCE_CSV_TREE`: the nested taxonomy of transport_type → medium → vehicle_type → drive → fuel. This is the most useful mapping reference in the codebase.

Key vehicle-type-to-model-bucket mapping embedded in this file:
```
car, suv, lt  →  LPV
2w            →  MC (Motorcycles)
bus           →  Bus (Buses)
ht, mt        →  Trucks
lcv           →  LCVs
```

Fuel names in this file match LEAP fuel names: "Motor gasoline", "Gas and diesel oil", "Electricity", "Hydrogen", "Natural gas", "LPG", "Biodiesel", "Biogasoline", "Biogas", "LNG", "Efuel", etc.

#### `config/transport_economy_config.py` — ADAPT

Contains economy/scenario config with base years per economy. Base year 2022 for most economies. Needs to be updated for new system configuration.

#### Functions to replace entirely

| Component | Reason for replacement |
|-----------|----------------------|
| `transport_workflow_pipeline.py` | Tightly LEAP-coupled orchestration; architecture is 9th edition specific |
| `measures.py`, `measure_processing.py` | LEAP-specific measure catalog |
| `leap_utilities_functions.py` | LEAP API wrappers |
| `transport_branch_paths.py` | LEAP branch path definitions; need to be rewritten for new system |
| `branch_mappings.py` | LEAP-specific; contains 300+ branch definitions for the old model |
| `branch_expression_mapping.py` | LEAP formula syntax; old model specific |

### LEAP naming conventions from codebase

**Economy codes:** `{01-21}_{ABBREVIATION}` — e.g., "12_NZ", "20_USA", "01_AUS". Synthetic aggregate: "00_APEC".

**Scenarios:** "Target", "Reference" (capital first letter; case-sensitive in LEAP).

**Vehicle type buckets (model-internal):**
- Passenger: "LPV", "MC", "Bus"
- Freight: "Trucks", "LCVs"

**LEAP branch vehicle type labels:**
- Passenger: "LPVs", "Motorcycles", "Buses"
- Freight: "Trucks", "LCVs"

**Drive types (source level):** `ice_g`, `ice_d`, `bev`, `phev_g`, `phev_d`, `fcev`, `hev`, `cng`, `lpg`, `lng`, `erev_g`, `erev_d`

**Drive groups used in policy code:**
```python
"ice":    ("ice_d", "ice_g")
"hybrid": ("hev", "hev_d", "hev_g")
"phev":   ("phev_d", "phev_g")
"ev":     ("bev", "fcev", "erev_d", "erev_g", "phev_d", "phev_g")
```

**Primary data structures:** `pd.Series` (indexed by year or age), `pd.DataFrame`, `dict[str, pd.Series]` (vehicle-type → series), `dict[int, float]` (age → survival/vintage value).

---

## 4. 9th edition transport output inventory

### Source locations

- `C:\Users\Work\github\leap_transport\data\transport_data_9th\model_output_detailed_2`
- `C:\Users\Work\github\leap_transport\data\transport_data_9th\model_output_with_fuels`

### model_output_detailed_2

21 CSV files, one per economy. Named `{NN}_{ECON}_NON_ROAD_DETAILED_model_output{DATE}.csv`.

Note: Despite the "NON_ROAD" label in the filename, these files contain ALL modes (road, rail, ship, air).

**Columns (36 total):** Economy, Date, Medium, Vehicle Type, Transport Type, Drive, Scenario, Efficiency, Energy, Mileage, Stocks_old, Activity, Occupancy_or_load, Intensity, Activity_per_Stock, Travel_km, Stocks, Activity_efficiency_improvement, Average_age, Gdp, Gdp_per_capita, New_vehicle_efficiency, Population, Surplus_stocks, Stocks_per_thousand_capita, Turnover_rate, Age_distribution, Unit, Data_available, Measure, Vehicle_sales_share, Stock_turnover, New_stocks_needed, Non_road_intensity_improvement, Activity_growth.

**Years:** 2022–2100

**Categorical dimensions:**

| Dimension | Values |
|-----------|--------|
| Economies | 01_AUS through 21_VN |
| Scenarios | Reference, Target |
| Transport types | passenger, freight |
| Mediums | road, rail, ship, air |
| Passenger vehicle types | 2w, lt, suv, car, bus |
| Freight vehicle types | lcv, mt, ht |
| Road drive types | ice_g, ice_d, cng, lpg, bev, phev_g, phev_d, fcev |

**Units:**
- Energy: MJ
- Activity: passenger-km or tonne-km
- Efficiency: MJ/km
- Stocks: vehicles

**Key issues with this structure:**
1. Energy in MJ, not PJ — conversion needed
2. `Age_distribution` is a comma-delimited nested list stored in a single CSV cell — requires careful parsing
3. Wide format with 36 columns; many are 0 or empty for non-applicable mode/vehicle combinations
4. Contains GDP and Population alongside transport data — useful for Module 3

**Validation usefulness:** These files provide base-year stock, mileage, efficiency, and activity values for all economies in 2022. They are useful as a cross-check for Module 2 base-year structure preparation.

### model_output_with_fuels

21 CSV files, one per economy. Long/normalised format.

**Columns (9):** Date, Economy, Scenario, Transport Type, Vehicle Type, Drive, Medium, Fuel, Energy

**Years:** 2022–2100

**Fuel codes (APEC format):**
`01_x_thermal_coal`, `07_01_motor_gasoline`, `07_07_gas_diesel_oil`, `07_09_lpg`, `08_01_natural_gas`, `08_02_lng`, `16_01_biogas`, `16_05_biogasoline`, `16_06_biodiesel`, `16_x_ammonia`, `16_x_efuel`, `16_x_hydrogen`, `17_electricity`

**Units:** Energy in MJ

**Key uses:**
- Historical ESTO road energy by fuel by economy (needed for Module 3 energy trend calibration)
- Energy by fuel for 2022 base year (needed for Module 6 reconciliation starting point)
- Long-format fuel data is the cleaner form; prefer over model_output_detailed_2 for fuel-level queries

**Key issue:** Energy values are 9th edition model outputs, not raw ESTO. For Module 3, the new system should use raw ESTO data where possible. These model outputs can serve as a fallback or cross-check.

### Which outputs to use as validation benchmarks

| Output file | Benchmark use |
|-------------|--------------|
| model_output_detailed_2 | Base-year stocks, mileage, efficiency — cross-check for Module 2 |
| model_output_with_fuels | Base-year fuel split — cross-check for Module 6 fuel allocation |
| combined_exports | Final LEAP output structure and values — primary benchmark for the new system |

---

## 5. Lower-priority legacy context summary

### Economy naming (canonical)

All repos use the same numbering: `{01-21}_{ABBREVIATION}` with the following full list:

```
01_AUS  Australia
02_BD   Brunei Darussalam
03_CDA  Canada
04_CHL  Chile
05_PRC  China (People's Republic)
06_HKC  Hong Kong, China
07_INA  Indonesia
08_JPN  Japan
09_ROK  Korea
10_MAS  Malaysia
11_MEX  Mexico
12_NZ   New Zealand
13_PNG  Papua New Guinea
14_PE   Peru
15_PHL  Philippines
16_RUS  Russia
17_SGP  Singapore
18_CT   Chinese Taipei
19_THA  Thailand
20_USA  United States of America
21_VN   Viet Nam
```

Aggregate codes: `00_APEC`, `22_SEA` (Southeast Asia), `23_NEA` (Northeast Asia), `24_OAM`, `25_OCE`, `26_NA`.

**Note:** `multinode_energy_balance` drops the underscore after the number (`01AUS` not `01_AUS`). This is a naming inconsistency to watch for when using multinode outputs.

### Scenario naming

"Reference" and "Target" (capital first letter). Internally: ScenarioID 2 = Reference, ScenarioID 3 = Target.

### Standard multi-index (transport_data_system)

The transport_data_system combined_data output uses this standard long-form index:
```
economy, date, medium, measure, vehicle_type, unit, transport_type, drive, fuel
```

with a `value` column and metadata columns (`dataset`, `source`, `comment`).

This is a useful reference for how to structure the new Module 1 raw input tables.

### Fuel codes from transport_data_system

The combined_data file uses these drive types for road:
`all, bev, cng, fcev, ice_d, ice_g, lng, lpg, phev_d, phev_g`

These match the source-level drive types in basic_mappings.py.

### Key assumptions embedded in old system

- Turnover rate default: 3% per year
- Logistic (S-curve) function enabled via `USE_LOGISTIC_FUNCTION = True`
- COVID exclusion for 2020–2022 in energy trend calibration
- Vehicle-equivalent weights: LPV=1.0, two-wheeler=0.3–0.8, bus=20.0 (economy-specific)
- Base year: 2022 for most economies; 2021 for Russia (in some files)
- Survival curves: referenced in calculation functions, not stored in standalone config tables

### Useful data sources referenced

- EGEDA (energy data by transport type)
- IEA EV Explorer (electric vehicle stocks, 2022 update)
- ATO (Automobile Technical Observatory, vehicle efficiency)
- National statistics: Korea, Mexico, Singapore, Indonesia, Philippines, New Zealand
- ITEM database (freight activity)
- IEA World Energy Balances (fuel classification, APEC fuel codes)

### multinode_energy_balance — useful context

This repo contains a web application for bottom-up/top-down energy balance reconciliation. The most relevant piece for the new road model is:

**`road_module1_defaults.py`** in `back-end/core/` — generates economy-specific vehicle stock/activity templates with:
- Default drive technology shares by vehicle type (e.g., passenger cars: 68% ICE gasoline, 8% diesel, 7% BEV)
- Efficiency maps (MJ/km) per drive type
- Annual mileage assumptions per vehicle type

These defaults are named `DEFAULT_VERSION = "v2026_05_25_best_guess"` and stored in `back-end/outputs/road_module1_defaults/`. This is directly useful as a starting point for Module 1 default assumptions.

The APEC energy balance dataset used in this repo (`00APEC_2024_low_with_subtotals.csv`, 36 MB, 1990–2022) is also relevant as the ESTO road energy source needed by Module 3.

**LEAP export format in multinode:** The multinode LEAP export workbook uses a similar structure to the combined_exports but at a less detailed vehicle-type level. The column layout is:
`Economy, Year, Sector Flow, LEAP Branch Path, Node Weight, Efficiency (COP), Final Energy Demand, Useful Energy, Macro Driver, Driver Value, Energy Intensity`

This is more aggregated than the new road model needs, but the LEAP Branch Path format is consistent: backslash-separated hierarchy, e.g., `Road Freight\Heavy Truck\Diesel ICE`.

---

## 6. Mapping from old system to new workflow modules

### Module 1 — Road input data and defaults

| Item | Source | Classification | Reason |
|------|--------|----------------|--------|
| Default efficiency by vehicle type and drive | `multinode_energy_balance/back-end/core/road_module1_defaults.py` | **Reuse after simplification** | Good starting defaults; needs to be extracted into a standalone YAML or CSV |
| Default mileage by vehicle type | Same | **Reuse after simplification** | Same |
| Default drive technology shares | Same | **Reuse as reference** | Too economy-specific for direct use; review before applying |
| Economy/scenario configuration | `transport_economy_config.py` | **Reuse after simplification** | Update file paths and add researcher override fields |
| Standard input schema | `transport_data_system/combined_data_DATE20250122.csv` | **Use as reference** | Column structure informs Module 1 input schema; do not copy directly |
| Source flag pattern | `transport_data_system` selection logic | **Use as reference** | The `dataset`, `source`, `comment` pattern is useful |
| Vehicle-equivalent weights | `sales_workflow.py` (DEFAULT_VEHICLE_WEIGHTS dict) | **Reuse directly** | Already matches workflow guide defaults (LPV=1.0, MC=0.3, Bus=20.0) |

### Module 2 — Base-year road structure and calibration preparation

| Item | Source | Classification | Reason |
|------|--------|----------------|--------|
| Base-year stocks | `model_output_detailed_2` (Stocks column, 2022 rows) | **Use as reference** | Economy-specific base-year stocks; verify against raw data |
| Base-year mileage | `model_output_detailed_2` (Mileage column, 2022 rows) | **Use as reference** | Same |
| Base-year efficiency | `model_output_detailed_2` (Efficiency column, 2022 rows) | **Use as reference** | Convert MJ/km → km/GJ |
| Vehicle-type-to-LEAP-bucket mapping | `config/basic_mappings.py` (SOURCE_CSV_TREE) | **Reuse directly** | This is the canonical taxonomy; clean and reusable |
| Fuel-to-drive mapping | `config/basic_mappings.py` | **Reuse directly** | Identifies which fuels are valid for which drive types |
| LEAP branch path template | `results/combined_exports` branch structure | **Reuse directly** | Defines the required output branch structure |
| Branch mapping table | `config/branch_mappings.py` | **Use as reference** | Contains 300+ branch definitions but too LEAP-specific; use to understand the needed structure, then rebuild |

### Module 3 — Stock target projection

| Item | Source | Classification | Reason |
|------|--------|----------------|--------|
| `logistic_envelope_from_base()` | `sales_curve_estimate.py` | **Reuse directly** | Core S-curve maths; already implements Module 3.1 logic |
| `estimate_recent_energy_growth()` | `sales_curve_estimate.py` | **Reuse directly** | Implements g_E calculation described in guide |
| `estimate_k_from_energy_trend()` | `sales_curve_estimate.py` | **Reuse directly** | Implements k estimation from g_E and M_base/M_sat |
| `compute_base_capacity_index()` | `sales_curve_estimate.py` | **Reuse directly** | Calculates M_base from observed stocks and weights |
| `envelope_to_target_stocks()` | `sales_curve_estimate.py` | **Reuse directly** | Converts M_envelope → vehicle-specific target stocks |
| k bounds (k_min=0.0, k_max=0.15) | `sales_workflow.py` function signatures | **Reuse directly** | Already matches workflow guide defaults |
| COVID year exclusion logic | `sales_workflow.py` and `sales_curve_estimate.py` | **Reuse directly** | Excludes 2020–2022 from trend estimation |
| Historical ESTO road energy | `model_output_with_fuels` | **Use as reference** | Useful fallback; prefer raw ESTO from multinode data |
| ESTO APEC energy balance data | `multinode_energy_balance/back-end/data/00APEC_2024_low_with_subtotals.csv` | **Reuse directly** | This is the right historical energy source for Module 3 trend calibration |
| GDP and Population data | `model_output_detailed_2` (Gdp, Population columns) | **Use as reference** | Embedded in 9th edition outputs; should use official macro source if available |
| Freight GDP elasticity logic | `build_freight_sales_for_economy()` in sales_workflow.py | **Reuse after simplification** | Implements Module 3.2 logic; extract the elasticity calculation as a standalone function |

### Module 4 — Sales, survival, vintage, and turnover policy

| Item | Source | Classification | Reason |
|------|--------|----------------|--------|
| `compute_sales_from_stock_targets()` | `sales_workflow.py` (policy-aware version) | **Reuse directly** | Core Module 4.1 stock-flow calculation |
| `initialise_cohorts()` | `sales_curve_estimate.py` | **Reuse directly** | Creates base-year cohort matrix from vintage profile |
| `derive_vehicle_turnover_policies_from_drive_policy()` | `sales_workflow.py` | **Reuse directly** | Module 4.5 |
| `derive_initial_fleet_age_shift_vintage_profiles()` | `sales_workflow.py` | **Reuse directly** | Module 4.4 |
| `_merge_turnover_policies()` | `sales_workflow.py` | **Reuse directly** | Module 4.6 |
| `_subtract_turnover_policies()` | `sales_workflow.py` | **Reuse directly** | Module 4.6 |
| `build_vintage_from_survival_excel()` | `lifecycle_profile_editor.py` | **Reuse directly** | Converts researcher-supplied survival curves into LEAP-compatible vintage profiles |
| `survival_profile_to_vintage_profile()` | `lifecycle_profile_editor.py` | **Reuse directly** | Core survival→vintage conversion |
| `apply_lifecycle_type_rules()` | `lifecycle_profile_editor.py` | **Reuse directly** | Validates monotonicity and normalisation |
| Survival and vintage Excel format | `lifecycle_profile_editor.py` | **Reuse directly** | LEAP expects this specific format |
| `drive_policy_counterfactual_turnover_policies` pattern | `sales_workflow.py` | **Reuse after simplification** | Module 4.6 counterfactual tooling |
| `_coerce_year_schedule()`, `_coerce_age_profile()` | `sales_workflow.py` | **Reuse directly** | Utility helpers |
| `scale_age_band()`, `smooth_profile()` | `lifecycle_profile_editor.py` | **Reuse directly** | Profile manipulation utilities |

### Module 5 — Vehicle sales share preparation

| Item | Source | Classification | Reason |
|------|--------|----------------|--------|
| EV sales shares from IEA | `transport_data_system` (IEA EV Explorer source) | **Use as reference** | Provides observed EV sales share data by economy |
| Stock-proportion allocation logic | `preprocessing.py` | **Reuse after simplification** | Pattern for allocating remaining sales shares using stock proportions |
| `vehicle_shares` parameter handling | `sales_workflow.py` | **Reuse after simplification** | The vehicle_shares dict pattern is reusable; extract the normalisation logic |

### Module 6 — LEAP handoff, fuel allocation, reconciliation, and Device Shares

| Item | Source | Classification | Reason |
|------|--------|----------------|--------|
| ESTE fuel-to-branch eligibility logic | `config/basic_mappings.py` (SOURCE_CSV_TREE) | **Reuse after simplification** | Defines which fuels are valid for which vehicle-drive branches |
| `allocate_fuel_alternatives_energy_and_activity()` | `preprocessing.py` | **Use as reference** | Fuel allocation pattern; new version should implement the workflow guide's step-by-step method |
| Energy reconciliation logic | `energy_use_reconciliation_road.py` | **Use as reference** | Contains existing reconciliation approach; new system should implement the simultaneous stock/mileage/efficiency method from the guide |
| LEAP import workbook writer | `apec_mapping_workbook.py` | **Use as reference** | Understand output format; replace with new adapter |
| Historical exports | `historical_exports.py` | **Use as reference** | Understand combined_exports generation; replace |
| combined_exports expression format | `results/combined_exports` | **Reuse as reference** | Defines the exact `Data(year, value, ...)` format required |

### Module 7 — Optional Python mirror and validation

| Item | Source | Classification | Reason |
|------|--------|----------------|--------|
| Python mirror calculations | `transport_workflow_pipeline.py` | **Use as reference** | Some mirror logic exists but is entangled with LEAP coupling |
| Validation structure | `results_analysis/` | **Use as reference** | Charts and dashboard patterns reusable |
| All core Module 4 functions | `sales_workflow.py`, `sales_curve_estimate.py` | **Reuse directly** | Mirror can use the same turnover engine |

---

## 7. Proposed new data contracts

All tables use tidy/long format. All column names use `lowercase_snake_case`. Year is an integer. Economy uses the canonical `NN_XXX` format.

### Common dimension values

| Dimension | Canonical values |
|-----------|-----------------|
| `economy` | `"01_AUS"` … `"21_VN"`, `"00_APEC"` |
| `scenario` | `"Reference"`, `"Target"`, `"Current Accounts"` |
| `transport_type` | `"passenger"`, `"freight"` |
| `vehicle_type` | `"LPVs"`, `"Motorcycles"`, `"Buses"`, `"Trucks"`, `"LCVs"` |
| `drive_type` | `"ICE"`, `"BEV"`, `"PHEV"`, `"FCEV"` |
| `fuel` | `"Motor gasoline"`, `"Gas and diesel oil"`, `"Electricity"`, `"Hydrogen"`, `"Natural gas"`, `"LPG"`, `"Biodiesel"`, `"Biogasoline"`, `"Biogas"`, `"LNG"`, `"Efuel"` |
| `source_flag` | `"researcher"`, `"observed"`, `"iea_ev"`, `"stock_proportion"`, `"regional_default"`, `"global_default"`, `"fallback"` |

---

### T1 — Raw researcher input table

**Purpose:** Collect all researcher-provided inputs before merging with defaults.

**Grain:** One row per economy × scenario × year × transport_type × vehicle_type × drive_type × variable.

**Required columns:**

| Column | Type | Description |
|--------|------|-------------|
| `economy` | str | Economy code |
| `scenario` | str | Scenario label |
| `year` | int | Year (base year only for most variables) |
| `transport_type` | str | `"passenger"` or `"freight"` |
| `vehicle_type` | str | LEAP vehicle type label |
| `drive_type` | str | Drive type |
| `variable` | str | Variable name (see list below) |
| `value` | float | Variable value |
| `unit` | str | Explicit unit |
| `source_flag` | str | Always `"researcher"` in this table |
| `comment` | str | Optional researcher note |

**Variables in this table:**
`stock`, `mileage`, `efficiency`, `saturation_level`, `fleet_age_shift_years`, `survival_multiplier`, `freight_elasticity_override`, `ev_sales_share`, `phev_electric_utilisation_rate`

---

### T2 — Default assumption table

**Purpose:** Store documented defaults for every variable that may be missing from researcher inputs.

**Grain:** One row per scope × variable. Scope can be global, regional, or economy-specific.

**Required columns:**

| Column | Type | Description |
|--------|------|-------------|
| `scope` | str | `"global"`, `"regional"`, or economy code |
| `variable` | str | Variable name |
| `vehicle_type` | str | Vehicle type or `"all"` |
| `drive_type` | str | Drive type or `"all"` |
| `value` | float | Default value |
| `unit` | str | Explicit unit |
| `source` | str | Source of the default |
| `version` | str | Default version date |
| `review_recommended` | bool | Whether researcher review is recommended |

---

### T3 — Merged input table (Module 1 output)

**Purpose:** Researcher inputs merged with defaults; source-flagged.

**Grain:** Same as T1.

**Required columns:** All T1 columns, plus:

| Column | Type | Description |
|--------|------|-------------|
| `source_flag` | str | Origin of this value |
| `is_default` | bool | True if a default was used |
| `default_scope` | str | Scope of the default applied, if any |

**Validation rules:**
- All economies present for all required variables
- No null values in `value`, `unit`, `source_flag`
- `efficiency` > 0
- `stock` >= 0

---

### T4 — Base-year road branch table (Module 2 output)

**Purpose:** Base-year road structure with all branches populated, ready for stock projection and reconciliation.

**Grain:** One row per economy × scenario × transport_type × vehicle_type × drive_type × fuel (base year only).

**Required columns:**

| Column | Type | Description |
|--------|------|-------------|
| `economy` | str | Economy code |
| `scenario` | str | Scenario label |
| `base_year` | int | Base year |
| `transport_type` | str | Transport type |
| `vehicle_type` | str | LEAP vehicle type label |
| `drive_type` | str | Drive type |
| `fuel` | str | Fuel name |
| `leap_branch_path` | str | Full LEAP branch path |
| `stock` | float | Base-year vehicle count |
| `mileage_km_per_year` | float | Annual km per vehicle |
| `efficiency_km_per_gj` | float | Vehicle efficiency |
| `stock_source_flag` | str | Data source for stock |
| `mileage_source_flag` | str | Data source for mileage |
| `efficiency_source_flag` | str | Data source for efficiency |

**Optional columns:**
`vehicle_equivalent_weight`, `capacity_share`, `stock_per_thousand_capita`

**Validation rules:**
- All LEAP branch paths must be valid (present in branch template)
- `stock` >= 0, `mileage_km_per_year` > 0, `efficiency_km_per_gj` > 0
- No duplicate branch rows per economy × scenario

---

### T5 — Stock target projection table (Module 3 output)

**Purpose:** Annual target stocks by vehicle type from motorisation envelope and GDP elasticity.

**Grain:** One row per economy × scenario × year × transport_type × vehicle_type.

**Required columns:**

| Column | Type | Description |
|--------|------|-------------|
| `economy` | str | Economy code |
| `scenario` | str | Scenario label |
| `year` | int | Year |
| `transport_type` | str | Transport type |
| `vehicle_type` | str | LEAP vehicle type label |
| `target_stock` | float | Target vehicle count |

**Optional/diagnostic columns:**
`motorisation_level`, `saturation_level`, `k_used`, `gdp_elasticity_used`, `saturation_source_flag`, `k_clamped` (bool), `is_saturated` (bool)

**Validation rules:**
- `target_stock` >= 0
- Passenger `motorisation_level` <= `saturation_level` unless explicitly flagged
- `k_used` within [k_min, k_max]
- No negative values

---

### T6 — Sales, survival, and vintage table (Module 4 output)

**Purpose:** Annual sales, retirements, surviving stock, and vintage profile from stock-flow accounting.

**Grain:** One row per economy × scenario × year × transport_type × vehicle_type × drive_type for aggregate columns. Vintage profile stored as a separate schema (T6v).

**Required columns:**

| Column | Type | Description |
|--------|------|-------------|
| `economy` | str | Economy code |
| `scenario` | str | Scenario label |
| `year` | int | Year |
| `transport_type` | str | Transport type |
| `vehicle_type` | str | LEAP vehicle type label |
| `drive_type` | str | Drive type |
| `target_stock` | float | From Module 3 |
| `surviving_stock` | float | After natural survival |
| `new_sales` | float | New vehicles sold |
| `natural_retirements` | float | Natural retirements from survival curve |
| `additional_retirements` | float | Policy-driven extra retirements |
| `total_retirements` | float | natural + additional |
| `stock` | float | Final stock after all adjustments |
| `scrappage_for_leap` | float | Explicit scrappage to pass to LEAP |

**Validation rules:**
- `stock` = `surviving_stock` + `new_sales` - `additional_retirements` (stock accounting identity)
- All values >= 0
- `surviving_stock` <= `target_stock` unless surplus rule applies
- Sales shares must sum to 1 within vehicle type

**T6v — Vintage profile sub-table:**

| Column | Type | Description |
|--------|------|-------------|
| `economy` | str | Economy code |
| `scenario` | str | Scenario label |
| `vehicle_type` | str | LEAP vehicle type label |
| `drive_type` | str | Drive type |
| `age` | int | Vehicle age in years |
| `vintage_share` | float | Share of fleet at this age (0–1) |
| `survival_probability` | float | Cumulative survival to this age (0–1) |
| `age_shift_applied_years` | float | Age shift applied (0 if none) |

---

### T7 — Base-year sales share table (Module 5 output)

**Purpose:** Base-year sales shares by vehicle type and drive before LEAP entry.

**Grain:** One row per economy × scenario × vehicle_type × drive_type.

**Required columns:**

| Column | Type | Description |
|--------|------|-------------|
| `economy` | str | Economy code |
| `scenario` | str | Scenario label |
| `vehicle_type` | str | LEAP vehicle type label |
| `drive_type` | str | Drive type |
| `sales_share` | float | Share of new sales (sums to 1 within vehicle_type) |
| `ev_sales_share_used` | float | EV sales share before remaining allocation |
| `source_flag` | str | Source flag |

**Validation rules:**
- `sales_share` sums to 1.0 within each economy × scenario × vehicle_type
- All `sales_share` values in [0, 1]
- EV sales share not negative

---

### T8 — Fuel allocation table (Module 6 step 4 output)

**Purpose:** Provisional allocation of ESTO fuel totals across eligible branches before reconciliation.

**Grain:** One row per economy × scenario × transport_type × vehicle_type × drive_type × fuel.

**Required columns:**

| Column | Type | Description |
|--------|------|-------------|
| `economy` | str | Economy code |
| `scenario` | str | Scenario label |
| `transport_type` | str | Transport type |
| `vehicle_type` | str | LEAP vehicle type label |
| `drive_type` | str | Drive type |
| `fuel` | str | Fuel name |
| `esto_fuel_total_pj` | float | Total ESTO fuel for this fuel type |
| `phev_liquid_subtracted_pj` | float | PHEV liquid fuel already removed |
| `remaining_esto_fuel_pj` | float | Fuel available for normal reconciliation |
| `branch_allocation_share` | float | This branch's share of remaining ESTO fuel |
| `allocated_branch_fuel_pj` | float | Allocated fuel energy (provisional) |
| `allocation_rule` | str | Rule used (e.g., `"stock_share"`, `"initial_energy_share"`) |

---

### T9 — Reconciliation scalar table (Module 6 steps 5–6 output)

**Purpose:** Stock, mileage, and efficiency scalars from the reconciliation step.

**Grain:** One row per economy × scenario × transport_type × vehicle_type × drive_type × fuel.

**Required columns:**

| Column | Type | Description |
|--------|------|-------------|
| `economy` | str | Economy code |
| `scenario` | str | Scenario label |
| `transport_type` | str | Transport type |
| `vehicle_type` | str | LEAP vehicle type label |
| `drive_type` | str | Drive type |
| `fuel` | str | Fuel name |
| `initial_branch_energy_pj` | float | Before reconciliation |
| `allocated_branch_fuel_pj` | float | Target after allocation |
| `energy_correction_factor` | float | allocated / initial |
| `stock_scalar` | float | Applied stock scalar |
| `mileage_scalar` | float | Applied mileage scalar |
| `efficiency_scalar` | float | Applied efficiency scalar |
| `stock_weight` | float | Weight used for stock (default 0.50) |
| `mileage_weight` | float | Weight used for mileage (default 0.25) |
| `efficiency_weight` | float | Weight used for efficiency (default 0.25) |
| `adjusted_stock` | float | Post-reconciliation stock |
| `adjusted_mileage_km_per_year` | float | Post-reconciliation mileage |
| `adjusted_efficiency_km_per_gj` | float | Post-reconciliation efficiency |
| `final_branch_fuel_pj` | float | Recalculated energy after adjustment |
| `scalars_within_bounds` | bool | Whether all scalars stayed within configured bounds |

---

### T10 — Device Share table (Module 6 step 8 output)

**Purpose:** Final calibrated Device Shares by branch.

**Grain:** One row per economy × scenario × transport_type × vehicle_type × drive_type × fuel.

**Required columns:**

| Column | Type | Description |
|--------|------|-------------|
| `economy` | str | Economy code |
| `scenario` | str | Scenario label |
| `transport_type` | str | Transport type |
| `vehicle_type` | str | LEAP vehicle type label |
| `drive_type` | str | Drive type |
| `fuel` | str | Fuel name |
| `leap_branch_path` | str | Full LEAP branch path |
| `implied_vehicles_using_fuel` | float | Derived from final branch energy |
| `adjusted_total_vehicles` | float | Total vehicles in this branch |
| `device_share` | float | implied_vehicles / adjusted_total |

**Validation rules:**
- `device_share` sums to 1.0 within each parent branch (transport_type × vehicle_type × drive_type)
- All `device_share` values in [0, 1]
- No negative `implied_vehicles_using_fuel`

---

### T11 — LEAP-ready output table (Module 6 final output)

**Purpose:** Complete LEAP-ready input package, ready for conversion to LEAP import workbook format.

**Grain:** One row per economy × scenario × year × leap_branch_path × variable.

**Required columns:**

| Column | Type | Description |
|--------|------|-------------|
| `economy` | str | Economy code |
| `scenario` | str | Scenario label |
| `year` | int | Year |
| `leap_branch_path` | str | Full backslash-separated LEAP path |
| `variable` | str | LEAP variable name |
| `value` | float | Variable value |
| `unit` | str | LEAP unit string |

**Variables in this table:**
`Sales`, `Sales Share`, `Stock`, `Mileage`, `Fuel Economy`, `Device Share`, `Activity Level`, `Final Energy Intensity`

**Note:** `Mileage` unit is `"Kilometer"`. `Fuel Economy` unit is `"MJ/100 km"` (converted from km/GJ). `Sales` and `Stock` unit is `"Device"`. `Device Share` unit is `"Share"`.

**Validation rules:**
- All required LEAP branch paths present
- Sales Shares sum to 1 within vehicle type
- Device Shares sum to 1 within parent branch
- No negative values
- Year range 2022–2060 complete with no gaps

---

### T12 — Reconciliation diagnostic table (Module 6)

**Purpose:** Audit trail for the reconciliation; not passed to LEAP.

**Grain:** One row per economy × scenario × fuel.

**Required columns:**

| Column | Type | Description |
|--------|------|-------------|
| `economy` | str | Economy code |
| `scenario` | str | Scenario label |
| `fuel` | str | Fuel name |
| `esto_total_pj` | float | ESTO observed fuel total |
| `phev_liquid_pj` | float | PHEV liquid fuel removed before reconciliation |
| `remaining_esto_pj` | float | Remaining for normal reconciliation |
| `pre_reconciliation_model_pj` | float | Model energy before adjustment |
| `post_reconciliation_model_pj` | float | Model energy after adjustment |
| `gap_pj` | float | Residual gap |
| `gap_pct` | float | Gap as % of ESTO total |
| `reconciliation_status` | str | `"ok"`, `"large_adjustment"`, `"failed"` |

---

### T13 — Optional Python mirror output (Module 7)

**Purpose:** Python mirror of LEAP road calculation for QA.

**Grain:** One row per economy × scenario × year × transport_type × vehicle_type × drive_type.

**Required columns:**

| Column | Type | Description |
|--------|------|-------------|
| `economy` | str | Economy code |
| `scenario` | str | Scenario label |
| `year` | int | Year |
| `transport_type` | str | Transport type |
| `vehicle_type` | str | LEAP vehicle type label |
| `drive_type` | str | Drive type |
| `mirror_stock` | float | Python mirror stock |
| `mirror_vehicle_km` | float | Python mirror activity |
| `mirror_energy_pj` | float | Python mirror energy |
| `leap_stock` | float | LEAP extracted stock (if available) |
| `leap_vehicle_km` | float | LEAP extracted activity (if available) |
| `leap_energy_pj` | float | LEAP extracted energy (if available) |
| `stock_difference` | float | mirror - LEAP |
| `energy_difference_pj` | float | mirror - LEAP |

---

## 8. Adapter functions needed

These adapters translate between existing file formats and the new data contracts. Adapters should be kept separate from core model logic.

### A1 — `parse_leap_export_expressions()`

**Purpose:** Convert `Data(year, value, ...)` expression strings from combined_exports into tidy long format (T11 schema).

**Input:** Path to combined_export Excel workbook.
**Output:** DataFrame with columns `[economy, scenario, leap_branch_path, variable, year, value, unit]`.
**When to use:** Loading combined_exports for benchmark comparison.

### A2 — `load_combined_exports_as_benchmark()`

**Purpose:** Load all combined_export files from `results/combined_exports/` and produce a benchmark table for comparing new model outputs.

**Input:** Directory path, optional economy filter.
**Output:** Tidy DataFrame in T11 schema with a `source="benchmark_combined_export"` flag.
**When to use:** Validation — comparing new model outputs against existing benchmark.

### A3 — `load_leap_import_workbook_as_template()`

**Purpose:** Read `DEFAULT_transport_leap_import_TGT_REF_CA.xlsx` and extract branch paths, variable names, and scenarios as a validation template.

**Input:** Workbook path.
**Output:** DataFrame of all `[leap_branch_path, variable, scenario, unit]` combinations that the new system must populate.
**When to use:** Validating that Module 6 output covers all required LEAP branches.

### A4 — `load_9th_edition_detailed_output()`

**Purpose:** Load a `model_output_detailed_2` CSV for one or more economies and return base-year road rows in T4 schema.

**Input:** Directory path, economy list, base_year (default 2022).
**Output:** DataFrame in T4 schema with `source_flag="9th_edition_model"`.
**Conversions needed:**
- MJ/km → km/GJ: `efficiency_km_per_gj = 1000 / efficiency_mj_per_km`
- Vehicle type mapping: `{car, suv, lt} → LPVs`, `{2w} → Motorcycles`, `{bus} → Buses`, `{ht, mt} → Trucks`, `{lcv} → LCVs`
- Drive type mapping: `{ice_g, ice_d} → ICE`, `{bev} → BEV`, `{phev_g, phev_d} → PHEV`, `{fcev} → FCEV`
**When to use:** Populating Module 2 base-year structure when researcher data is unavailable.

### A5 — `load_9th_edition_fuel_output()`

**Purpose:** Load `model_output_with_fuels` for one or more economies and return road energy by fuel in a schema compatible with Module 6 ESTO input.

**Input:** Directory path, economy list.
**Output:** DataFrame with `[economy, scenario, year, transport_type, vehicle_type, drive_type, fuel, energy_pj]`.
**Conversions needed:**
- MJ → PJ: `energy_pj = energy_mj / 1e6`
- APEC fuel codes → LEAP fuel names: `07_01_motor_gasoline → "Motor gasoline"`, `07_07_gas_diesel_oil → "Gas and diesel oil"`, `17_electricity → "Electricity"`, `16_x_hydrogen → "Hydrogen"`, `08_01_natural_gas → "Natural gas"`, etc.
**When to use:** Module 6 fuel reconciliation when ESTO data is not directly available.

### A6 — `load_transport_data_system_output()`

**Purpose:** Load `combined_data_DATE20250122.csv` and extract road rows for specified economies, returning a T3-compatible input table.

**Input:** CSV path, economy list, variable list.
**Output:** DataFrame in T3 schema with `source_flag` mapped from the `dataset` column.
**When to use:** Module 1 — populating default inputs from the transport data system outputs.

### A7 — `wrap_sales_workflow_output()`

**Purpose:** Convert the dict output of `build_passenger_sales_for_economy()` or `build_freight_sales_for_economy()` into T6 schema rows.

**Input:** Result dict from sales_workflow.py functions, economy, scenario.
**Output:** DataFrame in T6 schema.
**When to use:** During Module 4 while the old high-level wrappers are still in use. Replaced when Module 4 is rebuilt around modular functions.

### A8 — `convert_to_leap_expression()`

**Purpose:** Convert a tidy time series (year, value pairs) into a LEAP `Data(...)` expression string.

**Input:** `pd.Series` indexed by year.
**Output:** String `"Data(2022, v1, 2023, v2, ..., 2060, v39)"`.
**When to use:** Final LEAP export step.

### A9 — `write_leap_import_workbook()`

**Purpose:** Convert T11 tidy output into the LEAP import workbook format (two sheets: LEAP and FOR_VIEWING).

**Input:** T11 DataFrame, output path, template workbook path.
**Output:** Excel workbook matching the structure of `DEFAULT_transport_leap_import_TGT_REF_CA.xlsx`.
**Conversions needed:**
- `efficiency_km_per_gj → MJ/100km`: `mj_per_100km = 10_000 / efficiency_km_per_gj`
- PJ → MJ for energy values: `mj = pj * 1e6`
- Tidy rows → `Data(...)` expression strings via A8
**When to use:** Module 6 final output.

### A10 — `load_multinode_road_defaults()`

**Purpose:** Load the economy-specific road Module 1 defaults from `multinode_energy_balance` outputs and return as T2 (default assumption table).

**Input:** `multinode_energy_balance/back-end/outputs/road_module1_defaults/` directory path, economy list.
**Output:** DataFrame in T2 schema.
**When to use:** Module 1 — populating default efficiency and mileage assumptions.

---

## 9. Recommended implementation order

### Phase 0 — Schemas, adapters, and test economy (before any module code)

1. Define all schemas (T1–T13) as Python dataclasses or validation functions with `pandera` or plain assertions.
2. Implement adapters A1–A10.
3. Load combined_exports for one economy using A2 — confirm T11 schema produces the expected rows.
4. Load LEAP import workbook using A3 — produce the complete branch × variable template.
5. Build a tiny test economy dataset (suggest: 12_NZ or 17_SGP — smaller, well-documented) with manually specified base-year stocks, mileage, efficiency, and ESTO fuel totals.

### Phase 1 — Module 3: Stock target projection

6. Port `estimate_recent_energy_growth()`, `estimate_k_from_energy_trend()`, `logistic_envelope_from_base()` into a standalone `module3_passenger_stock_projection.py`.
7. Implement freight GDP elasticity as a standalone function.
8. Run on the test economy. Compare projected stock levels to combined_exports Stock variable using A2 benchmark.
9. Add diagnostics (T5 optional columns) and required plots.

### Phase 2 — Module 4: Sales, survival, vintage

10. Port `compute_sales_from_stock_targets()` and vintage/survival helpers into `module4_sales_turnover.py`. Do not yet refactor the high-level wrappers.
11. Use A7 to wrap existing `build_passenger_sales_for_economy()` output into T6 for the test economy.
12. Port `derive_vehicle_turnover_policies_from_drive_policy()` and `derive_initial_fleet_age_shift_vintage_profiles()` into Module 4.
13. Validate stock accounting identity: `stock = surviving_stock + new_sales - additional_retirements`.
14. Add LEAP scrappage output column (`scrappage_for_leap`) explicitly.

### Phase 3 — Module 5: Base-year sales shares

15. Implement `module5_sales_shares.py` using EV sales share defaults from transport_data_system and stock-proportion fallback.
16. Validate sales shares sum to 1.0 within each vehicle type.

### Phase 4 — Module 6: LEAP handoff structure and fuel allocation

17. Implement branch eligibility table from `basic_mappings.py` `SOURCE_CSV_TREE`.
18. Implement fuel allocation rules (T8) for the test economy.
19. Implement PHEV electricity/liquid split (T8 step 2 intermediate).
20. Validate that all ESTO fuel totals are covered and no fuel has zero eligible branches.

### Phase 5 — Module 6: Reconciliation and Device Shares

21. Implement scalar reconciliation (T9) with iterative simultaneous stock/mileage/efficiency adjustment.
22. Implement Device Share calculation (T10).
23. Implement T12 diagnostic table.
24. Validate against combined_exports Device Share variable using A2.

### Phase 6 — Module 6: Final LEAP export

25. Implement A8 `convert_to_leap_expression()`.
26. Implement A9 `write_leap_import_workbook()`.
27. Produce a complete LEAP import workbook for the test economy.
28. Compare against `DEFAULT_transport_leap_import_TGT_REF_CA.xlsx` structure using A3 template.

### Phase 7 — Modules 1 and 2: Input data and defaults

29. Implement Module 1 using T1, T2, T3 schemas. Connect to Fabian's researcher input tool when ready.
30. Implement Module 2 base-year branch table (T4). Use A4, A5 adapters to populate from 9th edition data where researcher data is absent.

### Phase 8 — Scale to all economies

31. Run phases 1–6 for all 21 economies.
32. Compare all combined_export benchmarks using A2.
33. Flag economies where k is clamped, saturation assumptions differ, or reconciliation fails.

### Phase 9 — Module 7 (optional, later)

34. Implement Python mirror in `module7_mirror_validation.py` using T13 schema.
35. Do not require LEAP extraction for the first implementation.

---

## 10. Human review questions

### Category A — Mapping ambiguities
> some things you may not have realsied: we want to remove EREV from all drive types, as well as HEVs. EREVs will be considered as a efficiency improvemnt on phevs, and simialr for HEVs to ICES. This is because the sales share of EREVs and HEVs is very small but they still use the same fuels as PHEVs and ICEs. We will also remove the small category for LPVs, and just detail medium and large. 
> it is important that even though we are reducing the types, the new system should be flexible enough to add more types in the future if needed. For example, if we want to some of these categories back in.
**A1.** The workflow guide uses "two-wheelers" but LEAP uses "Motorcycles" (and the existing code uses "MC" internally). The new system should use "Motorcycles" as the canonical LEAP label. Confirm whether there is any economy where two-wheeler data needs to be separated from motorcycles (e.g., e-bikes vs. motorbikes with different drive profiles).
> no. always use motorcycles even if the vehicle is a 3w. push bikes are not considered in the modelling since they dont use neergy. ebikes are skipped since they are not a significant share of the fleet in any economy, and they have very different drive profiles that would require separate modelling. If ebikes become more significant in the future, we can consider adding a separate "ebike" vehicle type with its own drive profiles and assumptions.

**A2.** The workflow guide uses "light trucks" and "medium trucks" and "heavy trucks" as distinct vehicle types. The combined_exports show only "Trucks" split by size suffix in the technology label (e.g., "ICE heavy", "ICE medium"). The source taxonomy uses `ht` (heavy) and `mt` (medium) separately. Should the new system track light, medium, and heavy trucks as separate vehicle_type values, or aggregate `ht + mt → Trucks` with size encoded in the technology label? This affects T4, T5, T6, and T10.
> split trucks into medium and heavy on the drive type level like this 'aggregate `ht + mt → Trucks` with size encoded in the technology label? This affects T4, T5, T6, and T10.'
**A3.** LPVs in the combined_exports are split by size (small, medium, large) at the technology level. The workflow guide does not specify size splits for passenger vehicles. Should size classes be preserved as a sub-dimension in the new model, or is size only relevant for the LEAP branch path name (encoded in the `leap_branch_path` column)?
> jsut like for trucks, we can split LPVs into small, medium, and large on the drive type level like this 'aggregate `car + suv + lt → LPVs` with size encoded in the technology label? This affects T4, T5, T6, and T10.'

**A4.** The workflow guide mentions "LCVs" as a freight vehicle type. The 9th edition model uses `lcv` in freight. Are LCVs always freight, or do some economies classify them as passenger? Clarify the transport_type assignment for LCVs.
> LCVs are always freight. They are not used as passenger vehicles in any economy. We can safely classify all LCVs under the freight transport type in the new model.

### Category B — Old assumptions that may conflict with new workflow

**B1.** The old system uses 3% default turnover rate (from transport_data_system). The new system derives required sales from target stocks and surviving stock rather than from a fixed turnover rate. The turnover rate is an output in the new system, not an input. Confirm this is correct and that no component of the new system should hard-code a turnover rate.
> yeah thats good. but having a turnover rate output is useful for diagnostics and comparison to the old system, so we can calculate it as `turnover_rate = new_sales / surviving_stock` and include it in the T6 output for validation purposes. Maybe even allow it to be seen by vehicle type.  But it should not be used as an input or assumption anywhere in the new model.

**B2.** The old system embeds survival curve assumptions directly in calculation functions rather than storing them in standalone config files. The new system should store survival curves as researcher inputs or defaults in T2/T3. A default survival curve set needs to be assembled. Identify who owns this and what source to use (IEA, ICCT, other?).
> not 100% sure yet but we will use the one that exists in leap_transport for now and then we can review it and update it later if needed. We can extract the survival curves from the existing leap_transport codebase and store them in a CSV or YAML file that can be loaded as defaults in T2. Researchers can then review and adjust these curves as needed for different economies or scenarios. 

**B3.** The `build_passenger_sales_for_economy()` function has a `use_9th_vehicle_type_sales_shares` flag (default `True`) that overrides vehicle share proportions with 9th edition values. This flag embeds a 9th edition dependency in the sales calculation. Remove this flag in the new system and replace with the Module 5 sales share preparation logic.
> yes. however we will be using the 9th edition sales shares as a default input for Module 1 so in the end its kind of the same. 
**B4.** The multinode_energy_balance uses economy code format `01AUS` (no underscore after number), while all other repos use `01_AUS`. Confirm which format the new road model should use canonically. The canonical format should be `01_AUS` (with underscore) to match all other systems.

### Category C — LEAP workbook structure constraints

**C1.** The LEAP workbook uses size-differentiated technology labels (e.g., "ICE small", "ICE medium", "ICE large" for LPVs; "ICE heavy", "ICE medium" for Trucks). The new model at drive type level uses "ICE", "BEV", "PHEV", "FCEV". A mapping is needed from `(vehicle_type, drive_type)` pairs to LEAP technology labels with size. Is the size split purely cosmetic in LEAP (i.e., LEAP does not separately track them) or does it materially affect the model calculation?
> actually the split contains size identifiers for LPVs and trucks within the drive type level, so we will need to preserve that in the new model. e.g. ICE medium, large for LPVs and Trucks. This has a effect on the efficiency assumptions since medium and large vehicles have different energy use profiles. So we will need to maintain the size split in the new model and ensure that the LEAP branch paths reflect this split correctly. It was done in leap_transport using the car/SUV/LT and ht/mt labels in the source data, so we can do something similar in the new model to ensure the correct mapping to LEAP technology labels. For now, since we previously split car/SUV/LT into small/medium/large, and we now want to move to medium/large only, we can just map car to medium and SUV/LT to large for the LPVs. For trucks, we can map mt to medium and ht to large. This way we maintain the size differentiation in the LEAP branch paths while simplifying our internal vehicle type categories.

**C2.** The LEAP workbook exports Device Shares within technology branches (e.g., "BEV small" has a Device Share for "Electricity"). For ICE branches, Device Shares allow multiple fuels per technology. For BEV, only electricity is expected. Confirm whether the new Module 6 Device Share calculation should output Device Share = 1.0 for single-fuel branches (BEV → Electricity) or whether LEAP handles this automatically.
> yes use 1.

**C3.** The LEAP workbook requires ScenarioID integers (1, 2, 3) linked to specific LEAP scenario names. How should the new Python system handle the ScenarioID mapping? Should it be hard-coded as `{Current Accounts: 1, Reference: 2, Target: 3}` or read from a config file?
> handle it the same way these ID cols are handled in leap_transport which is by doign a merge on them at the final stage. But since this is a longer system lets do it at stages throughotu, such as once in module 2, and then after all calcs are done? if things arent mapping then weare msising/have extra rows that leap doesnt expect so it will be a useful validation step to do the merge and check for missing/extra rows at multiple points in the workflow. the id cols are below, with typical values for the Target scenario in Japan from the combined_export file: 
BranchID	VariableID	ScenarioID	RegionID	Branch Path	Variable	Scenario	Region
1489	958	3	1	Demand\Freight road	Sales	Target	Japan
1491	1424	3	1	Demand\Freight road\LCVs	Sales Share	Target	Japan


**C4.** The workbook `Expression` column stores the full 39-year time series (2022–2060) as a single string. If the model projection end year changes (e.g., extended to 2070), does the entire workbook structure change? Is 2060 the firm end year for the Outlook, or could it be extended?
> 2060 is the current end year for the Outlook, but we want to keep the system flexible in case we need to extend it in the future. The `convert_to_leap_expression()` function should be designed to handle any range of years, so if we need to extend to 2070 later, we can do so without changing the overall workbook structure. The key is to ensure that all components of the system are designed with flexibility in mind regarding the projection end year.

### Category D — Data gaps and defaults

**D1.** PHEV electric utilisation rate (the share of km driven on electricity) is listed as a required Module 1 input. No default source is identified in the existing codebase. What is the recommended default PHEV electric utilisation rate by vehicle type and economy, and what source should be cited?
> lets use 50% and say its
**D2.** Survival curves are referenced in the existing code but not stored in a standalone accessible config. A default survival curve set is needed for Module 1. What file currently contains the default survival curves for the 9th edition LEAP model, and can those curves be used as a starting point?
> we can extract the survival curves from the existing leap_transport codebase C:\Users\Work\github\leap_transport\data\lifecycle_profiles and store them in a CSV file that can be loaded as defaults in the website. Researchers can then review and adjust these curves as needed for different economies or scenarios. The source for them is currently non-existent, just estimated. We can say they are estimated based on expert judgement and available literature, and we can document the source as "leap_transport default survival curves" until we have a more formal source or justification for them.

**D3.** The freight GDP elasticity calculation excludes COVID years 2020–2022 as described in the workflow guide, and the elasticity is clamped to configured bounds. No default bounds are specified in the guide for the freight elasticity. What are the recommended freight elasticity bounds (analogous to k_min=0.0, k_max=0.15 for passenger)?
> we can set the freight GDP elasticity bounds to k_min=0.0 and k_max=0.3. This allows for a wider range of potential elasticities in freight, which can be more sensitive to economic growth compared to passenger transport. The upper bound of 0.3 is still conservative enough to prevent unrealistic projections while allowing for significant growth in freight demand in high-growth scenarios. 
> we should make a note that this needs time to be calibrated and validated against historical data, and we may need to adjust these bounds as we gather more evidence on freight demand responsiveness to GDP growth in different economies.

**D4.** EV sales share data from IEA EV Explorer is referenced as a key input for Module 5. The transport_data_system has a 2022 update. Is there a more recent update available (2023, 2024, 2025), and where is it stored?
> the most recent data is here https://www.iea.org/data-and-statistics/data-tools/global-ev-data-explorer .  we should build a quick process for extracting the data and making it useful in this system.

### Category E — Implementation scope and Fabian's tool

**E1.** The workflow guide describes Fabian's researcher input tool as the intended interface for Module 1 data collection. How much of Module 1 should be built now versus left as a stub that Fabian's tool will fill? Specifically: should the new Module 1 code read from a fixed CSV format, from Fabian's tool output format, or both?
>ive started building on top of his tool so assume its now a fixed CSV format that the C:\Users\Work\github\multinode_energy_balance project will output. The only link to fabians tool now is that it is origianlly his code and he may take it over later on. 

**E2.** The workflow guide says researchers will enter future sales shares directly in LEAP. Does this mean Module 5 only needs to produce the base-year sales share, or does it also need to produce projected sales shares as a starting point for researchers to edit? Clarify the handoff boundary.
> Module 5 produce the base-year sales share. Then it should use projected sales sahres from the 9th edition model as a default for the future years, but these are just defaults that researchers can adjust as needed. So the handoff boundary is that Module 5 produces the base-year sales share and default future sales shares, but researchers have the flexibility to edit the future sales shares directly in LEAP based on their knowledge of the specific economy and scenario. the future sales sahres are already somehwat genrated in leap_transprot so copy that workflow and then we can review the assumptions and adjust as needed. It will be important to ffind someway to adjsut the future sales shares to match the base year sales shares we calculate, since we dont want to have a disconnect between the base year and future year assumptions. Maybe we can do some kind of scaling of the future sales shares to ensure they are consistent with the base year sales shares we produce in Module 5.

**E3.** The reconciliation weights (stock=0.50, mileage=0.25, efficiency=0.25) are specified as defaults in the workflow guide. Should these be stored in a YAML config file so that researchers can adjust them per economy or vehicle type, or should they be fixed in code?
they should be adjustable thogu hC:\Users\Work\github\multinode_energy_balance which it hink they already are. these will then be read by the reconciliation function in Module 6 and applied to the stock, mileage, and efficiency adjustments. So, currently multinode_energy_balance outputs a leap import file with all valid leap imports sucha s sales shares, mileage etc, then also the survival and vintage profiles in their own formattd file, and then also a config file with the reconciliation weights and bounds. The Module 6 code will read in the leap import file for the initial values, read in the survival and vintage profiles for the stock projection, and read in the config file for the reconciliation weights and bounds. This way we keep all the configurable parameters in one place and make it easy for researchers to adjust them as needed without having to change the core model code. Perhaps the best way to do this is to actually ahve it all in one workbook with different sheets for the leap imports, the survival/vintage profiles, and the config parameters. This way we have a single source of truth for all the inputs to the model, and researchers can easily see how the different assumptions interact with each other. 
We can also include validation in multinode_energy_balance to ensure that the weights sum to 1.0 and are within reasonable bounds (e.g., each weight between 0 and 1). This way researchers can experiment with different weightings to see how it affects the reconciliation outcomes.

**E4.** The workflow guide notes that LEAP scrappage assumptions should be prepared as "explicit year-specific scrappage assumptions" passed to LEAP, not baked into survival curves. Is there a LEAP mechanism for entering scrappage by year by vehicle type that the new model should target? Confirm whether the `scrappage_for_leap` column in T6 maps to a specific LEAP variable name and branch path.
> yes ther eis a leap variable for this already. we are going to make it so teh user can choose to enter this data in at module 1, and then it will be passed through to module 4 and then to module 6 where it will be included in the final LEAP export. The `scrappage_for_leap` column in T6 will map to a specific LEAP variable name, which we can call "Scrappage" for now. The branch path will depend on the vehicle type and drive type, but it will generally follow the structure of `Demand\{transport_type} road\{vehicle_type}\{drive_type}\Scrappage`. For example, for medium ICE passenger cars, the branch path would be `Demand\Passenger road\Medium\ICE\Scrappage`. We will need to ensure that this variable is included in the final LEAP import workbook and that it is correctly mapped to the appropriate branches in LEAP. We should also include validation to ensure that the scrappage values are non-negative and do not exceed the surviving stock for each vehicle type and year, as it would not make sense to scrap more vehicles than are surviving. This is quite complex so it may end up being deleted if it proves too difficult to implement in a clean way, but we can try to include it as an optional feature in the first iteration and then review it after we have some initial results.

---

*End of transition audit report.*
*Next step: human review of Section 10, then proceed to Phase 0 of the implementation order.*
