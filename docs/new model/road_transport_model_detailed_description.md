# Road transport model detailed description

> **Purpose note**  
> This document is the compact conceptual description of the road transport model in `leap_road_model`. It summarises the current methodology and main implementation choices without reproducing the full module-by-module build workflow. For implementation sequencing, module responsibilities, and handoff details, use `road_transport_model_workflow_guide.md`.
> **Implementation status note**  
> The current orchestrator path (`codebase/road_workflow.py`) now assumes
> Module 1 defaults are the primary upstream source for base-year road
> assumptions (loaded from `input_data/module1_defaults/`), with Modules 2–6
> executed after that handoff.

## 1. Scope

The road transport model is a stock-flow model built in Python before being exported into LEAP.

It covers:

```text
Transport road
├─ Freight road
│  ├─ Trucks
│  └─ LCVs
└─ Passenger road
   ├─ Motorcycles
   ├─ Buses
   └─ LPVs
```

The hierarchy is:

```text
transport type → vehicle type → drive type → fuel type
```

In the current implementation, LPVs carry an explicit size bucket in technology
labels, using `small` / `medium` / `large` for LPV mapping. Trucks retain
`medium` / `heavy` size labels where truck-size splits are used.

Use:

```text
transport type = passenger / freight
vehicle type = LPVs / Motorcycles / Buses / Trucks / LCVs
drive type = ICE / BEV / FCEV / PHEV, plus LPV-only HEV / EREV
fuel type = gasoline / diesel / electricity / hydrogen / LPG / natural gas / other fuels where relevant
```

Scope rule:

- `HEV` and `EREV` are LPV-only in the current policy.
- Truck `PHEV` is out of scope.

The road model performs:

```text
input preparation
passenger stock and sales calculation
freight stock and sales calculation
survival and vintage accounting
initial base-year energy calculation
fuel allocation
Device Share calculation
PHEV electricity / liquid-fuel treatment
ESTO reconciliation
LEAP input package creation
```

The goal is to create a calibrated base-year road model that matches ESTO energy by fuel, while producing stock, sales, mileage, efficiency (km/GJ), Device Share, survival and projection inputs that can be used inside LEAP.

---

## 2. Inputs needed before LEAP

### 2.1 Base-year inputs

```text
base-year vehicle stock
base-year mileage
base-year efficiency (km/GJ)
base-year road energy by fuel from ESTO
population
GDP per capita
vehicle ownership
vehicle ownership saturation level
historical road energy by fuel
estimated passenger / freight road energy split
fuel allocation rules
PHEV electric / liquid-fuel driving split
survival profiles
vintage profiles
```

Definitions:

```text
vehicle stock:
Number of vehicles in each transport type, vehicle type and drive type.

mileage:
Annual distance travelled per vehicle.

efficiency (km/GJ):
Distance travelled per unit energy.

vehicle ownership:
Passenger vehicles per person or per 1,000 people.

vehicle ownership saturation:
Long-run passenger ownership ceiling.

ESTO road energy:
Base-year road energy by fuel. This is the reconciliation target.

estimated passenger / freight road energy split:
Used to separate historical road energy growth into passenger and freight components where direct historical activity data are unavailable.
```

---

### 2.2 Projection inputs

```text
population projection
GDP per capita projection
manufacturing or industrial GDP projection
total GDP projection
sales share by vehicle type
sales share by drive type
mileage adjustment variables
efficiency adjustment variables
Device Share assumptions
scrappage assumptions
PHEV Device Share assumptions
researcher overrides
```

Definitions:

```text
sales share by vehicle type:
Share of total road sales allocated to LPVs, Motorcycles, Buses, Trucks and LCVs.

sales share by drive type:
Share of vehicle sales allocated to drive branches (for example ICE, BEV,
FCEV, PHEV, and LPV-only HEV/EREV where applicable).

mileage adjustment variable:
Scenario multiplier applied to projected mileage.

efficiency adjustment variable:
Scenario multiplier applied to efficiency (km/GJ) or energy intensity.

Device Share:
Split of a drive branch across fuel branches in LEAP.

scrappage assumptions:
Scenario assumptions that accelerate or slow vehicle retirement.

researcher overrides:
Explicit economy-specific assumptions that replace or modify default modelled values.
```

