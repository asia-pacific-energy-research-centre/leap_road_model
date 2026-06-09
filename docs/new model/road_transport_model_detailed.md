<!-- markdownlint-disable MD024 MD025 MD033 -->

# Road transport model workflow guide

> **Purpose note**  
> This document is the implementation-oriented workflow guide for the road transport model in `leap_road_model`. It defines module boundaries, required logic, and expected outputs for the current codebase. For a shorter conceptual summary of the model, use `road_transport_model_simplified.md`
.

This guide describes the Python-side workflow needed to prepare the road transport model before it is passed into LEAP.

![End-to-end road model workflow](End-to-end%20road%20model%20workflow%208062026.png)

*Primary reference for the full end-to-end workflow. Some implementation detail is not shown.*

![Road transport model — researcher detail](Road%20transport%20model%20%E2%80%94%20researcher%20detail.png)
*More simplified illustration of the modelling workflow.*

The road model is the most detailed transport demand model because it uses a stock-flow structure: vehicle stock, sales, retirements, mileage, efficiency, and fuel allocation all interact to produce energy use. Existing transport documentation describes this as a sales-based model where ownership assumptions, sales shares, survival curves, efficiency, and mileage combine to produce annual energy use in LEAP.

This guide covers:

- Module 1 - Road input data and defaults

- Module 2 - Base-year road structure and calibration preparation

- Module 3 - Stock target projection

- Module 4 - Sales, survival, vintage, and turnover policy

- Module 5 - Vehicle sales share preparation

- Module 6 - Road LEAP input package, fuel allocation, and reconciliation

- Module 7 - Optional Python mirror and post-LEAP validation

## Contents

