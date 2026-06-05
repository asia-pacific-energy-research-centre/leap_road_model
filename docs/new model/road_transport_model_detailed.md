<!-- markdownlint-disable MD024 MD025 MD033 -->

# Road transport model workflow guide

> **Purpose note**  
> This document is the implementation-oriented workflow guide for the road transport model in `leap_road_model`. It defines module boundaries, required logic, and expected outputs for the current codebase. For a shorter conceptual summary of the model, use `road_transport_model_simplified.md`. Where the current repo has refined an earlier design idea, this guide should follow the implemented method unless the text explicitly marks a future enhancement.

This guide describes the Python-side workflow needed to prepare the road transport model before it is passed into LEAP.

The road model is the most detailed transport demand model because it uses a stock-flow structure: vehicle stock, sales, retirements, mileage, efficiency, and fuel allocation all interact to produce energy use. Existing transport documentation describes this as a sales-based model where ownership assumptions, sales shares, survival curves, efficiency, and mileage combine to produce annual energy use in LEAP.

This guide covers:

- Module 1 - Road input data and defaults

- Module 2 - Base-year road structure and calibration preparation

- Module 3 - Stock target projection

- Module 4 - Sales, survival, vintage, and turnover policy

- Module 5 - Vehicle sales share preparation

- Module 6 - Road LEAP input package, fuel allocation, and reconciliation

- Module 7 - Optional Python mirror and post-LEAP validation

## Implementation status (current repo)

The current `codebase/road_workflow.py` runtime now treats Module 1 defaults as
the primary upstream input contract for base-year road assumptions.

In practice this means the workflow loads a generated Module 1 package before
Modules 2-6. The target upstream package is the canonical long CSV contract from
`road_model_inputs_interface`; older wide packages under
`input_data/module1_defaults/` are legacy compatibility inputs.

The loaded Module 1 package supplies, at minimum:

- base-year road inputs (stock, mileage, fuel economy, sales-share rows);
- survival curves and vintage profiles;
- passenger saturation level for Module 3;
- vehicle-equivalent weights for Module 3;
- vehicle-type `Stock Share` rows for Module 3 stock split assumptions;
- PHEV electric utilisation rate (single float) and scalar bounds for Module 6;
- reconciliation weights for Module 6 (required — Module 1 provides APEC-wide defaults that can be overridden per economy).

If local compatibility defaults are missing, refresh them with
`scripts/generate_module1_defaults.py`. The long-term package generator lives in
`road_model_inputs_interface`.

After loading population, GDP, and ESTO energy in `run_for_economy()`, `_validate_macro_inputs()` checks that all three DataFrames have the expected column names and cover every projection year, raising a clear `ValueError` at entry rather than a cryptic error deep in Module 3.

## Module 1 data-source contract (no hard-coded data)

For cross-repo consistency, Module 1 data values must not be hard-coded in
runtime code. The authoritative data sources are CSV/XLSX files in:

```text
road_model_inputs_interface/back-end/data/road_model/
```

This includes reconciliation factors, PHEV utilisation, saturation, vehicle-equivalent weights, and workbook defaults. `leap_road_model` consumes generated Module 1 default packages from those sources and should not embed parallel literal datasets in runtime code.

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
- `Units`
- source/comment metadata where available

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

![Road transport model — researcher detail](Road%20transport%20model%20%E2%80%94%20researcher%20detail.png)

## Module 1 - Road Input Data and Defaults

### Purpose

Module 1 gathers, standardises, and documents road model inputs before any stock projection, turnover, fuel allocation, or LEAP preparation is done.

The current orchestrator does not run raw Module 1 source processing directly.
It loads a generated Module 1 package. During migration this can be a legacy
package from `input_data/module1_defaults/`; the target package is the long CSV
from `road_model_inputs_interface`.

### Responsibilities

Module 1 provides:

- base-year stock, mileage, fuel economy, and sales-share rows;
- survival curves and vintage profiles;
- passenger saturation assumptions;
- vehicle-equivalent weights;
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

#### k bounds

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

### Freight Stock