---

## 3. Passenger road stock and sales calculation

Passenger road stock is based on population, ownership growth, ownership saturation and survival.

Core structure:

```text
population
→ vehicle ownership
→ target passenger stock
→ surviving stock
→ required annual sales
```

Core formulas:

```text
target_passenger_stock =
population × vehicle_ownership
```

```text
annual_sales =
target_passenger_stock - surviving_stock + replacement_sales
```

If annual sales are negative:

```text
annual_sales = 0
```

and stock is allowed to decline through retirements.

---

### 3.1 Passenger ownership growth

Passenger ownership is represented through a motorisation envelope rather than a free-form growth rule.

The current implementation uses a logistic / Gompertz-style passenger motorisation curve calibrated from recent historical passenger road energy growth.

Conceptual process:

```text
1. Convert base-year passenger stock into a vehicle-equivalent motorisation level.
2. Resolve a saturation level from researcher input or a documented fallback.
3. Estimate recent passenger road energy growth over a configurable lookback window.
4. Exclude COVID-disrupted years from that calibration window.
5. Convert recent energy growth into an S-curve steepness parameter k.
6. Clamp k to configured bounds.
7. Project the passenger motorisation envelope toward saturation.
8. Convert the envelope back into passenger stock using population.
```

Core relationships:

```text
M_base = vehicle-equivalent passenger stock / population

k ≈ recent_passenger_energy_growth / (1 - M_base / M_sat)

M(y) = logistic motorisation envelope toward M_sat

target_passenger_stock(y) = M(y) × population(y)
```

For already-saturated economies, the envelope is held broadly flat and stock mainly changes with population.

This keeps the method explicit, configurable, and close to the implemented Module 3 logic.

Suggested input fields:

```text
economy
scenario
year
population
GDP_per_capita
historical_passenger_road_energy
estimated_passenger_energy_share
ownership_saturation_level
passenger_growth_method
passenger_growth_source
notes
```

Possible methods:

```text
logistic_motorisation_curve
researcher_defined
previous_Outlook_projection
simple_growth_assumption
```

Validation checks:

```text
ownership does not exceed saturation unless explicitly allowed
growth slows as ownership approaches saturation
population data exist for all projection years
GDP per capita data exist where required
passenger/freight energy split is documented
researcher overrides are reported
```

---

### 3.2 Passenger vehicle type split

Passenger target stock and sales are split across:

```text
LPVs
Motorcycles
Buses
```

using:

```text
base-year stock shares
sales share by vehicle type
researcher-defined vehicle type assumptions
scenario assumptions
```

The vehicle type split can change over time.

Example:

```text
Passenger road sales:
LPVs 70%
Motorcycles 20%
Buses 10%
```

Vehicle type sales shares must sum to 100% within passenger road.

---

### 3.3 Passenger drive type split

Vehicle sales are then split into:

```text
ICE
HEV
EREV
BEV
FCEV
PHEV
```

using sales share by drive type.

Example:

```text
LPV sales:
ICE 30%
HEV 8%
EREV 2%
BEV 60%
PHEV 10%
FCEV 0%
```

Drive type sales shares must sum to 100% within each vehicle type.

These assumptions are intended to be adjustable in LEAP.

---

## 4. Freight road stock and sales calculation

Freight road does not use passenger ownership saturation.

Instead, freight stock follows projected freight activity or a freight proxy variable.

This is one of the weaker parts of the transport model and should be flagged as an area where the method may need more work later.

---

### 4.1 Freight activity growth proxy

Freight road is projected using GDP elasticity rather than a passenger-style ownership curve.

The current implementation estimates freight elasticity from historical freight road energy growth and GDP growth over a configurable lookback window, excluding COVID-disrupted years.

Conceptual formula:

