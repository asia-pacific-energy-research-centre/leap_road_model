# Road transport model conceptual summary

> **Purpose note**
> This document is the compact conceptual description of the road transport model in `leap_road_model`. For module sequencing, implementation details, and table outputs, use `road_transport_model_detailed.md`. For Module 1 data sourcing, the CSV contract, researcher UI workflow, and the static row contract, use `multinode_road_module1_repo_guide.md` in `road_model_inputs_interface/docs/new model/`.

## Contents

1. [Scope](#1-scope)
2. [Model Logic](#2-model-logic)
3. [Inputs Needed Before LEAP](#3-inputs-needed-before-leap)
4. [Passenger Stock](#4-passenger-stock)
5. [Freight Stock](#5-freight-stock)
6. [Sales, Survival, and Turnover](#6-sales-survival-and-turnover)
7. [Sales Shares](#7-sales-shares)
8. [Base-Year Energy and Reconciliation](#8-base-year-energy-and-reconciliation)
9. [LEAP Export Package](#9-leap-export-package)
10. [How to Read the T Tables](#10-how-to-read-the-t-tables)
11. [Validation Checks](#11-validation-checks)
12. [Current Reference Files](#12-current-reference-files)

![End-to-end road model workflow](End-to-end%20road%20model%20workflow%208062026.png)

*Primary reference for the full end-to-end workflow. Some implementation detail is not shown.*

![Road transport model — quick view](Road%20transport%20model%20%E2%80%94%20quick%20view.png)

## 1. Scope

The road transport model is a Python-prepared, LEAP-executed stock-flow model. Python prepares calibrated base-year inputs and scenario assumptions; LEAP remains the official projection platform.

The road branch hierarchy runs `transport type → vehicle type → drive type + size where relevant → fuel type`. Each leaf in the tree below is a LEAP branch:

```text
Demand
  Passenger road
    LPVs                                 [sizes: small, medium, large]
      ICE <size>
        Motor gasoline, Gas and diesel oil, Natural gas, LPG, LNG
        Biogasoline, Biodiesel, Biogas, Efuel
      HEV <size>
        Motor gasoline, Gas and diesel oil, Biogasoline, Biodiesel, Efuel
      EREV <size>
        Electricity, Motor gasoline, Biogasoline, Efuel
      PHEV <size>
        Electricity, Motor gasoline, Biogasoline, Efuel
      BEV <size>
        Electricity
      FCEV <size>
        Hydrogen
    Motorcycles
      ICE
        Motor gasoline, Gas and diesel oil, Natural gas, LPG, LNG
        Biogasoline, Biodiesel, Biogas, Efuel
      BEV
        Electricity
      FCEV
        Hydrogen
    Buses
      ICE
        Motor gasoline, Gas and diesel oil, Natural gas, LPG, LNG
        Biogasoline, Biodiesel, Biogas, Efuel
      BEV
        Electricity
      FCEV
        Hydrogen
  Freight road
    Trucks                               [sizes: medium, heavy]
      ICE <size>
        Motor gasoline, Gas and diesel oil, Natural gas, LPG, LNG
        Biogasoline, Biodiesel, Biogas, Efuel
      BEV <size>
        Electricity
      FCEV <size>
        Hydrogen
    LCVs
      ICE
        Motor gasoline, Gas and diesel oil, Natural gas, LPG, LNG
        Biogasoline, Biodiesel, Biogas, Efuel
      PHEV
        Electricity, Motor gasoline, Biogasoline, Efuel
      BEV
        Electricity
      FCEV
        Hydrogen
```

Scope notes (useful when comparing to the 9th edition and earlier 10th edition LEAP models):

- `HEV` and `EREV` are LPV-only.
- Truck `PHEV` is out of scope.
- LCVs and LPVs can use PHEV; Buses and Motorcycles do not.
- HEV excludes gaseous fuels (LPG, Natural gas, LNG, Biogas) — those are ICE-only.
- Size labels appear as a suffix on the drive type in LEAP branch paths, e.g. `ICE medium`, `BEV heavy`.

## 2. Model Logic

At a high level, the road workflow does this:

```text
input preparation
base-year branch parsing
passenger and freight stock target projection
sales, survival, vintage, and turnover calculation
base-year sales share preparation
base-year energy calculation
fuel allocation and ESTO reconciliation
Device Share calculation
LEAP input package creation
optional Python mirror validation
```

![Road model module workflow and end-to-end handoff](Road%20model%20module%20workflow%20and%20end-to-end%20handoff.png)

The pipeline is now two linked repositories: `road_model_inputs_interface`
generates and preserves the Module 1 long CSV package, while `leap_road_model`
loads that package, runs Modules 2 to 6, and writes diagnostics and the LEAP
import workbook.

The goal is a calibrated base-year road model that matches ESTO road energy by fuel while producing the stock, sales, mileage, fuel economy, Device Share, survival, and projection inputs needed by LEAP.

## 3. Inputs Needed Before LEAP

Base-year inputs:

- vehicle stock;
- mileage;
- fuel economy in the canonical `Fuel Economy` variable;
- ESTO road energy by fuel;
- population and GDP drivers;
- base-year sales shares where observed;
- survival curves and vintage profiles;
- PHEV electric utilisation assumptions;
- reconciliation weights and scalar bounds.

Projection inputs:

- population and GDP projections;
- passenger saturation assumptions;
- vehicle-equivalent weights;
- passenger stock growth-rate adjustment;
- freight GDP-elasticity adjustment;
- vehicle-type `Stock Share` assumptions for LPVs, motorcycles, buses, trucks,
  and LCVs;
- freight road energy and GDP history for elasticity estimation;
- base-year and future `Sales Share` rows;
- mileage, efficiency, and scrappage assumptions for LEAP scenarios.

Module 1 defaults are the primary upstream source for base-year road assumptions
in the current workflow. The target package is generated by
`road_model_inputs_interface` as one long CSV per economy, using underscore
economy codes such as `20_USA` and columns such as `Economy`, `Scenario`,
`Branch Path`, `Variable`, `Year`, and `Value`. `codebase/road_workflow.py`
loads that package before Modules 2 to 6 run. Older wide packages under
`input_data/module1_defaults/` are legacy compatibility inputs during migration.

## 4. Passenger Stock

Passenger stock is projected in vehicle-equivalent ownership terms. This avoids treating one bus, one motorcycle, and one LPV as identical when calculating the passenger motorisation envelope.

Module 1 `Stock Share` rows are physical vehicle-count shares. The workflow
uses the five LEAP vehicle-type branches and converts passenger physical shares
to LPV-equivalent capacity shares internally before allocating the passenger
motorisation envelope.

The passenger method:

1. Calculates base-year vehicle-equivalent ownership per capita.
2. Projects ownership toward a saturation level.
3. Uses configurable vehicle-equivalent weights.
4. Applies the Module 1 `Passenger Stock Growth Rate Adjustment` multiplier to
   the estimated S-curve growth parameter before bounds are applied.
5. Applies bounds to the final growth parameter.
6. Flags already saturated economies and bound hits for review.

For saturated economies, ownership should remain broadly stable unless a reviewed economy-specific assumption says otherwise.

After Module 6 reconciliation, passenger stock targets can be re-anchored to
the reconciled base-year stock. The model preserves the original final-year
physical stock target and fades the base-year reconciliation adjustment to zero
by the final projection year.

## 5. Freight Stock

Freight stock is projected with a bounded GDP-elasticity method. The method uses historical freight road activity or energy signals where available, then applies a transparent elasticity to GDP growth.

The truck/LCV split is held flat at base-year proportions and is not researcher-adjustable. There are no strong projected trends in the truck/LCV mix across APEC economies, so the base-year split is treated as a fixed structural parameter. Researchers should not edit freight `Stock Share` values in Module 1; the 2040 and 2060 anchor values are seeded equal to the base year as a deliberate default.

Module 1 also exposes a `Freight GDP Elasticity Adjustment` multiplier. A value
of `1.0` keeps the estimated elasticity unchanged; values above or below `1.0`
scale the estimated elasticity before it is clamped to bounds.

This part of the model should remain highly diagnostic. Missing historical data, weak trends, adjustments, and bounded elasticities should be visible in review outputs. The current implementation carries diagnostics through Module 3 outputs: raw elasticity, final elasticity, whether it was clamped, freight energy growth, GDP growth, adjustment value, data source, and a short note.

### How the current projection works

`project_freight_stocks` (`codebase/modules/module3_stock_targets.py`) operates in three steps:

1. **Estimate one GDP elasticity** from historical freight road energy growth vs GDP growth over the preceding 10 years (COVID years excluded). The elasticity is multiplied by the Module 1 adjustment, clamped to [0.0, 2.0], and defaults to 0.8 if data are insufficient.

2. **Project a single physical-count total** from the sum of base-year Truck and LCV stocks:

   ```text
   total_physical_base = Trucks_base + LCVs_base
   total_physical(year) = total_physical_base × (GDP(year) / GDP_base) ^ elasticity
   ```

3. **Allocate to vehicle types** using fixed physical-count shares from the base year:

   ```text
   target_stock(vt, year) = total_physical(year) × share_physical(vt)
   ```

   where `share_physical(vt) = base_stock(vt) / total_physical_base`.

Because the shares are held flat, this is identical to applying the same elasticity factor to each vehicle type independently — the total-first architecture is already in place but currently uses a plain physical count rather than a weighted aggregate.

After Module 6 reconciliation, freight stock targets can be re-anchored to the
reconciled base-year stock. Freight preserves the original GDP-elasticity growth
index from the reconciled base, so the growth shape stays the same while the
physical stock level moves with the reconciled starting point.

### Relationship to the passenger approach

The passenger projection (`project_passenger_stocks`) uses a structurally similar pattern but with weighted totals:

| Step | Passenger | Freight (current) |
| --- | --- | --- |
| Aggregate | weighted stock / population = LPV-equiv per capita | physical count total |
| Projection driver | logistic S-curve, GDP per capita | GDP elasticity |
| Normalisation denominator | population | — (absolute count) |
| Back-calculation | `(total_weighted × capacity_share) / weight` | `total_physical × physical_share` |

For passenger, the weighted aggregate is necessary because one bus replaces ~20 LPVs of ownership demand; treating them as identical physical units would give a meaningless motorisation level. For freight, the equivalent argument would be that one truck represents ~3.3 LCV-equivalents (Trucks=5.0, LCVs=1.5 in `model_defaults.yaml` and `apec_vehicle_equivalent_weights.csv`), so the freight capacity index should track weighted stock rather than vehicle count.

### Why the weighted-index approach is not implemented

With the truck/LCV split held flat, the two approaches produce identical projected stock counts. Proof:

```text
# Passenger-style (weighted):
total_weighted_base = Trucks_base × 5.0 + LCVs_base × 1.5
total_weighted(y)   = total_weighted_base × GDP_ratio^e
capacity_share(vt)  = base_stock(vt) × weight(vt) / total_weighted_base
target(vt, y)       = total_weighted(y) × capacity_share(vt) / weight(vt)
                    = base_stock(vt) × GDP_ratio^e   ✓ same result

# Physical-count (current):
total_physical_base = Trucks_base + LCVs_base
total_physical(y)   = total_physical_base × GDP_ratio^e
physical_share(vt)  = base_stock(vt) / total_physical_base
target(vt, y)       = total_physical(y) × physical_share(vt)
                    = base_stock(vt) × GDP_ratio^e   ✓ same result
```

The two methods diverge only if the researcher can supply time-varying shares
that shift the truck/LCV mix. Since that input is deliberately not exposed, the
weighted approach adds no new information to the projection. The main benefit it
would bring is a meaningful single-number diagnostic — a `freight_stock_index`
analogous to the `M_envelope` for passenger — which is currently not needed.

If the model later allows a researcher-adjustable truck/LCV split, that change
should be paired with a weighted freight capacity index. Using time-varying
physical-count shares with a physical-count total would make the aggregate
freight trajectory depend on which vehicle type grows faster.

## 6. Sales, Survival, and Turnover

The stock-flow accounting identity is:

```text
ending stock = surviving prior stock + new sales - additional retirements
```

Survival curves, vintage profiles, and additional retirement policies convert target stock paths into sales and retirements. Temporary scrappage policies should be represented in LEAP as explicit year-specific scrappage assumptions rather than hidden in a permanent survival curve.

When surviving cohorts already exceed the target stock, Module 4 records the
event with `stock_above_target` and the `scale_factor_applied` used to bring the
fleet down to the target. This makes naturally shrinking fleets visible in the
dashboard and validation outputs.

These are needed in LEAP as separate inputs to the usual import workbook structure. They also need to be calculated with stock targets in mind, since leap road model uses a sales-driven structure rather than a stock-driven structure. The sales shares module then allocates sales across branches, which in turn determines the stock structure that emerges from the survival curves and vintage profiles. If the wrong profiles are used, the resulting stock structure may not match the intended targets. For a similar reason the sales share between vehicle types is important to plan upfront rather than while modlling in LEAP, becuase that also has a major effect on stock structure that LEAP cannot cature, due to the LPV-equivalent assumptions for buses and motorcycles and how that affects the passenger motorisation envelope.

## 7. Sales Shares

Base-year `Sales Share` rows are loaded from Module 1 and can override the
model-computed base-year shares. Where those rows are absent, Module 5 computes
base-year shares from the base-year stock structure and optional observed EV
sales data.

Future `Sales Share` rows are part of the Module 1 package contract for projected scenarios. They are seeded from 9th edition trajectories re-anchored to the new base year and are the main starting point for the LEAP sales-share scenario. The Module 1 interface does not currently expose researcher editing of future sales shares; the expectation is that researchers will edit them directly in LEAP after the base-year handoff.

If no future rows are received from Module 1, Module 5 falls back to a flat projection from base-year shares. When future rows are available but need re-anchoring, the module preserves the provided non-ICE trajectory shape where possible and keeps ICE as the residual; if that would make ICE negative, it switches to a linear interpolation fallback and flags the case.

## 8. Base-Year Energy and Reconciliation

Initial branch energy is calculated from stock, mileage, and fuel economy. Module 6 then reconciles the result to ESTO fuel totals.

The reconciliation sequence is:

1. Calculate branch energy.
2. Reconcile BEV and PHEV electricity.
3. Calculate and subtract PHEV liquid fuel from the relevant ESTO liquid fuel pools.
4. Allocate remaining ESTO fuel to eligible branches.
5. Split each branch correction across stock, mileage, and fuel economy using configurable weights and bounds.
6. Recalculate final energy and Device Shares.

Fuel eligibility comes from configuration. Electricity is handled through the BEV/PHEV process. PHEV and EREV are treated alike; EREV is modeled like a more efficient PHEV. Their liquid fuel is gasoline-family only for passenger and freight branches: Motor gasoline, Biogasoline, and Efuel are allowed, while diesel and biodiesel are not. Alternative fuels are spread as a constant proportion of the corresponding original fuel family's use across eligible branches.

Conventional liquid fuels use reviewed priority rules before ordinary stock-share
allocation. Diesel and biodiesel are allocated to trucks first, then LCVs, then
passenger vehicles if freight demand has already been saturated. Gasoline and
biogasoline are allocated to passenger vehicles first, then LCVs; they are not
allocated to trucks under the road priority rule. Within a priority tier,
allocation is proportional to branch stock.

Known modeling risk: `Biodiesel` and `Biogasoline` are currently allocated as
separate observed ESTO fuel streams. When ESTO biofuel energy is large relative
to eligible modeled demand, this can create high biofuel Device Shares and make
LEAP/dashboard outputs look like dedicated biofuel vehicle penetration rather
than blended fuel use. The behavior is left unchanged for now.

## 9. LEAP Export Package
The LEAP-ready package contains:

- calibrated base-year stock, mileage, fuel economy, and Device Share values;
- sales, survival, vintage, and scrappage inputs;
- base-year and seeded future sales shares;
- scenario, region, branch path, units, and source metadata needed for LEAP import and diagnostics.

T11 follows LEAP branch levels: transport/vehicle stock rows, transport sales
rows, fuel-level mileage/fuel-economy/device-share rows, and share-control rows
for `Sales Share` and `Stock Share`. `Activity Level` is excluded. The strict
Excel writer merges LEAP ID columns from a reference export and returns warnings
for unmatched rows before writing the `LEAP` and `FOR_VIEWING` sheets. The
`LEAP` sheet preserves the import structure used by LEAP exports: ID columns,
logical row-key columns, metadata columns, `Expression`, a blank spacer column,
and `Level 1` through `Level 8...`. The Level columns are generated from
`Branch Path` by splitting on `\`; blank hierarchy levels remain blank. The
repo-local reference template is
`input_data/leap_import_templates/DEFAULT_transport_leap_import_TGT_REF_CA.xlsx`.

The package should preserve enough metadata to trace whether values came from researcher input, defaults, scaling, reconciliation, or fallback logic.

## 10. How to Read the T Tables

The workflow uses `T*` table names as stable output and diagnostic labels. They
are lineage names, not module numbers.

| Table | Plain-English meaning |
| --- | --- |
| `T4` | Base-year branch table from Module 2: stock, mileage, fuel economy, dimensions, and branch paths by road technology/fuel branch. |
| `T5` | Module 3 stock targets by year and vehicle type, including passenger saturation diagnostics and freight GDP-elasticity diagnostics. |
| `T6` | Module 4 sales and turnover table: target stock, surviving stock, sales, retirements, and stock-flow diagnostics. |
| `T6v` | Module 4 vintage profile table: base-year age distribution used by turnover. |
| `T7` | Module 5 base-year sales shares by vehicle and drive type. |
| `T7f` | Module 5 future sales-share trajectories, either from explicit inputs, Module 1 projected rows, scaling, or fallback logic. |
| `T8` | Module 6 provisional fuel allocation from ESTO totals to eligible road branches. |
| `T9` | Module 6 reconciliation scalars and adjusted base-year stock, mileage, and fuel economy. |
| `T10` | Module 6 Device Shares after reconciliation. |
| `T11` | LEAP-ready long table used to write the import workbook. |
| `T12` | Module 6 fuel reconciliation diagnostics and validation status. |
| `T12_phev` | PHEV electric/liquid utilisation diagnostics. |
| `T13` | Optional Module 7 Python mirror outputs for QA. |

### Pre- and post-reconciliation naming

Before Module 6 re-anchors stock trajectories, the active Module 3 and 4 tables
are simply `T5`, `T6`, and `T6v`. If re-anchoring happens, the workflow saves
those original tables as `T5_pre_reconciliation`, `T6_pre_reconciliation`, and
`T6v_pre_reconciliation`, then replaces the active downstream tables with
post-reconciliation versions.

This means:

- if re-anchoring did not run, plain `T5`, `T6`, and `T6v` are already
  pre-reconciliation;
- if re-anchoring did run, `T5`, `T6`, and `T6v` are the active
  post-reconciliation tables, and the original Module 3/4 outputs live under
  the `*_pre_reconciliation` names;
- `module3.html` should show the original pre-reconciliation stock, sales, and
  turnover view;
- `module3_post_reconciliation.html` should show only charts whose values
  changed after stock re-anchoring.

Passenger and freight stock re-anchoring behave differently. Passenger keeps
the original final-year physical stock target and fades the base-year adjustment
to zero. Freight keeps the original growth index from the reconciled base-year
stock, so its index chart keeps the same shape while physical stock levels move
with the reconciled base.

## 11. Validation Checks

Core validation checks are:

- no duplicate key records;
- required dimensions are present;
- stock, mileage, fuel economy, sales, and shares are valid and non-negative;
- sales shares and Device Shares sum correctly;
- base-year fuel totals match ESTO within tolerance;
- PHEV utilisation diagnostics remain within tolerance;
- large reconciliation scalars and fallback assumptions are flagged.

## 12. Current Reference Files

Use these files for the current implementation:

- `codebase/road_workflow.py`
- `codebase/adapters/road_module1_defaults.py`
- `codebase/adapters/leap_import_writer.py`
- `codebase/modules/module2_base_year.py`
- `codebase/modules/module3_stock_targets.py`
- `codebase/modules/module4_sales_turnover.py`
- `codebase/modules/module5_sales_shares.py`
- `codebase/modules/module6_reconciliation_and_leap_handoff.py`
- `codebase/modules/module7_mirror.py`
- `scripts/generate_module1_defaults.py` (legacy/backfill helper for `input_data/module1_defaults/`, not the preferred source update path)
- `codebase/config/workflow_defaults.yaml` (runtime workflow switches and paths)
- `codebase/config/model_defaults.yaml` (guidance-only calibration reference)