Freight stock is projected with a bounded GDP-elasticity method using `estimate_freight_elasticity` and `project_freight_stocks` in `module3_stock_targets.py`.

#### Elasticity estimation

Annual growth rates are estimated as compound rates over the 10-year lookback window (COVID years excluded):

```text
freight_energy_growth = (E_end / E_start) ^ (1 / n) − 1
gdp_growth            = (GDP_end / GDP_start) ^ (1 / n) − 1
elasticity            = freight_energy_growth / gdp_growth
```

The elasticity is clamped to `[0.0, 2.0]`. If GDP growth is near zero or data are insufficient, the default elasticity `0.8` is used. The data source flag (`estimated` or `override`) and a short note are carried into T5.

#### Stock projection

```text
total_base = Trucks_base + LCVs_base
total(year) = total_base × (GDP(year) / GDP_base) ^ elasticity
target_stock(vt, year) = total(year) × physical_share(vt)
```

where `physical_share(vt) = base_stock(vt) / total_base` and shares are held flat at base-year proportions (see the Stock Share discussion above).

A researcher-supplied `freight_total` override replaces the estimated elasticity; the override is recorded in diagnostics.

### Diagnostics

T5 carries the following per-row diagnostic columns for review:

**Passenger rows:** `motorisation_level`, `saturation_level`, `k_used`, `k_clamped`, `is_saturated`, `saturation_source_flag`, `original_vehicle_equivalent_weight`, `adjusted_vehicle_equivalent_weight`, `weight_calibration_applied`.

**Freight rows:** `gdp_elasticity_used`, `freight_raw_elasticity`, `freight_elasticity_clamped`, `freight_energy_growth_rate`, `freight_gdp_growth_rate`, `freight_elasticity_data_source`.

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

## Module 5 - Vehicle Sales Share Preparation

### Purpose

Module 5 prepares base-year sales shares and seeded future sales-share trajectories. Researchers can then edit future sales shares in LEAP.

### Base-Year Sales Shares

Base-year EV sales data should be used first where available. Remaining sales shares should be filled from the observed stock structure or documented defaults.

Required checks:

- sales shares sum to 1 within each economy, scenario, year, transport type, and vehicle type;
- no negative sales shares;
- EV sales shares are not overwritten by residual ICE allocation;
- all fallback methods are flagged.

### Future Sales Share Seeding

The current implementation can create `T7f_future_shares` by scaling 9th edition sales-share trajectories to match the new base year. This is a bridge assumption, not an official policy scenario.

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

The nine-step workflow is implemented in `run_module6` (`codebase/modules/module6_leap_handoff.py`).

#### Step 1 — Initial branch energy

Calculate `energy_pj` for every branch using base-year stock, mileage, and efficiency from Module 2.

#### Step 2 — BEV and PHEV electricity reconciliation

Before touching liquid fuels, reconcile BEV and PHEV electricity to the ESTO road electricity total using the same scalar method as Steps 5–6. PHEV electricity and liquid fuel are calculated from the adjusted PHEV branches using the Module 1 `PHEV electric utilisation rate`, which is held fixed during reconciliation unless config explicitly allows it to move.

#### Step 3 — PHEV liquid fuel subtraction

Remove PHEV liquid fuel from the relevant ESTO pools before normal fuel reconciliation:

```text
remaining_esto_gasoline = ESTO_gasoline − PHEV_gasoline
remaining_esto_diesel   = ESTO_diesel   − PHEV_diesel
```

PHEV liquid fuels covered: Motor gasoline, Gas and diesel oil, Biodiesel, Biogasoline, Efuel. This prevents ICE reconciliation from absorbing energy that actually belongs to PHEVs.

#### Step 4 — Allocate remaining ESTO fuel to eligible branches

For each fuel, the remaining ESTO total is allocated across eligible branches using stock-share allocation by default. Eligibility is driven by `fuel_mappings.yaml` (`drive_fuel_eligibility`). This creates a provisional `allocated_branch_fuel_energy_pj` for each branch before scalar adjustment.

#### Step 5 — Derive energy correction factor

For each branch:

```text
ECF = allocated_branch_fuel_energy_pj / initial_branch_energy_pj
```