```text
freight_elasticity =
average annual freight road energy growth / average annual GDP growth
```

Then:

```text
target_freight_stock(y) =
base_year_freight_stock × (GDP(y) / GDP_base) ^ freight_elasticity
```

In the current codebase this uses total GDP as the main projection driver. Manufacturing or industrial GDP can still be used later as an override or enhancement where that gives a better freight signal.

Historical freight road energy growth is used directly in elasticity estimation and should also be checked as a diagnostic.

Suggested metadata fields:

```text
freight_projection_source
freight_projection_method
freight_projection_notes
freight_gdp_series_used
freight_elasticity_used
historical_freight_road_energy_growth_for_review
```

---

### 4.2 Freight stock calculation

Freight stock should follow the GDP-elasticity projection.

Core structure:

```text
GDP projection
→ elasticity-calibrated freight growth
→ target freight stock
→ surviving stock
→ required annual sales
```

Formula:

```text
target_freight_stock =
base_year_freight_stock × (GDP / GDP_base) ^ elasticity
```

Then:

```text
annual_sales =
target_freight_stock - surviving_stock + replacement_sales
```

Vehicle types:

```text
Trucks
LCVs
```

Drive types:

```text
ICE
BEV
FCEV
PHEV (where applicable, excluding truck PHEV in the current scope policy)
```

---

### 4.3 Freight data sources

Possible data sources:

```text
manufacturing GDP
industrial GDP
total GDP
historical freight road energy
previous Outlook freight projections
researcher-defined freight projections
freight tonne-km where available
trade volume where relevant
construction activity where relevant
```

Fallback options:

```text
historical freight stock growth
previous Outlook freight projections
configured default elasticity
```

The freight method should prioritise transparency and bounded, reviewable elasticity estimates over a more opaque freight-demand equation.

Validation checks:

```text
freight growth inputs exist for all projection years
freight stock does not become negative
freight sales do not become negative unless explicitly allowed
freight method and data source are documented
```

---

## 5. Lifecycle profiles

Lifecycle profiles keep stock-flow accounting coherent.

They handle:

```text
survival profiles
vintage profiles
retirement rates
scrappage assumptions
policy-adjusted turnover
```

Functions should:

```text
convert cumulative survival assumptions into year-by-year survival probabilities
derive matching vintage profiles
calculate surviving stock
calculate retirements
preserve stock consistency
```

The lifecycle editor is a calibration and accounting tool, not a direct fit to noisy real-world age distributions.

It should support:

```text
accelerated ICE retirement
policy scrappage
average vehicle age adjustments
survival-shape adjustments
```

without breaking stock totals or ownership targets.

---

## 6. Base-year road energy and reconciliation

The base-year road model combines:

```text
vehicle stock
mileage
efficiency (km/GJ)
PHEV electricity / liquid-fuel calculation
fuel allocation
Device Share calculation
ESTO comparison
weighted scalar reconciliation
validation
```

The goal is to create a calibrated base-year road system that matches ESTO road energy by fuel while preserving plausible transport assumptions.

---

### 6.1 Initial road energy calculation

Initial road energy is calculated before reconciliation.

Core formulas:

```text
activity =
stock × mileage
```

```text
initial_energy =
stock × mileage / efficiency_km_per_gj
```

where efficiency is expressed as distance per unit of energy, for example km/GJ.

Outputs:

```text
economy
scenario
year
transport type
vehicle type
drive type
fuel type
stock
mileage
efficiency_km_per_gj
activity
initial energy
```

At this stage, energy totals will usually not match ESTO.

---

### 6.2 Fuel simplification rules

Some fuels may require simplification or aggregation before reconciliation where detailed stock data are unavailable.

The current implementation keeps fuel eligibility explicit through configuration and branch mappings. Any simplification rules such as combining biofuels with their fossil equivalents should be treated as configurable preprocessing assumptions rather than hard-coded model logic.

Suggested config file:

```text
config/dummy_inputs/road_fuel_simplification_rules.csv
```

---