1. [Implementation status (current repo)](#implementation-status-current-repo)
2. [Workflow runtime configuration](#workflow-runtime-configuration)
3. [Module 1 data-source contract (no hard-coded data)](#module-1-data-source-contract-no-hard-coded-data)
4. [Overall Python / LEAP Split](#overall-python--leap-split)
5. [Input Format](#input-format)
6. [Road Branch Scope](#road-branch-scope)
7. [Module Sequence](#module-sequence)
8. [Module 1 - Road Input Data and Defaults](#module-1---road-input-data-and-defaults)
9. [Module 2 - Base-Year Road Structure](#module-2---base-year-road-structure)
10. [Module 3 - Stock Target Projection](#module-3---stock-target-projection)
11. [Module 4 - Sales, Survival, Vintage, and Turnover](#module-4---sales-survival-vintage-and-turnover)
12. [Module 5 - Vehicle Sales Share Preparation](#module-5---vehicle-sales-share-preparation)
13. [Module 6 - LEAP Handoff, Reconciliation, and Device Shares](#module-6---leap-handoff-reconciliation-and-device-shares)
14. [Module 7 - Optional Python Mirror and Post-LEAP Validation](#module-7---optional-python-mirror-and-post-leap-validation)
15. [T-Table Lineage and Output Inventory](#t-table-lineage-and-output-inventory)
16. [Validation Requirements](#validation-requirements)
17. [Main Files](#main-files)
18. [Relationship to Other Documents](#relationship-to-other-documents)

## Implementation status (current repo)

The current `codebase/road_workflow.py` runtime now treats Module 1 defaults as
the primary upstream input contract for base-year road assumptions.

In practice this means the workflow loads a generated Module 1 package before
Modules 2-6. The target upstream package is the canonical long CSV contract from
`road_model_inputs_interface`; older wide packages under
`input_data/module1_defaults/` remain supported as backward-compatibility inputs
during migration, but new work should use the canonical long CSV package.

The exact row contract for the interface hand-off is maintained in
`../road_model_inputs_interface/back-end/data/road_model/config/road_module1_static_contract.csv`.
That file defines which branch/variable rows are required in the static package
and which rows are shown in the browser. The loaded Module 1 package supplies,
at minimum:

- base-year road inputs (stock, mileage, fuel economy, sales-share rows);
- survival curves and vintage profiles;
- passenger saturation level for Module 3;
- vehicle-equivalent weights for Module 3;
- vehicle-type `Stock Share` rows for Module 3 stock split assumptions;
- `Passenger Stock Growth Rate Adjustment` for Module 3 passenger S-curve tuning;
- `Freight GDP Elasticity Adjustment` for Module 3 freight elasticity tuning;
- PHEV electric utilisation assumptions, specified for passenger and freight PHEV branches where applicable, and scalar bounds for Module 6;
- reconciliation weights for Module 6 (required — Module 1 provides APEC-wide defaults that can be overridden per economy).

For normal source-backed generation, use the `road_model_inputs_interface`
package builder. `scripts/generate_module1_defaults.py` remains a repo-local
compatibility/backfill helper for `input_data/module1_defaults/`, not the
preferred source update path.

After loading population, GDP, and ESTO energy in `run_for_economy()`, `_validate_macro_inputs()` checks that all three DataFrames have the expected column names and cover every projection year, raising a clear `ValueError` at entry rather than a cryptic error deep in Module 3.

## Workflow runtime configuration

Runtime switches for `codebase/road_workflow.py` are centralised in
`codebase/config/workflow_defaults.yaml`. This YAML is for orchestration
defaults only: scenario, base/final years, Module 1 package root/version,
visualisation output, CSV output, progress printing, LEAP row diagnostics,
future sales-share auto-loading, module run/skip switches, and Module 6 match
tolerance.

These settings are not model input fallbacks. Base-year stock, mileage, fuel
economy, survival curves, PHEV utilisation, projection adjustment multipliers,
reconciliation weights, and scalar bounds must still come through the generated
Module 1 package.

Precedence for `run_for_economy()` and the CLI is:

1. built-in `RoadWorkflowConfig` defaults;
2. `codebase/config/workflow_defaults.yaml` or `--workflow-config <path>`;
3. explicit `run_for_economy(..., **config_overrides)` values or CLI flags.

Common CLI overrides:

```powershell
python codebase\road_workflow.py 15_PHL --no-vis --module1-defaults-dir ..\road_model_inputs_interface\back-end\outputs\road_module1_defaults --module1-defaults-version v2026_06_05_road_module1_sources
python codebase\road_workflow.py 20_USA --skip-m7 --no-save-csv-outputs
python codebase\road_workflow.py 20_USA --module6-match-tolerance 0.02
```

## Module 1 data-source contract (no hard-coded data)

For cross-repo consistency, Module 1 data values must not be hard-coded in
runtime code. The authoritative data sources are CSV/XLSX files in:

```text
road_model_inputs_interface/back-end/data/road_model/
```

This includes reconciliation factors, PHEV utilisation, saturation, vehicle-equivalent weights, passenger stock growth-rate adjustments, freight GDP-elasticity adjustments, and workbook defaults. `leap_road_model` consumes generated Module 1 default packages from those sources and should not embed parallel literal datasets in runtime code.

## Overall Python / LEAP Split

Python prepares the road transport input package that LEAP needs. LEAP remains the official Outlook projection platform.

Python is responsible for:

- loading and standardising Module 1 inputs;
- preparing base-year road branch data;
- projecting target stock envelopes for passenger and freight road;
- preparing sales, survival, vintage, and turnover inputs;
- seeding base-year and future sales shares;
- reconciling base-year fuel energy to ESTO; and
- writing LEAP-ready tables and diagnostics.

LEAP is responsible for:

- running the official stock-turnover projection;
- storing researcher-entered future sales shares and scenario assumptions;
- applying future mileage, fuel economy, and scrappage assumptions; and
- producing final Outlook outputs.

Any Python calculation after the LEAP handoff should be labelled as QA, diagnostics, or a mirror model. It is not the official projection unless the workflow explicitly says so.

## Input Format

The target workflow consumes the canonical long Module 1 package contract from
`road_model_inputs_interface`. The current adapter may still accept the older
LEAP-style wide CSV as a compatibility artifact.

Canonical long package columns are:

- `Economy`
- `Scenario`
- `Branch Path`
- `Variable`
- `Year`
- `Value`
- `Scale`
- `Units`
- source/comment metadata where available

`Scale` is optional for backward compatibility. When present, numeric LEAP-style
labels such as `Thousand`, `Thousands`, `Million`, `Millions`, `Billion`, and
`Billions` are applied as multipliers before values enter the model. For example,
a `Stock` value of `1.25` with `Scale = Millions` is loaded internally as
`1,250,000` devices. `%` is preserved as a LEAP/display scale for share rows and
is not converted to a fraction by the generic input parser.

Profile rows stay in the same CSV. They encode their profile index in the
branch path, for example `Age Profile\5`, rather than using a mostly blank
extra column. Current profiles are treated as global road-model profiles unless
a later package adds more specific profile branch paths.

Generated per-economy filenames use stable underscore economy codes and
overwrite in place:

```text
road_module1_values_<ECONOMY>.csv
road_module1_values_20_USA.csv
```

The adapter converts those rows into the internal LEAP-style shape used by the
rest of the workflow. Legacy package files may still provide:

- `Branch Path`
- `Variable`
- `Scenario`
- `Region`
- at least one year column, usually `2022`

Useful optional legacy columns are:

- `Scale`
- `Units`
- `Per...`
- source and review metadata such as `input_source`, `source_type`, `notes`, and `review_flag`

The runtime parser ignores unrelated metadata columns, but the diagnostics should preserve useful source flags where possible.

## Road Branch Scope

The road branch hierarchy is:

```text
Demand
  Passenger road
    LPVs
      ICE small/medium/large
      HEV small/medium/large
      PHEV small/medium/large
      EREV small/medium/large
      BEV small/medium/large
      FCEV small/medium/large
    Motorcycles
      ICE / BEV / FCEV
    Buses
      ICE / BEV / FCEV
  Freight road
    Trucks
      ICE medium/heavy
      BEV medium/heavy
      FCEV medium/heavy
    LCVs
      ICE / BEV / FCEV / PHEV
```

Current scope rules (important when comparing to the 9th edition and earlier 10th edition LEAP models):

- `HEV` and `EREV` are LPV-only.
- Truck `PHEV` is out of scope.
- LPVs use `small`, `medium`, and `large` size labels.
- Trucks use `medium` and `heavy` size labels where truck-size splits are needed.
- `Fuel Economy` is the canonical Module 1 efficiency variable. `Final On-Road Fuel Economy` can be accepted only as a legacy input alias.

The same vehicle/drive/size matrix should be used by Module 1 validation and
Module 2 branch generation. Module 1 rows outside this matrix should be rejected
or explicitly recategorized before export; Module 2 should not create branches
outside this matrix during skeleton generation.

## Module Sequence

`codebase/road_workflow.py` runs Modules 2 to 6 after loading a pre-generated Module 1 package. Module 7 is available as an optional QA mirror and is called separately.

```text
Module 1 defaults package
  -> Module 2 base-year branch table
  -> Module 3 stock targets
  -> Module 4 sales, survival, vintage, turnover
  -> Module 5 sales shares
  -> Module 6 LEAP handoff and reconciliation
  -> optional Module 7 mirror and post-LEAP validation
```

## Module 1 - Road Input Data and Defaults

### Purpose

Module 1 gathers, standardises, and documents road model inputs before any stock projection, turnover, fuel allocation, or LEAP preparation is done.

The current orchestrator does not run raw Module 1 source processing directly.
It loads a generated Module 1 package. During migration this can be a legacy
package from `input_data/module1_defaults/`; the target package is the long CSV
from `road_model_inputs_interface`.

The interface-side row contract is
`../road_model_inputs_interface/back-end/data/road_model/config/road_module1_static_contract.csv`.
It is the operator-maintained list of expected static package rows and interface
visibility flags; the model should load the generated package rather than
reconstructing that contract itself.

Researchers who want to run the road workflow without starting the website can
use `scripts/offline_workflow.py`. It reads pre-generated Module 1 outputs from
the sibling `road_model_inputs_interface/back-end/outputs/road_module1_defaults/`
directory when available, falls back to legacy `input_data/module1_defaults/`,
and then calls `run_for_economy()` for one or more economies.

### Responsibilities

Module 1 provides:

- base-year stock, mileage, fuel economy, and sales-share rows;
- survival curves and vintage profiles;
- passenger saturation assumptions;
- vehicle-equivalent weights;
- passenger stock growth-rate adjustment;
- freight GDP-elasticity adjustment;
- PHEV electric utilisation assumptions;
- reconciliation weights and scalar bounds where available;
- source and comment metadata for defaulted or researcher-edited values.

### Researcher Input Tool

The researcher input process should guide users through missing data, show defaults, and allow economy-specific overrides. It should not require researchers to know every value before the workflow can run.

The tool should collect or expose:

- base-year stock by vehicle type, drive, and size where relevant;
- base-year mileage;
- base-year fuel economy;
- base-year sales shares where known;
- survival and vintage assumptions;
- saturation and vehicle-equivalent weight assumptions;
- passenger stock growth-rate adjustment;
- freight GDP-elasticity adjustment;
- PHEV utilisation assumptions;
- notes explaining researcher overrides.

### Outputs

The generated Module 1 package should include:

- one canonical long CSV for each economy;
- a manifest describing generation date, base year, source files, and scripts;
- any validation report generated during packaging; and
- source/comment metadata needed for diagnostics.

## Module 2 - Base-Year Road Structure

### Purpose

Module 2 parses Module 1 rows and produces a base-year road branch table that
later modules can use consistently.

### Responsibilities

Module 2 should:

- parse `Branch Path` into `transport_type`, `vehicle_type`, `drive_type`, `size`, and `fuel` dimensions;
- normalise variable names and units;
- apply scale multipliers;
- keep passenger and freight road separate;
- preserve source and review metadata;
- identify missing required base-year inputs;
- build a tidy branch table for stock, mileage, fuel economy, stock share, sales share, and Device Share rows.

### Important Distinction

Module 2 prepares the branch structure and base-year inputs. It does not perform final fuel reconciliation. ESTO matching and Device Share finalisation happen in Module 6.

### Outputs

Module 2 produces `T4_base_year_branches`, the common base-year branch table used by Modules 3 to 6.

## Module 3 - Stock Target Projection

### Purpose

Module 3 creates target stock envelopes for passenger and freight road. Target stock is calculated internally; it is not treated as a fixed external input.

Vehicle-type stock splits come from Module 1 `Stock Share` rows at the five
vehicle-type branches: `Demand\Passenger road\LPVs`,
`Demand\Passenger road\Motorcycles`, `Demand\Passenger road\Buses`,
`Demand\Freight road\Trucks`, and `Demand\Freight road\LCVs`. Values are
LEAP-style percentages in the Module 1 package. The workflow converts them to
fractions, interpolates from the base year to supplied target years, and holds
the last target constant.

**Passenger `Stock Share`** (LPVs, Motorcycles, Buses) is researcher-adjustable.
Module 1 provides base-year shares derived from base-year Stock rows, plus
default anchor values at 2040 and 2060 seeded to the same base-year share.
Researchers may edit the 2040/2060 anchors to define a trajectory; if left
unchanged, the model holds the base-year split flat. The workflow converts
passenger physical shares to LPV-equivalent capacity shares using Module 1
vehicle-equivalent weights before calling Module 3.

**Freight `Stock Share`** (Trucks, LCVs) is **not researcher-adjustable**.
The truck/LCV split shows no meaningful projected trend and is held flat at the
base-year proportions. The 2040 and 2060 anchor values are seeded equal to the
base year by design; researchers should leave these unchanged.

### Passenger Stock

Passenger stock is projected using a logistic motorisation envelope. The envelope is defined in vehicle-equivalent terms so that the ownership curve remains comparable when the vehicle mix shifts between LPVs, motorcycles, and buses.

#### Vehicle-equivalent ownership

Physical stocks are converted to a single aggregate using Module 1 `Vehicle Equivalent Weight` values (sourced from `apec_vehicle_equivalent_weights.csv`). Default weights:

| Vehicle type | Default weight |
| --- | --- |
| LPVs | 1.0 (reference unit) |
| Motorcycles | 0.8 |
| Buses | 20.0 |

These are config-driven, not hard-coded. One bus is treated as equivalent to 20 LPVs of ownership demand; ignoring this would produce a meaningless aggregate when bus-heavy economies are compared with car-dominated ones.

Base-year motorisation level:

```text
M_base = sum(base_stock[vt] × weight[vt]) / population_base
```

in units of LPV-equivalents per capita.

#### Saturation level

`M_sat` is resolved in priority order:

1. Researcher-supplied value in Module 1 (source flag: `researcher`).
2. Regional default from `apec_passenger_vehicle_saturation.csv` (source flag: `regional_default`).
3. Fallback: `M_sat = M_base × 3.0` (source flag: `fallback`).

The source flag is carried through T5 for review.

#### Estimating k

`k` is the S-curve steepness parameter. It is estimated from recent passenger road energy growth, using energy as a proxy for stock growth:

```text
g_E = mean(log(E[t] / E[t-1]))   over the 10-year lookback window
k   = g_E / (1 − M_base / M_sat)
```

COVID years 2020–2022 are excluded. The lookback window and excluded years are config-driven (`lookback_window_years = 10`, `covid_exclude_years = [2020, 2021, 2022]`).

Example: if `g_E = 0.03` and `M_base / M_sat = 0.40`, then `k = 0.03 / 0.60 = 0.05`.

#### Growth-rate adjustment and k bounds

Before bounds are applied, `k` is multiplied by the Module 1
`Passenger Stock Growth Rate Adjustment`. The current APEC-wide default is
`1.2`, meaning the estimated S-curve steepness is increased by 20 percent unless
an economy-specific or researcher-edited value overrides it. A value of `1.0`
keeps the estimated rate unchanged. This is an overall passenger stock growth
tuning parameter, not a vehicle-type-specific adjustment.

`k` is clamped to `[k_min, k_max]` (defaults: `0.0` to `0.15`):

- `k = 0.0` means no structural growth in the motorisation envelope — stock moves only with population.
- `k = 0.15` is a fast upper-bound transition toward saturation.
- Negative `k` would imply structural decline and is not permitted as a default.

Any economy where `k` hits either bound is flagged in T5 (`k_clamped = True`).

#### Already-saturated economies

If `M_base ≥ 0.95 × M_sat`, the economy is treated as already saturated: `k` is set to `0.0` and the `is_saturated` flag is set. Ownership remains flat; stock changes only with population.

#### Weight calibration

When `passenger_saturation_reached = True`, Module 3 can calibrate vehicle-equivalent weights for Motorcycles and Buses so that the base-year weighted stock equals the saturation target. Calibration solves a constrained minimisation that stays within per-type bounds and minimises deviation from the Module 1 default weights. The original and adjusted weights are both recorded in T5.

#### Allocation to vehicle types

After projecting the aggregate motorisation envelope `M(year)`:

```text
total_weighted(year) = M(year) × population(year)
target_stock(vt, year) = total_weighted(year) × capacity_share(vt) / weight(vt)
```

where `capacity_share(vt) = base_stock(vt) × weight(vt) / sum(base_stock × weight)`.

#### Post-reconciliation stock target adjustment

After Module 6 reconciles base-year stock, mileage, and efficiency to ESTO fuel
totals, the workflow may call
`road_workflow.py::build_post_reconciliation_stock_targets()`. For passenger
rows, this re-anchors the base year to reconciled stock but preserves the
original final-year physical stock target. The difference between the
pre-reconciliation base-year stock and reconciled base-year stock fades linearly
to zero by `final_year`. T5 records the original target, reconciled base stock,
base adjustment, and method string
`preserve_final_target_linear_base_adjustment`.

### Freight Stock

Freight stock is projected with a bounded GDP-elasticity method using `estimate_freight_elasticity` and `project_freight_stocks` in `module3_stock_targets.py`.

#### Elasticity estimation

Annual growth rates are estimated as compound rates over the 10-year lookback window (COVID years excluded):

```text
freight_energy_growth = (E_end / E_start) ^ (1 / n) − 1
gdp_growth            = (GDP_end / GDP_start) ^ (1 / n) − 1
elasticity            = freight_energy_growth / gdp_growth
```

The estimated elasticity is multiplied by Module 1
`Freight GDP Elasticity Adjustment` before clamping. The elasticity is then
clamped to `[0.0, 2.0]`. If GDP growth is near zero or data are insufficient,
the default elasticity `0.8` is used. The data source flag (`estimated`,
`estimated_adjusted`, or `override`) and a short note are carried into T5.

Historical GDP rows are required for this estimate. If the macro input starts at the base year only, the lookback window cannot estimate GDP growth, especially because 2020-2022 are excluded as COVID years. The intended fix is to add historical GDP data to the macro source, not to add code that hides the missing-data warning.

#### Stock projection

```text
total_base = Trucks_base + LCVs_base
total(year) = total_base × (GDP(year) / GDP_base) ^ elasticity
target_stock(vt, year) = total(year) × physical_share(vt)
```

where `physical_share(vt) = base_stock(vt) / total_base` and shares are held flat at base-year proportions (see the Stock Share discussion above).

A researcher-supplied `freight_total` override replaces the estimated elasticity; the override is recorded in diagnostics.

#### Post-reconciliation stock target adjustment

When post-reconciliation stock target adjustment is enabled, freight rows are
re-anchored to reconciled base-year stock differently from passenger rows.
Freight preserves the original growth index from Module 3:

```text
growth_factor(year) = pre_reconciliation_target_stock(year) / pre_reconciliation_target_stock(base_year)
post_reconciliation_target_stock(year) = reconciled_base_stock × growth_factor(year)
```

This keeps the GDP-elasticity growth shape unchanged while moving the physical
stock level to the reconciled base. T5 records the method string
`preserve_growth_index_from_reconciled_base`.

### Diagnostics

T5 carries the following per-row diagnostic columns for review:

**Passenger rows:** `motorisation_level`, `saturation_level`, `k_raw`, `k_used`, `k_clamped`, `passenger_stock_growth_rate_adjustment`, `is_saturated`, `saturation_source_flag`, `original_vehicle_equivalent_weight`, `adjusted_vehicle_equivalent_weight`, `weight_calibration_applied`.

**Freight rows:** `gdp_elasticity_used`, `freight_raw_elasticity`, `freight_elasticity_clamped`, `freight_energy_growth_rate`, `freight_gdp_growth_rate`, `freight_elasticity_adjustment`, `freight_elasticity_data_source`, `freight_elasticity_note`.

### Outputs

Module 3 produces `T5_stock_targets` with columns for `economy`, `scenario`, `year`, `transport_type`, `vehicle_type`, `target_stock`, and all diagnostic columns above.

## Module 4 - Sales, Survival, Vintage, and Turnover

### Purpose

Module 4 converts target stock paths into sales, retirements, and lifecycle assumptions that LEAP can use.

### Core Stock-Flow Logic

For each technology bucket, Module 4 should account for:

```text
ending stock = surviving prior stock + new sales - additional retirements
```

Required logic:

- apply survival curves by age;
- calculate natural retirements;
- calculate sales required to meet target stock;
- prevent negative sales and record any adjustment;
- preserve a stock accounting check for every year and bucket.

### Survival, Vintage, and Scrappage Policy

Module 4 should support:

- researcher-supplied survival curves;
- survival curve scaling;
- base-year vintage profile shifting;
- additional retirement rates;
- age-weighted scrappage policies;
- drive-level policy allocation to vehicle buckets.

Temporary scrappage policies should be passed to LEAP as explicit year-specific scrappage assumptions, not baked into a permanent survival curve unless the policy is meant to represent a structural lifetime change.

### Outputs

Module 4 produces `T6_sales_turnover`, including:

- target stock;
- surviving stock;
- natural retirements;
- additional retirements;
- required sales;
- `stock_above_target` and `scale_factor_applied` when surviving cohorts exceed
  the target stock and are scaled down;
- survival and vintage assumptions;
- stock accounting diagnostics.

Module 4 also produces `T6v_vintage_profiles`, the age-profile table used by
the lifecycle exporter. The workflow writes LEAP-compatible lifecycle profile
workbooks from the final active `T6v` under
`results/<economy>/lifecycle_profiles/`. Survival profiles are exported as
cumulative percent curves reconstructed from Module 4 annual survival
probabilities; vintage profiles are exported as percent age distributions that
sum to 100. The directory includes one workbook per vehicle/profile type, a
`lifecycle_profile_manifest.csv`, and a downloadable
`<economy>_lifecycle_profiles.zip`.

## Module 5 - Vehicle Sales Share Preparation

### Purpose

Module 5 prepares base-year sales shares and seeded future sales-share
trajectories. Researchers can then edit future sales shares in LEAP.

There is also an option for the user to adjust future sales share in the module 1 interface but for now we have turned that off so the future sales shares are based on the 9th edition trajectories scaled to the new base year. This is a bridge assumption, since the expectation is that the future sales shares will be directly edited by researchers in LEAP rather than sticking with the ones seeded from Python. Instead these seeded shares are meant to be a starting point for researchers to then edit in LEAP, and a to provide a more realistic projection in module 7, than keeping sales shares constant from the base year.

This module is relatively small compared to the others.

### Base-Year Sales Shares

Module 5 is still needed even when Module 1 provides consistent base-year
`Sales Share` rows. The current implementation computes a base-year share table
from T4 as a fallback and then applies Module 1 `Sales Share` rows as overrides.
That keeps downstream tables on one normalized schema and gives Module 6 a
complete `T7f` trajectory table.

Base-year checks remain useful as a defensive gate. Module 5 verifies that sales
shares are non-negative and sum correctly within each economy, scenario, year,
transport type, and vehicle type. In routine runs these checks should pass
because Module 1 has already enforced the same contract.

### Future Sales Share Seeding

The current implementation can create `T7f_future_shares` by scaling 9th edition sales-share trajectories (i.e. projections) to match the new base year. This is a bridge assumption, not an official policy scenario.

Method flags should distinguish:

- `shape_preserve`: preserve the 9th edition shape after anchoring to the new base year;
- `hold_flat`: no source trajectory exists, so hold the new base-year share constant;
- `hold_at_base`: the source trajectory is flat, so hold the new base-year share constant.

### Outputs

Module 5 produces:

- `T7_sales_shares`: base-year sales shares by road bucket;
- `T7f_future_shares`: optional seeded future sales-share trajectories;
- source flags and fallback diagnostics.

## Module 6 - LEAP Handoff, Reconciliation, and Device Shares

### Purpose

Module 6 builds the final Python-side road package for LEAP and reconciles base-year energy to ESTO. It is the most complex module because fuel energy, stock, mileage, efficiency, and Device Shares all interact.

### Handoff Package

Module 6 combines:

- Module 2 base-year branch data;
- Module 4 sales and lifecycle outputs;
- Module 5 sales shares;
- ESTO road fuel totals;
- Module 1 PHEV utilisation and reconciliation settings.

The LEAP-ready package preserves economy, scenario, year, transport type, vehicle type, drive type, size, fuel, variable, value, units, and source metadata.

### Base energy formula

All energy calculations in Module 6 use:

```text
energy_pj = stock × mileage / efficiency_km_per_gj / 1,000,000
```

where `efficiency` is distance per unit energy (km/GJ). Higher efficiency means lower energy use per vehicle.

### Reconciliation Workflow

The nine-step workflow is implemented in `run_module6`
(`codebase/modules/module6_reconciliation_and_leap_handoff.py`). The file name
intentionally covers both major responsibilities: base-year reconciliation and
the LEAP hand-off package.

#### Step 1 — Initial branch energy

Calculate `energy_pj` for every branch using base-year stock, mileage, and efficiency from Module 2.

#### Step 2 — BEV and PHEV electricity reconciliation

Before touching liquid fuels, reconcile BEV and PHEV electricity to the ESTO road electricity total using the same scalar method as Steps 5–6. PHEV electricity and liquid fuel are calculated from the adjusted PHEV branches using the Module 1 `PHEV electric utilisation rate`, which is held fixed during reconciliation unless config explicitly allows it to move.

Note that EREVs are considered as PHEVs for reconciliation purposes because they have the same electric drive and fuel use characteristics as PHEVs. The difference is that EREVs have a larger battery and can run on electricity alone for longer distances, but they still use liquid fuel when the battery is depleted. Therefore, both PHEVs and EREVs contribute to the electricity total and are reconciled together before adjusting liquid fuel.

#### Step 3 — PHEV liquid fuel subtraction

Remove PHEV liquid fuel from the relevant ESTO pools before normal fuel reconciliation:

```text
remaining_esto_gasoline = ESTO_gasoline − PHEV_gasoline
```

PHEV and EREV liquid fuel is gasoline-family only for both passenger and freight branches: Motor gasoline, Biogasoline, and Efuel are allowed. Diesel and biodiesel are not allocated to PHEV/EREV branches. This prevents ICE reconciliation from absorbing gasoline-family energy that actually belongs to PHEVs/EREVs while keeping diesel out of the plug-in hybrid fleet.

#### Step 4 — Allocate remaining ESTO fuel to eligible branches

For each fuel, the remaining ESTO total is allocated across eligible branches. Eligibility is driven by `fuel_mappings.yaml` (`drive_fuel_eligibility`). This creates a provisional `allocated_branch_fuel_energy_pj` for each branch before scalar adjustment.

Conventional liquid fuels use a vehicle-priority spillover rule before falling back to stock-share allocation:

1. Diesel and biodiesel are allocated through the freight priority tiers first:
   trucks, then LCVs, then passenger vehicles only if freight liquid-fuel demand
   has already been saturated.
2. Gasoline and biogasoline are allocated to passenger vehicles first, then any leftover spills to LCVs. They are not allocated to trucks in the road priority rule.
3. Within each priority tier, allocation is proportional to branch stock.
4. If the ESTO total exceeds the modeled energy capacity of all priority tiers,
   the final residual is assigned within the final allowed priority tier by stock
   share so the whole fuel total remains represented in T8 without violating the
   reviewed vehicle order.

Biofuels follow the same priority families as their fossil counterparts:
`Biodiesel` follows diesel tiers and `Biogasoline` follows gasoline tiers. The
current model allocates the observed ESTO biofuel total as its own fuel stream
to eligible branches, so a branch receiving a biofuel allocation can have a high
biofuel Device Share if ESTO reports large biofuel energy relative to the
modeled eligible demand. This is a reviewed modeling choice rather than a hidden
assumption that all vehicles run on 100 percent biofuel. The risk is that LEAP
may interpret high biofuel Device Shares as a dedicated biofuel technology mix
rather than a blended-fuel share, which could overstate apparent biofuel vehicle
penetration, produce large branch-level correction scalars, and make dashboard
biofuel estimates look implausibly concentrated.

Other ordinary fuels without a reviewed priority order use stock-share allocation across eligible branches.

#### Step 5 — Derive energy correction factor

For each branch:

```text
ECF = allocated_branch_fuel_energy_pj / initial_branch_energy_pj
```

If a branch has zero initial energy but non-zero allocated ESTO energy (e.g. a hydrogen FCEV branch in an economy with no observed hydrogen use), the ECF is treated as zero and the branch scalars are clamped to their lower bounds rather than raising a division error.

#### Step 6 — Adjust stock, mileage, and efficiency simultaneously

The ECF is split across the three variables using configurable Module 1 weights
that are exposed through the interface and can be edited by researchers
(defaults: stock=0.50, mileage=0.25, efficiency=0.25). The defaults put more
weight on stock because stock is usually more visible and easier to review than
mileage or efficiency.


```text
stock_scalar      = ECF ^ 0.50
mileage_scalar    = ECF ^ 0.25
efficiency_scalar = ECF ^ −0.25     ← inverted: higher efficiency reduces energy
```

Because `efficiency` is km/GJ, increasing it lowers energy use. The negative exponent ensures the efficiency scalar moves in the direction that corrects the energy gap.

Each scalar is clamped to its configured per-scalar bounds from Module 1
(`reconciliation_bound_lower/upper_stock/mileage/efficiency`). Bounds are
per-scalar by default, allowing stock wider movement than mileage or efficiency.
Legacy single-tuple bounds are still accepted by the code for older packages and
tests, but routine generated Module 1 packages should use per-component bounds.

Adjusted values:

```text
adjusted_stock      = stock      × stock_scalar
adjusted_mileage    = mileage    × mileage_scalar
adjusted_efficiency = efficiency × efficiency_scalar
```

Whether each scalar stayed within bounds is recorded in T9 and T12.

#### Step 7 — Recalculate final branch fuel energy

```text
final_energy_pj = adjusted_stock × adjusted_mileage / adjusted_efficiency / 1,000,000
```

This should match `allocated_branch_fuel_energy_pj` within tolerance. If scalars were clamped, a residual gap will remain and is reported in T12.

#### Step 8 — Calculate implied vehicles and Device Shares

```text
energy_per_vehicle = adjusted_mileage / adjusted_efficiency / 1,000,000
implied_vehicles   = final_energy_pj / energy_per_vehicle
Device Share       = implied_vehicles / adjusted_total_vehicles_in_branch
```

Device Shares must be calculated after reconciliation because they depend on the final reconciled stock, mileage, efficiency, and fuel allocation. Single-fuel drive types (e.g. BEV) always have Device Share = 1.0.

#### Step 9 — Validate

T12 diagnostics check:

- final fuel energy matches ESTO totals (after adding PHEV liquid back) within tolerance;
- all scalars stayed within bounds;
- Device Shares sum to 1 within each parent branch;
- no negative values or impossible fuel/drive combinations.

### Fuel Allocation Rules

Fuel eligibility is config-driven (`fuel_mappings.yaml`), not hard-coded. Key rules:

| Fuel | Eligible drives | Notes |
| --- | --- | --- |
| Motor gasoline | ICE, HEV, PHEV, EREV | Biogasoline follows the same gasoline-family branches |
| Gas and diesel oil | ICE, HEV | Biodiesel follows the same diesel-family branches; freight-preferred allocation where ESTO diesel is freight-dominated |
| LPG | ICE only | Separate fuel from natural gas |
| Natural gas | ICE only | Separate fuel from LPG; biogas follows the same branches |
| Electricity | BEV, PHEV, EREV | Handled in Step 2 before normal reconciliation |
| Hydrogen | FCEV | Not expected in most base years; clamped to lower bound if no ESTO hydrogen observed |
| E-fuels | ICE, HEV, PHEV, EREV | Not expected in most base years; follows ordinary liquid-fuel ICE-style branches unless a narrower reviewed rule exists |
| Ammonia | Not assigned to road unless a reviewed branch rule exists and the code is adjusted where necessary | — |

Any fuel present in ESTO but with no valid branch is flagged in T12.

### PHEV Treatment

PHEV and EREV branches carry two fuel streams: electricity and gasoline-family liquid fuel. EREV is treated like a more efficient PHEV. The electric utilisation rate (fraction of km driven on electricity) is a Module 1 input from `apec_phev_utilisation_rates.csv` and is held fixed during reconciliation.

After BEV/PHEV electricity is reconciled in Step 2, PHEV liquid fuel is computed and removed from the ESTO pools before ICE reconciliation. This preserves the ESTO fuel balance:

```text
final_gasoline = reconciled_non_phev_gasoline + phev_gasoline
final_biogasoline = reconciled_non_phev_biogasoline + phev_biogasoline
final_efuel = reconciled_non_phev_efuel + phev_efuel
final_diesel   = reconciled_non_phev_diesel
```

`build_phev_utilisation_diagnostics()` back-calculates the electric driving
share from reconciled PHEV/EREV electric and liquid energy, compares it with the
Module 1 input rate, and writes the result to `T12_phev`. Rows outside the
configured tolerance are flagged as `below_range` or `above_range`, which helps
identify fuel allocation or reconciliation problems that distort the PHEV
electric/liquid split.

### Outputs

Module 6 produces:

- `T8`: fuel allocation table (provisional allocated branch fuel energy);
- `T9`: reconciliation scalar table and reconciled branch values (stock, mileage, efficiency, scalars, within-bounds flags);
- `T10`: Device Share table;
- `T11`: LEAP-ready output table;
- `T12`: reconciliation diagnostics (ECF, residual gaps, validation status);
- `T12_phev`: PHEV utilisation diagnostics.

T11 is written at LEAP-compatible variable levels:

- `Stock`: transport-type and vehicle-type branches;
- `Sales`: transport-type branches;
- `Mileage`, `Fuel Economy`, `Device Share`: fuel-level branches;
- `Sales Share`, `Stock Share`: vehicle-type rows and drive/technology rows.

When a reference LEAP export is available, the final Excel workbook is written
through `codebase/adapters/leap_import_writer.py`, which merges BranchID,
VariableID, ScenarioID, and RegionID and returns structured warnings for
unmatched rows. The workflow searches first for the repo-local reference
template at
`input_data/leap_import_templates/DEFAULT_transport_leap_import_TGT_REF_CA.xlsx`.
The `LEAP` sheet keeps LEAP's import column structure: ID columns,
`Branch Path`, `Variable`, `Scenario`, `Region`, `Scale`, `Units`, `Per...`,
`Expression`, a blank spacer column, and `Level 1` through `Level 8...`. The
Level columns are derived directly from `Branch Path` by splitting on `\`, with
unused levels left blank.

Lifecycle profile files are written separately by
`codebase/adapters/lifecycle_profile_exporter.py` because LEAP lifecycle
profiles use a different workbook layout from the main branch-variable import
workbook.

Open implementation item: a second-run calibration helper would be useful. It
would export a Module 1-compatible CSV containing reconciled base-year stock,
mileage, and fuel economy values so researchers can import those values into the
interface and rerun the workflow with near-flat reconciliation adjustments.
## Module 7 - Optional Python Mirror and Post-LEAP Validation

### Purpose

Module 7 is a QA mirror, not the official projection engine. It can reproduce key LEAP-side calculations in Python to help give an idea of what results may look like before running LEAP and to validate that the LEAP model is correctly implementing the intended logic. Note that there will always be some differences between the mirror and LEAP results due to differences in calculation order, rounding, and any LEAP-specific features that are not mirrored in Python. The goal is not to get perfect matches but to ensure that the mirror and LEAP results are reasonably close and that any large discrepancies are flagged for review.

### Responsibilities

Module 7 can:

- run a Python mirror of the stock-turnover calculation;
- calculate mirrored vehicle-km and energy;
- accept tidy LEAP output when provided;
- populate comparison columns without overwriting LEAP results;
- flag large differences for review.

### Outputs

Module 7 produces `T13_mirror_output`, with mirror values, optional LEAP values, differences, and validation flags.

## T-Table Lineage and Output Inventory

The workflow names intermediate tables with `T*` labels. These labels are
stable diagnostic and handoff names; they do not always match the module number.
The table below is the practical lineage from model inputs to LEAP import.

| Table | Produced by | Primary source inputs | What it contains | Main saved file |
| --- | --- | --- | --- | --- |
| `T4_base_year_branches` | Module 2 | Module 1 canonical long CSV, vehicle taxonomy, branch/fuel mappings | One base-year row per model branch/fuel combination. It carries economy, scenario, transport type, vehicle type, drive type, size, fuel, LEAP branch path, base stock, mileage, fuel economy, source/provenance flags, and fill/split diagnostics. | `results/<economy>/module2/T4_base_year_branches.csv` |
| `T5_stock_targets` | Module 3 | T4 base stocks, population, GDP, ESTO road energy proxy, Module 1 stock shares and growth controls | Vehicle-type stock targets by year. Passenger rows include motorisation, saturation, S-curve, saturation flag, and vehicle-equivalent weight diagnostics. Freight rows include GDP index, final elasticity, raw elasticity, clamping flag, energy/GDP growth rates, elasticity adjustment, source, and note. | `results/<economy>/module3/T5_stock_targets.csv` |
| `T5_stock_targets_pre_reconciliation` | Workflow copy before Module 6 re-anchoring | Original Module 3 T5 | Snapshot of stock targets before Module 6 changes the base-year stock anchor. This is the conceptual Module 3 output and is used by the normal Module 3 dashboard view when present. | `results/<economy>/module3/T5_stock_targets_pre_reconciliation.csv` |
| `T5_stock_targets_post_reconciliation` | Module 6 stock re-anchoring plus Module 3 table shape | T5 pre-reconciliation, T9 reconciled base-year stock | Stock target paths re-anchored to reconciled base-year stock. Passenger keeps the original final-year physical stock target and fades the base adjustment to zero. Freight keeps the original growth index from the reconciled base stock, so GDP-elasticity growth shape is unchanged while physical stock levels move. | `results/<economy>/module3/T5_stock_targets_post_reconciliation.csv` |
| `T6_sales_turnover` | Module 4 | T5 stock targets, Module 1 survival curves, vintage profiles, turnover/scrappage controls | Vehicle stock-flow table by year: target stock, surviving stock, new sales, natural retirements, additional retirements, stock above target flags, scale factors, and stock accounting diagnostics. | `results/<economy>/module4/T6_sales_turnover.csv` |
| `T6_sales_turnover_pre_reconciliation` | Workflow copy before Module 6 re-anchoring | Original Module 4 T6 | Snapshot of sales and turnover based on the pre-reconciliation T5. This is the conceptual Module 4 output used by the normal stock/sales dashboard when present. | `results/<economy>/module4/T6_sales_turnover_pre_reconciliation.csv` |
| `T6_sales_turnover_post_reconciliation` | Module 4 rerun after Module 6 re-anchoring | T5 post-reconciliation and the same survival/vintage/turnover settings | Sales and turnover recalculated from the re-anchored stock target path. This is the active table used by downstream Module 6/7 outputs after re-anchoring. | `results/<economy>/module4/T6_sales_turnover_post_reconciliation.csv` |
| `T6v_vintage_profiles` | Module 4 | Module 1 vintage profile rows and survival settings | Base-year vintage/age distribution used by the turnover model. It is stored separately because it is an age-profile table rather than a year-by-year stock-flow table. | `results/<economy>/module4/T6v_vintage_profiles.csv` |
| `T6v_vintage_profiles_pre_reconciliation` | Workflow copy before Module 6 re-anchoring | Original Module 4 T6v | Snapshot paired with `T6_sales_turnover_pre_reconciliation`. Usually identical in structure and often values, but kept so the pre-reconciliation dashboard can use a complete Module 4 pair. | `results/<economy>/module4/T6v_vintage_profiles_pre_reconciliation.csv` |
| `T6v_vintage_profiles_post_reconciliation` | Module 4 rerun after Module 6 re-anchoring | Same inputs as T6v plus rerun context | Vintage profile output paired with `T6_sales_turnover_post_reconciliation`. | `results/<economy>/module4/T6v_vintage_profiles_post_reconciliation.csv` |
| `Lifecycle profile workbooks` | Lifecycle profile exporter | Final active `T6v` | LEAP lifecycle profile files with `Area:`, `Profile:`, blank separator, and `Year`/`Value` rows. The export includes survival and vintage profile workbooks, a manifest, and a ZIP for interface download. | `results/<economy>/lifecycle_profiles/` |
| `T7_sales_shares` | Module 5 | T4 base-year branches, EV sales data, Module 1 base-year sales share rows, fallback rules | Base-year sales shares by economy, scenario, transport type, vehicle type, and drive type. These shares anchor future drive-type mix. | In memory and diagnostics; saved only where configured or surfaced in dashboard outputs. |
| `T7f_future_shares` | Module 5 | Explicit future sales-share file, Module 1 projected sales-share rows, 9th-edition trajectory scaling, or flat fallback | Future sales-share trajectories by year, vehicle type, and drive type. Method/source flags distinguish explicit input, Module 1 projected rows, shape-preserving scaling, hold-flat, and fallback behavior. | In memory and diagnostics; saved only where configured or surfaced in dashboard outputs. |
| `T8_fuel_allocation` | Module 6 | T4 base-year branch energy, ESTO road fuel totals, fuel eligibility config, PHEV liquid/electric split | Provisional allocation of observed ESTO fuel totals to eligible model branches before scalar reconciliation. It records allocation method, priority/spillover behavior, branch eligibility, and allocated energy. | `results/<economy>/module6/T8_fuel_allocation.csv` |
| `T9_reconciliation_scalars` | Module 6 | T8 allocated fuel energy, T4 initial stock/mileage/efficiency, Module 1 reconciliation weights and scalar bounds | Branch/fuel-level reconciliation table. It contains initial energy, ECF, stock/mileage/efficiency scalars, adjusted stock, adjusted mileage, adjusted efficiency, final branch fuel energy, bound flags, iteration flags, and branch metadata. | `results/<economy>/module6/T9_reconciliation_scalars.csv` |
| `T10_device_shares` | Module 6 | T9 reconciled branch/fuel values | LEAP Device Share rows calculated after reconciliation. Device Share is fuel energy allocation expressed as a share within each technology branch after adjusted stock/mileage/efficiency are known. | `results/<economy>/module6/T10_device_shares.csv` |
| `T11_leap_ready` | Module 6 | T9 reconciled base-year values, T10 Device Shares, T6 sales/stock-flow outputs, T7/T7f sales shares | Canonical LEAP-ready long table. It includes branch path, variable, scenario, year, value, scale, units, dimensions, and source metadata for Stock, Sales, Mileage, Fuel Economy, Device Share, Sales Share, and Stock Share. Current Accounts rows are appended after Module 6 by taking the base-year Target slice and relabeling the scenario. | `results/<economy>/module6/T11_leap_ready.csv` |
| `T12_reconciliation_diagnostics` | Module 6 | T9 final fuel energy and ESTO fuel totals | Fuel-level QA table: pre/post model energy, ESTO target, gap, gap percent, ECF summary, scalar-bound status, reconciliation status, and validation flags. | `results/<economy>/module6/T12_reconciliation_diagnostics.csv` |
| `T12_phev_utilisation_diagnostics` | Module 6 | PHEV branches from T9, configured PHEV utilisation, electricity/liquid energy split | PHEV electric/liquid split QA. It back-calculates electric driving share from reconciled energy and compares it with the configured utilisation rate. | `results/<economy>/module6/T12_phev_utilisation_diagnostics.csv` |
| `T13_mirror_outputs` | Module 7 | T6 active sales/turnover, T9 base technology assumptions, T10 Device Shares, T7f sales shares | Optional Python mirror of LEAP-like stock, vehicle-km, and energy calculations for validation and comparison against LEAP outputs when available. | `results/<economy>/module7/T13_mirror_outputs.csv` |
| `T13_mirror_fuel_outputs` | Module 7 | T13 mirror outputs and T10 Device Shares | Optional fuel-level mirror outputs and fuel energy comparisons. | `results/<economy>/module7/T13_mirror_fuel_outputs.csv` |

### Runtime naming rule for pre/post reconciliation

The conceptual outputs of Modules 3 and 4 are pre-reconciliation `T5`, `T6`,
and `T6v`. During a full workflow, Module 6 can re-anchor stock trajectories to
reconciled base-year stock and rerun Module 4. When this happens, the workflow
keeps the original tables under explicit `*_pre_reconciliation` names and
replaces the active downstream tables with post-reconciliation versions:

```text
Module 3/4 original:
  T5, T6, T6v

Before re-anchoring, saved as:
  T5_pre_reconciliation
  T6_pre_reconciliation
  T6v_pre_reconciliation

After re-anchoring:
  T5 = T5_post_reconciliation
  T6 = T6_post_reconciliation
  T6v = T6v_post_reconciliation
```

If no Module 6 stock re-anchoring occurs, plain `T5`, `T6`, and `T6v` are still
the original pre-reconciliation tables. The normal dashboard page
`module3.html` is intended to show the original pre-reconciliation stock,
sales, and turnover view. The separate
`module3_post_reconciliation.html` page is intended to show only charts whose
values changed after stock re-anchoring.

## Validation Requirements

Before data are passed to LEAP, the workflow should check:

- no duplicate records in key output tables;
- required dimensions are populated;
- stock, mileage, fuel economy, sales, and shares are non-negative where required;
- sales shares sum to 1 within each relevant group;
- Device Shares sum correctly within each technology branch;
- base-year fuel totals match ESTO within tolerance after reconciliation;
- PHEV utilisation diagnostics remain within configured tolerance;
- scalar bounds and fallback assumptions are reported;
- large stock, mileage, or efficiency adjustments are flagged for review.

## Main Files

Runtime files:

- `codebase/road_workflow.py`
- `codebase/adapters/road_module1_defaults.py`
- `codebase/modules/module2_base_year.py`
- `codebase/modules/module3_stock_targets.py`
- `codebase/modules/module4_sales_turnover.py`
- `codebase/modules/module5_sales_shares.py`
- `codebase/modules/module6_reconciliation_and_leap_handoff.py`
- `codebase/modules/module7_mirror.py`

Support files:

- `scripts/generate_module1_defaults.py`
- `codebase/config/workflow_defaults.yaml` (runtime workflow switches and paths)
- `codebase/config/model_defaults.yaml` (guidance-only calibration reference; not a runtime fallback source)
- `codebase/config/fuel_mappings.yaml`
- `codebase/schemas/`
- `codebase/diagnostics/`

## Relationship to Other Documents

Use this guide for implementation sequence and module responsibilities for Modules 2-7. It is the source of truth for Module 2-7 behavior.

Use `road_transport_model_simplified.md` for the shorter conceptual explanation.

Use `multinode_road_module1_repo_guide.md` in `road_model_inputs_interface/docs/new model/` for Module 1 behavior. That guide is the source of truth for Module 1 data sourcing, the CSV contract, the static row contract, researcher UI workflow, and versioning. The Module 1 sections in this document summarize the handoff contract only; always check that guide for full Module 1 details.

Use `transition_audit_report.md` only for historical migration context. It is not the current implementation source of truth.