If a branch has zero initial energy but non-zero allocated ESTO energy (e.g. a hydrogen FCEV branch in an economy with no observed hydrogen use), the ECF is treated as zero and the branch scalars are clamped to their lower bounds rather than raising a division error.

#### Step 6 — Adjust stock, mileage, and efficiency simultaneously

The ECF is split across the three variables using configurable weights (defaults: stock=0.50, mileage=0.25, efficiency=0.25):

```text
stock_scalar      = ECF ^ 0.50
mileage_scalar    = ECF ^ 0.25
efficiency_scalar = ECF ^ −0.25     ← inverted: higher efficiency reduces energy
```

Because `efficiency` is km/GJ, increasing it lowers energy use. The negative exponent ensures the efficiency scalar moves in the direction that corrects the energy gap.

Each scalar is clamped to its configured per-scalar bounds from Module 1 (`reconciliation_bound_lower/upper_stock/mileage/efficiency`). Bounds are per-scalar by default, allowing stock wider movement than mileage or efficiency. Legacy single-tuple bounds are also supported for backward compatibility.

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
| Motor gasoline | ICE, HEV, PHEV, EREV | Biogasoline follows the same branches |
| Gas and diesel oil | ICE, HEV, PHEV, EREV | Biodiesel follows the same branches; freight-preferred allocation where ESTO diesel is freight-dominated |
| LPG | ICE only | Separate fuel from natural gas |
| Natural gas | ICE only | Separate fuel from LPG; biogas follows the same branches |
| Electricity | BEV, PHEV, EREV | Handled in Step 2 before normal reconciliation |
| Hydrogen | FCEV | Not expected in most base years; clamped to lower bound if no ESTO hydrogen observed |
| E-fuels | ICE, HEV, PHEV, EREV | Not expected in most base years |
| Ammonia | Not assigned to road unless a reviewed branch rule exists | — |

Any fuel present in ESTO but with no valid branch is flagged in T12.

### PHEV Treatment

PHEV branches carry two fuel streams: electricity and a liquid fuel (gasoline or diesel depending on the PHEV type). The electric utilisation rate (fraction of km driven on electricity) is a Module 1 input from `apec_phev_utilisation_rates.csv` and is held fixed during reconciliation.

After BEV/PHEV electricity is reconciled in Step 2, PHEV liquid fuel is computed and removed from the ESTO pools before ICE reconciliation. This preserves the ESTO fuel balance:

```text
final_gasoline = reconciled_non_phev_gasoline + phev_gasoline
final_diesel   = reconciled_non_phev_diesel   + phev_diesel
```

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

`Activity Level` is intentionally excluded. When a reference LEAP export is available, the final Excel workbook is written through `codebase/adapters/leap_import_writer.py`, which merges BranchID, VariableID, ScenarioID, and RegionID and returns structured warnings for unmatched rows.

## Module 7 - Optional Python Mirror and Post-LEAP Validation

### Purpose

Module 7 is a QA mirror, not the official projection engine. It can reproduce key LEAP-side calculations in Python and compare them with extracted LEAP results when those results are available.

### Responsibilities

Module 7 can:

- run a Python mirror of the stock-turnover calculation;
- calculate mirrored vehicle-km and energy;
- accept tidy LEAP output when provided;
- populate comparison columns without overwriting LEAP results;
- flag large differences for review.

### Outputs

Module 7 produces `T13_mirror_output`, with mirror values, optional LEAP values, differences, and validation flags.

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
- `codebase/modules/module6_leap_handoff.py`
- `codebase/modules/module7_mirror.py`

Support files:

- `scripts/generate_module1_defaults.py`
- `codebase/config/model_defaults.yaml` (guidance-only calibration reference; not a runtime fallback source)
- `codebase/config/fuel_mappings.yaml`
- `codebase/schemas/`
- `codebase/diagnostics/`

## Relationship to Other Documents

Use this guide for implementation sequence and module responsibilities.

Use `road_transport_model_simplified.md` for the shorter conceptual explanation.

Use `transition_audit_report.md` only for historical migration context. It is not the current implementation source of truth.