### 6.3 Fuel allocation and Device Share calculation

ESTO gives road energy by fuel, but not by vehicle-drive branch.

The model therefore allocates fuel energy across eligible branches.

Workflow:

```text
ESTO fuel totals
→ eligible vehicle-drive branches
→ allocated branch fuel energy
→ implied vehicles by fuel
→ Device Share
```

Core formulas:

```text
energy_per_vehicle =
mileage / efficiency_km_per_gj
```

```text
implied_vehicles_using_fuel =
allocated_branch_fuel_energy / energy_per_vehicle
```

```text
Device Share =
implied_vehicles_using_fuel / total_vehicles_in_drive_branch
```

Device Share is a split within a drive branch.

Example:

```text
ICE LPVs
├─ gasoline
├─ LPG
└─ natural gas
```

Device Share is not directly an activity share.

---

### 6.4 Configurable fuel allocation rules

Fuel allocation rules should be configurable and economy-specific.

Create a configurable allocation rules table:

```text
config/dummy_inputs/road_fuel_allocation_rules.csv
```

Suggested fields:

```text
economy
fuel
preferred_branch
eligible_branches
overflow_rule
default_distribution_rule
special_case_flag
notes
```

The allocation system should support:

```text
preferred allocation branches
eligible fallback branches
overflow handling
default distributions
economy-specific exceptions
```

---

#### 6.4.1 Diesel allocation logic

Default diesel behaviour:

```text
Diesel and related diesel fuels
→ freight ICE branches first
```

This includes:

```text
gas and diesel oil
diesel blends
biodiesel where merged into diesel
```

Overflow rule:

```text
If freight ICE branches cannot absorb all diesel and related diesel energy,
allocate the remaining diesel energy to other eligible ICE branches,
typically passenger ICE vehicles.
```

This reflects the fact that diesel passenger vehicles are plausible in many economies.

---

#### 6.4.2 Gasoline allocation logic

Default gasoline behaviour:

```text
Motor gasoline
→ passenger ICE branches first
```

Overflow rule:

```text
If passenger ICE branches cannot absorb all gasoline energy,
raise an allocation exception by default.
```

Do not automatically allocate excess gasoline into freight branches unless:

```text
the economy is configured as a special case
or
explicit allocation rules allow freight gasoline use
```

This prevents unrealistic freight gasoline allocation in economies where freight is overwhelmingly diesel-based.

---

#### 6.4.3 LPG and natural gas allocation logic

LPG and natural gas should generally already exist across eligible ICE branches.

Default rule:

```text
Distribute LPG and natural gas across eligible ICE branches
using stock-weighted or configurable default shares.
```

Possible allocation methods:

```text
equal distribution
stock-weighted distribution
researcher-defined ratios
economy-specific allocation rules
```

These fuels should not rely on overflow allocation as the primary mechanism unless explicitly configured.

---

#### 6.4.4 Electricity allocation logic

Electricity is allocated to:

```text
BEV branches
PHEV electric branches where enabled
```

Before the normal reconciliation process, BEV and PHEV electricity demand should be compared with ESTO road electricity using the electricity-only reconciliation method in Section 6.6.

---

#### 6.4.5 Hydrogen allocation logic

Hydrogen is allocated to:

```text
FCEV branches
```

Raise an exception if:

```text
hydrogen energy exists
but no eligible FCEV branch exists
```

unless a fallback rule is configured.

---

#### 6.4.6 E-fuels and other emerging fuels

E-fuels and other fuels that may not appear in the ESTO base-year road data should be handled case by case.

If a fuel appears in projection years but not in the ESTO base year, do not force it into base-year reconciliation.

Instead, define its eligible branches, allocation rule, and projection assumption in the same configurable road fuel allocation rules table.

---

#### 6.4.7 Allocation validation rules

Validation checks:

```text
all allocated fuel energy equals ESTO fuel totals
all allocated branches are eligible for the fuel
overflow allocations are documented
gasoline overflow into freight raises an exception unless explicitly allowed
fuel allocation rules exist for all active fuels
allocation exceptions appear in the reconciliation report
```

