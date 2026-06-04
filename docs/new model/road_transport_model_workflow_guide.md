<!-- markdownlint-disable MD024 MD025 MD033 -->

# Road transport model workflow guide

> **Purpose note**  
> This document is the implementation-oriented workflow guide for the road transport model in `leap_road_model`. It defines module boundaries, required logic, and expected outputs for the current codebase. For a shorter conceptual summary of the model, use `road_transport_model_detailed_description.md`. Where the current repo has refined an earlier design idea, this guide should follow the implemented method unless the text explicitly marks a future enhancement.

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
- PHEV electric utilisation rate and scalar bounds for Module 6;
- reconciliation weight settings where available in Module 1 outputs.

If local compatibility defaults are missing, refresh them with
`scripts/generate_module1_defaults.py`. The long-term package generator lives in
`road_model_inputs_interface`.

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
  Transport passenger road
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
  Transport freight road
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

### Passenger Stock

Passenger stock is projected using vehicle-equivalent ownership. This keeps the ownership envelope comparable when the vehicle mix shifts between LPVs, motorcycles, buses, and other passenger modes.

Required logic:

- calculate base-year passenger vehicle-equivalent ownership per capita;
- apply a Gompertz-style ownership curve using income or GDP-per-capita drivers;
- use Module 1 passenger saturation levels;
- use Module 1 vehicle-equivalent weights;
- clamp the growth parameter `k` within configurable bounds;
- flag economies that hit bounds or are already saturated.

For already saturated economies, passenger ownership should remain broadly stable and stock should mainly move with population unless a reviewed assumption says otherwise.

### Freight Stock

Freight stock is projected with a transparent GDP-elasticity method.

Required logic:

- estimate historical freight road activity growth where available;
- estimate a bounded GDP elasticity;
- project freight stock from GDP growth and the elasticity;
- apply fallbacks when the historical signal is missing or weak;
- flag fallback use and extreme elasticities.

The freight method intentionally prioritises reviewable diagnostics over an opaque freight-demand equation.

### Outputs

Module 3 produces stock target tables and diagnostics, including:

- passenger target stocks;
- freight target stocks;
- ownership and saturation diagnostics;
- `k` and elasticity values;
- fallback and review flags.

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

Module 6 builds the final Python-side road package for LEAP and reconciles base-year energy to ESTO.

### Handoff Package

Module 6 combines:

- Module 2 base-year branch data;
- Module 4 sales and lifecycle outputs;
- Module 5 sales shares;
- ESTO road fuel totals;
- Module 1 PHEV utilisation and reconciliation settings.

The LEAP-ready package should preserve economy, scenario, year, transport type, vehicle type, drive type, size, fuel, variable, value, units, and source metadata where available.

### Reconciliation Workflow

The current reconciliation workflow is:

1. Calculate initial branch energy from stock, mileage, and fuel economy.
2. Reconcile BEV and PHEV electricity before normal liquid/gaseous fuel reconciliation.
3. Calculate PHEV liquid fuel and subtract it from the relevant ESTO fuel pools.
4. Allocate remaining ESTO fuel totals to eligible branches.
5. Derive an energy correction factor for each branch.
6. Split that correction across stock, mileage, and efficiency using configurable weights and bounds.
7. Recalculate final branch energy.
8. Calculate implied vehicles and Device Shares.
9. Build reconciliation diagnostics.

### Fuel Allocation Rules

Fuel eligibility should come from configuration and branch mappings, not hard-coded one-off assumptions.

Current allocation principles:

- gasoline and diesel go to eligible ICE and relevant hybrid/liquid branches;
- LPG, natural gas, and biogas remain separate fuels even when their allocation logic is similar;
- electricity is handled through the BEV/PHEV electricity process;
- hydrogen is assigned to FCEV branches;
- e-fuels and other emerging fuels require explicit configuration;
- ammonia is not assigned to road unless a reviewed branch rule exists.

### PHEV Treatment

PHEV electricity and liquid fuel are calculated before normal gasoline/diesel reconciliation. The supplied PHEV electric utilisation rate should remain fixed unless configuration explicitly allows it to move.

Final PHEV outputs are expressed as LEAP Device Shares after accounting for different electric and liquid fuel economies.

### Outputs

Module 6 produces:

- `T8`: fuel allocation table;
- `T9`: reconciliation scalar table and reconciled branch values;
- `T10`: Device Share table;
- `T11`: LEAP-ready output table;
- `T12`: reconciliation diagnostics;
- `T12_phev`: PHEV utilisation diagnostics.

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
- `codebase/config/model_defaults.yaml` (legacy fallback; disabled unless explicitly reactivated)
- `codebase/config/fuel_mappings.yaml`
- `codebase/schemas/`
- `codebase/diagnostics/`

## Relationship to Other Documents

Use this guide for implementation sequence and module responsibilities.

Use `road_transport_model_detailed_description.md` for the shorter conceptual explanation.

Use `transition_audit_report.md` only for historical migration context. It is not the current implementation source of truth.