Suggested outputs:

```text
road_fuel_allocation_<economy>_<scenario>.csv
road_fuel_overflow_report_<economy>_<scenario>.csv
road_fuel_allocation_exceptions_<economy>_<scenario>.csv
```

---

### 6.5 PHEV electricity and liquid-fuel treatment

PHEVs require an assumption about how driving is split between electric driving and liquid-fuel driving.

In the current implementation, the electric utilisation rate can be a single default value or a vehicle-type-specific value.

Suggested input fields:

```text
economy
scenario
year
transport_type
vehicle_type
drive_type
electric_driving_share
liquid_fuel_driving_share
liquid_fuel_type
source
notes
```

Example:

```text
PHEV LPVs:
electric_driving_share = 0.60
liquid_fuel_driving_share = 0.40
liquid_fuel_type = gasoline
```

Important:

```text
electric-driving activity share ≠ electricity Device Share
```

because electric driving is more efficient than liquid-fuel driving.

For example, if 60% of PHEV kilometres are electric, electricity may account for less than 60% of PHEV energy use because electric driving uses less energy per kilometre.

Therefore, the model should calculate PHEV electricity and liquid-fuel energy first, then convert the result into LEAP Device Shares.

---

#### 6.5.1 PHEV pre-reconciliation energy calculation

For each PHEV branch:

```text
electric_activity =
PHEV stock × mileage × electric_driving_share
```

```text
liquid_fuel_activity =
PHEV stock × mileage × liquid_fuel_driving_share
```

Then:

```text
PHEV electricity energy =
electric_activity / PHEV electric efficiency_km_per_gj
```

```text
PHEV liquid-fuel energy =
liquid_fuel_activity / PHEV liquid-fuel efficiency_km_per_gj
```

Then calculate the implied fuel split for LEAP Device Shares.

The exact conversion should account for the different fuel economies of the electricity and liquid-fuel branches.

---

#### 6.5.2 Projection-year PHEV treatment in LEAP

In projection years, PHEVs are represented through:

```text
PHEV sales share by drive type
PHEV electricity Device Share
PHEV liquid-fuel Device Share
PHEV efficiency by fuel
mileage adjustment
efficiency adjustment
```

PHEV utilisation should not be implemented as a separate LEAP variable in the first version unless the method is clearly defined and tested.

However, PHEV utilisation rates are commonly produced in transport and vehicle research. They are therefore a useful input for estimating PHEV electricity and liquid-fuel Device Shares.

Important user note:

```text
electric-driving activity share ≠ electricity Device Share
```

because electric driving is more energy-efficient than liquid-fuel driving.

For example:

```text
60% electric-driving kilometres
does not necessarily mean
60% electricity Device Share
```

The model should therefore convert any source PHEV utilisation-rate assumption into Device Shares by accounting for:

```text
electric-driving share
liquid-fuel driving share
electric efficiency
liquid-fuel efficiency
```

If a robust method is developed, PHEV utilisation could later be included as a LEAP user-defined variable that changes over time.

Possible future LEAP logic:

```text
PHEV utilisation variable
→ converted to electricity and liquid-fuel energy shares
→ converted to PHEV Device Shares
```

For now, the input package should export PHEV electricity and liquid-fuel Device Shares directly.

---

#### 6.5.3 PHEV validation checks

```text
PHEV electric-driving share + liquid-fuel driving share = 1
PHEV electricity Device Share + liquid-fuel Device Share = 1
PHEV efficiency exists for electricity and liquid fuel branches
PHEV liquid fuel type is defined
default PHEV assumptions are flagged
```

Suggested outputs:

```text
road_phev_energy_pre_reconciliation_<economy>_<scenario>.csv
road_phev_device_share_calculation_<economy>_<scenario>.csv
```

---

### 6.6 Electricity-only reconciliation for BEV and PHEV branches

Before the normal road-wide reconciliation, run a separate electricity-only reconciliation for BEV and PHEV electricity use.

Compare:

```text
initial_road_electricity =
BEV electricity energy + PHEV electricity energy
```

against:

```text
ESTO road electricity
```

Then apply the same weighted scalar reconciliation method described in Section 6.8, but only to BEV and PHEV electricity-using branches.

Use the same default weights and bounds as the main reconciliation unless electricity-specific settings are provided.

In the current implementation, default bounds are per-scalar: stock uses wider bounds, while mileage and efficiency use tighter bounds.

After this stage, recalculate:

```text
BEV electricity energy
PHEV electricity energy
PHEV liquid-fuel energy
PHEV Device Shares
```

Then continue to the normal road fuel allocation and weighted scalar reconciliation process.

Special cases:

```text
initial electricity = 0 and ESTO electricity = 0 → no action
initial electricity = 0 and ESTO electricity > 0 → exception or flagged fallback
ESTO electricity = 0 and initial electricity > 0 → stock may fall to zero unless overridden
```

Suggested outputs:

```text
road_electricity_reconciliation_scalars_<economy>_<scenario>.csv
road_electricity_reconciliation_report_<economy>_<scenario>.csv
road_phev_device_share_calculation_<economy>_<scenario>.csv
```

---

### 6.7 ESTO comparison

Compare calculated road energy against ESTO by fuel.

Formula:

```text
fuel_gap =
ESTO_energy - calculated_energy
```

Outputs:

```text
fuel
calculated energy
ESTO energy
gap
gap %
```

The model must match ESTO at fuel level, not just total road level.

---

### 6.8 Weighted scalar reconciliation

After fuel allocation issues, PHEV treatment and electricity-only reconciliation have been handled, the model reconciles remaining energy gaps using weighted scalar adjustments.

The model adjusts:

```text
stock
mileage
efficiency
```

using configurable weights.

Default weights:

```text
stock_weight = 0.50
mileage_weight = 0.25
efficiency_weight = 0.25
```

Weights must sum to 1.

---

#### 6.8.1 Required energy ratio

For each branch or fuel group being reconciled:

```text
required_energy_ratio =
ESTO_energy / calculated_energy
```

Then calculate:

```text
stock_scalar =
required_energy_ratio ^ stock_weight
```

```text
mileage_scalar =
required_energy_ratio ^ mileage_weight
```

```text
efficiency_scalar =
required_energy_ratio ^ (-efficiency_weight)
```

Because the weights sum to 1:

```text
stock_scalar × mileage_scalar / efficiency_scalar
=
required_energy_ratio
```

before bounds are applied.

This means the weighted scalar method closes the energy gap exactly if no scalar hits a bound.

---

#### 6.8.2 Adjusted energy

Adjusted energy is:

```text
adjusted_energy =
stock × stock_scalar
× mileage × mileage_scalar
÷ (efficiency × efficiency_scalar)
```

The method is transparent because it explicitly says how much of the adjustment should fall on stock, mileage, and efficiency.

Default interpretation:

```text
50% of the adjustment is assigned to stock
25% to mileage
25% to efficiency
```

These are not physical shares of energy. They are reconciliation weights that reflect the modeller’s confidence in each input.

---

#### 6.8.3 Configurable weights

Weights should be configurable by:

```text
economy
transport type
vehicle type
drive type
fuel
scenario
```

Suggested config file:

```text
config/dummy_inputs/road_reconciliation_weights.csv
```

Suggested fields:

```text
economy
scenario
transport_type
vehicle_type
drive_type
fuel_type
stock_weight
mileage_weight
efficiency_weight
notes
```

Example:

```text
stock_weight = 0.50
mileage_weight = 0.25
efficiency_weight = 0.25
```

If stock data are considered reliable, lower `stock_weight`.

If mileage data are uncertain, raise `mileage_weight`.

If efficiency data are uncertain, raise `efficiency_weight`.

---

#### 6.8.4 Scalar bounds

Scalars should have configurable bounds.

Current implementation defaults:

```text
stock_scalar_bounds = [0.0, +infinity)
mileage_scalar_bounds = [0.85, 1.15]
efficiency_scalar_bounds = [0.90, 1.10]
```

This per-scalar design deliberately gives stock wider flexibility while keeping mileage and efficiency closer to input assumptions.

Legacy shared bounds (single min/max tuple for all scalars) remain available for backward compatibility.

If a scalar hits a bound, the model should:

```text
1. apply the bounded scalar,
2. calculate the remaining energy gap,
3. redistribute the remaining gap across scalars that still have available room within the chosen bounds,
4. report any large stock adjustment for review.
```

Suggested warning thresholds:

```text
stock scalar below 0.50 → warning
stock scalar above 1.50 → warning
stock scalar below 0.25 or above 2.00 → strong warning / review flag
```

Large stock adjustments should still be reviewed because they may indicate bad input stock, mileage, efficiency, fuel allocation, or ESTO data.

Suggested config file:

```text
config/dummy_inputs/road_reconciliation_bounds.csv
```

---

#### 6.8.5 Weighted scalar example

If:

```text
required_energy_ratio = 1.20
stock_weight = 0.50
mileage_weight = 0.25
efficiency_weight = 0.25
```

Then:

```text
stock_scalar = 1.20 ^ 0.50 = 1.095
mileage_scalar = 1.20 ^ 0.25 = 1.047
efficiency_scalar = 1.20 ^ -0.25 = 0.955
```

And:

```text
1.095 × 1.047 / 0.955 ≈ 1.20
```

So energy increases by 20%.

---

#### 6.8.6 Reconciliation outputs

Preserve before/after values:

```text
initial stock → reconciled stock
initial mileage → reconciled mileage
initial efficiency → reconciled efficiency
initial Device Share → reconciled Device Share
initial energy → reconciled energy
```

Suggested outputs:

```text
road_reconciliation_scalars_<economy>_<scenario>.csv
road_reconciliation_report_<economy>_<scenario>.csv
road_reconciliation_exceptions_<economy>_<scenario>.csv
```

Validation checks:

```text
fuel-level match achieved
weights sum to 1
scalars remain within bounds or exception is reported
Device Shares sum to 100%
fuel allocation rules respected
adjusted values remain plausible
negative stock is not created
unresolved gaps are reported clearly
```

---

## 7. Projection-year logic in LEAP

Projection years are handled in LEAP using:

```text
sales share by drive type
mileage adjustment variables
efficiency adjustment variables
Device Share assumptions
scrappage assumptions
```

Projection logic:

```text
reconciled base-year stock
→ lifecycle evolution
→ annual sales
→ vehicle type split
→ drive type split
→ fuel split via Device Share
→ adjusted mileage and efficiency
→ projected energy
```

The LEAP structure should remain transparent and editable by researchers.

---

## 8. LEAP export package

The road LEAP package should contain three groups.

### 8.1 Calibrated base year

```text
reconciled stock
reconciled mileage
reconciled efficiency
base-year Device Shares
base-year energy by fuel
```

---

### 8.2 Sales and lifecycle inputs

```text
annual sales
sales share by vehicle type
survival profiles
vintage profiles
```

---

### 8.3 Projection assumptions

```text
sales share by drive type
mileage adjustment variables
efficiency adjustment variables
Device Share assumptions
scrappage assumptions
PHEV fuel split assumptions
```

## 8.4 Table naming convention used in the current pipeline

To keep base-year preparation, projection-year outputs, and LEAP handoff artifacts consistent, use the schema table names defined in `codebase/schemas/tables.py`.

```text
Base-year preparation:
  T4_base_year_branches

Projection-year preparation:
  T5_stock_targets
  T6_sales_turnover
  T6v_vintage_profiles
  T7_sales_shares

LEAP handoff and reconciliation:
  T8_fuel_allocation
  T9_reconciliation_scalars
  T10_device_shares
  T11_leap_ready
  T12_reconciliation_diagnostics

Optional mirror / QA:
  T13_mirror_outputs
```

---

## 9. Outputs

Suggested outputs:

```text
results/road/
  road_projected_sales_<economy>_<scenario>.csv
  road_survival_profiles_<economy>_<scenario>.csv
  road_vintage_profiles_<economy>_<scenario>.csv
  road_base_year_energy_initial_<economy>_<scenario>.csv
  road_fuel_allocation_<economy>_<scenario>.csv
  road_fuel_overflow_report_<economy>_<scenario>.csv
  road_fuel_allocation_exceptions_<economy>_<scenario>.csv
  road_device_shares_<economy>_<scenario>.csv
  road_phev_energy_pre_reconciliation_<economy>_<scenario>.csv
  road_electricity_reconciliation_scalars_<economy>_<scenario>.csv
  road_electricity_reconciliation_report_<economy>_<scenario>.csv
  road_phev_device_share_calculation_<economy>_<scenario>.csv
  road_reconciliation_scalars_<economy>_<scenario>.csv
  road_reconciliation_report_<economy>_<scenario>.csv
  road_reconciliation_exceptions_<economy>_<scenario>.csv
  road_validation_report_<economy>_<scenario>.csv
```

Workbook export:

```text
results/
  transport_leap_import_<economy>_<scenario>.xlsx
```

---

## 10. Validation checks

General checks:

```text
no duplicate records
required mappings exist
inputs are complete
no negative stock or activity
no negative mileage
no negative efficiency
```

Passenger checks:

```text
ownership does not exceed saturation unless explicitly allowed
ownership growth slows as saturation is approached
population data exist for all projection years
GDP per capita data exist where required
passenger/freight energy split is documented
```

Freight checks:

```text
freight growth inputs exist for all projection years
freight growth weights sum to 1
freight stock does not become negative
freight sales do not become negative unless explicitly allowed
freight method and data source are documented
historical freight road energy growth is available for review where possible
```

Sales and lifecycle checks:

```text
sales shares sum to 100%
survival curves remain valid
vintage curves remain consistent
retirements are non-negative
```

Fuel allocation checks:

```text
all fuel allocation rules exist
Device Shares sum to 100%
fuel allocation rules are respected
diesel overflow is documented
gasoline overflow into freight raises an error unless explicitly allowed
LPG and natural gas allocation method is documented
hydrogen has eligible FCEV branches where hydrogen exists
```

PHEV checks:

```text
PHEV electric-driving share + liquid-fuel driving share = 1
PHEV Device Shares sum to 100%
PHEV efficiency exists for electricity and liquid fuel branches
PHEV liquid fuel type is defined
PHEV assumptions are documented
```

Electricity reconciliation checks:

```text
BEV + PHEV electricity energy matches ESTO road electricity after electricity-only reconciliation
electricity reconciliation weights sum to 1
electricity scalars follow the same rules as the main reconciliation unless overridden
PHEV Device Shares are recalculated after electricity reconciliation
```

Reconciliation checks:

```text
road energy matches ESTO by fuel
weights sum to 1
scalars stay within bounds or exception is reported
unresolved gaps are clearly reported
adjusted values remain plausible
```

---

## 11. Dummy input templates

Suggested files:

```text
config/dummy_inputs/
  road_base_year_inputs.csv
  road_projection_assumptions.csv
  road_sales_share_by_vehicle_type.csv
  road_sales_share_by_drive_type.csv
  road_device_share_assumptions.csv
  road_scrappage_policy_assumptions.csv
  road_survival_inputs.csv
  road_vintage_inputs.csv
  road_vehicle_ownership_inputs.csv
  road_passenger_growth_inputs.csv
  road_freight_growth_inputs.csv
  road_fuel_simplification_rules.csv
  road_fuel_allocation_rules.csv
  road_phev_driving_share_inputs.csv
  road_reconciliation_weights.csv
  road_reconciliation_bounds.csv
```

Optional metadata fields:

```text
projection_source
projection_method
projection_notes
researcher_override_flag
notes
```

The input loader should treat these as dummy researcher-input files that can later be replaced by website-generated inputs.
