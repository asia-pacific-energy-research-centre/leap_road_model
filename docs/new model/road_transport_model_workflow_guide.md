# Road transport model workflow guide - Part 1 of 2

> **Purpose note**  
> This document is the implementation-oriented workflow guide for the road transport model in `leap_road_model`. It defines module boundaries, required logic, and expected outputs for the current codebase. For a shorter conceptual summary of the model, use `road_transport_model_detailed_description.md`. Where the current repo has refined an earlier design idea, this guide should follow the implemented method unless the text explicitly marks a future enhancement.

This guide describes the Python-side workflow needed to prepare the road transport model before it is passed into LEAP.

The road model is the most detailed transport demand model because it uses a stock-flow structure: vehicle stock, sales, retirements, mileage, efficiency, and fuel allocation all interact to produce energy use. Existing transport documentation describes this as a sales-based model where ownership assumptions, sales shares, survival curves, efficiency, and mileage combine to produce annual energy use in LEAP.

This first half covers:

- Module 1 - Road input data and defaults

- Module 2 - Base-year road structure and calibration preparation

- Module 3 - Stock target projection

- Module 4 - Sales, survival, vintage, and turnover policy

The second half should cover:

- Module 5 - Vehicle sales share preparation

- Module 6 - Road LEAP input package, fuel allocation, and reconciliation

- Module 7 - Optional Python mirror and post-LEAP validation

## Implementation status (current repo)

The current `codebase/road_workflow.py` runtime now treats Module 1 defaults as
the primary upstream input contract for base-year road assumptions.

In practice this means the workflow expects versioned Module 1 default packages
to exist under `input_data/module1_defaults/` and loads them before Modules 2–6.
The loaded Module 1 package now supplies (at minimum):

- base-year LEAP-format road inputs (stock, mileage, fuel economy, sales-share rows);
- survival curves and vintage profiles;
- passenger saturation level for Module 3;
- vehicle-equivalent weights for Module 3;
- PHEV electric utilisation rate and scalar bounds for Module 6;
- reconciliation weight settings where available in Module 1 outputs.

If defaults are missing locally, generate/refresh them with
`scripts/generate_module1_defaults.py` in `leap_road_model`.

## Overall Python / LEAP split

### Python before LEAP

Python prepares the road transport assumptions that LEAP needs.

Python should:

- derive passenger and freight target stocks;

- calculate sales, survival, vintage, and turnover policy inputs;

- prepare base-year sales shares by vehicle type and drive, using EV sales data where available and allocating remaining sales shares using stock proportions;

- calibrate base-year fuel allocation and Device Shares;

- create the calibrated LEAP input package.

### LEAP

LEAP receives the prepared input package and remains the official Outlook projection platform.

LEAP should:

- receive calibrated base-year road inputs;

- allow researchers to enter future sales shares directly within LEAP;

- allow researchers to adjust mileage using user-defined variables;

- allow researchers to adjust efficiency using user-defined variables;

- allow researchers to enter specific scrappage amounts in selected years;

- run the official stock-turnover projection;

- calculate stocks, activity, energy, and fuel use.

The main Python output is the LEAP-ready input package. Any Python calculation of projected stocks, activity, or energy after that point should be clearly labelled as a QA mirror or fallback model.

## Inputs expected before modules 3 to 7

Modules 1 and 2 prepare the data needed for the later modules.

Input data expected before modules 3 to 7:

- economy, scenario, year, and base-year definitions;

- population by economy and year, both historical and projected;

- GDP by economy and year, both historical and projected;

- ESTO road energy by fuel;

- base-year vehicle stock by transport type, vehicle type, and drive type;

- mileage assumptions by vehicle type and drive;

- Fuel Economy assumptions by vehicle type, drive, and fuel;

- vehicle-equivalent weights for ownership/saturation calculations;

- passenger vehicle saturation assumptions, where available;

- survival curves, where available;

- vintage profiles or average fleet age assumptions, where available;

- current vehicle sales shares, where available;

- EV sales data, including IEA data and any better local sources;

- PHEV electric driving share, utility factor, or equivalent assumption, where available;

- reconciliation bounds and weights;

- LEAP branch naming / mapping information.

Researchers may provide these inputs directly through the researcher input tool. The intention is to use the tool Fabian is building to make the process easier: researchers should be guided through the data request, shown default assumptions where they do not know a value, and given a clear way to replace defaults with economy-specific information.

Where data are missing, the system should use documented defaults, clearly flag that defaults were used, and make those assumptions easy for researchers to review later.

# Module 1 - Road input data and defaults system

## Purpose

Module 1 gathers and standardises the road model inputs before any stock projection, turnover, fuel allocation, or LEAP preparation is done.

This module is mostly about data handling, default values, and transparency. It should make sure that the model can run even when researchers do not provide every value, while making it clear where defaults were used.

## Main responsibilities

Module 1 should:

- collect researcher-provided inputs;

- load default assumptions;

- combine researcher inputs with defaults;

- flag which values came from researchers and which came from defaults;

- standardise economy, scenario, year, vehicle type, drive, and fuel labels;

- check units;

- check missing values;

- produce a clean input dataset for Module 2.

## Researcher input tool

The researcher input process should eventually be handled through Fabian's input tool.

The tool should help researchers provide:

- economy-specific vehicle stock data;

- mileage assumptions;

- efficiency assumptions;

- survival curves;

- vintage profiles or average fleet age information;

- passenger saturation assumptions;

- known EV sales shares;

- local sales share data;

- PHEV electric use assumptions;

- comments on unusual transport structure or data limitations.

The tool should not require researchers to know every value. It should show defaults and allow researchers to improve them where they have better information.

![Road transport input workbench UI — LEAP road demand input interface with tabs for vehicle types, fuel types, and parameter entry.](images/1%20road%20input.png)

*Example I got ai to do using fabians code.*

## Default assumptions

Defaults may be needed for:

- vehicle-equivalent weights;

- passenger saturation levels;

- mileage;

- efficiency;

- survival curves;

- vintage profiles;

- sales shares;

- EV sales shares;

- PHEV utilisation rates;

- reconciliation bounds and weights.

Current branch/scope policy that Module 1 and Module 2 should enforce:

- keep `HEV` and `EREV` only under LPV branches;
- remove `HEV` and `EREV` from non-LPV vehicle types;
- remove truck `PHEV` branches;
- use `Fuel Economy` as the canonical efficiency variable name in Module 1
  inputs (legacy `Final On-Road Fuel Economy` accepted only as an alias when
  reading older files);
- keep mileage researcher input shared at vehicle-type scope and expand to
  fuel-level rows in exported detailed outputs.

Each default should have:

- value;

- source;

- scope;

- date/version;

- whether researcher review is recommended.

## Outputs

Module 1 should produce:

- cleaned input tables;

- default-filled input tables;

- source-flag tables;

- missing-data reports;

- unit-check reports;

- researcher-review flags.

# Module 2 - Base-year road structure and calibration preparation system

## Purpose

Module 2 prepares the base-year road model structure before target stocks, sales, turnover, and reconciliation are calculated.

This module defines the branch structure and ensures that the data from Module 1 are organised in the same way the later model expects.

## Road branch structure

The road model should follow the broad hierarchy:

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>transport type<br />
-&gt; vehicle type<br />
-&gt; drive type<br />
-&gt; fuel type</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

Typical transport types:

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>passenger road<br />
freight road</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

Typical vehicle types may include:

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>LPVs<br />
Motorcycles<br />
Buses<br />
LCVs<br />
Trucks</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

Typical drive types may include:

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>ICE<br />
HEV (LPV only)<br />
EREV (LPV only)<br />
BEV<br />
PHEV<br />
FCEV</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

Fuel types depend on the drive type and LEAP structure.

For freight trucks specifically, PHEV branches are out of scope in the current
policy and should not be generated by default branch builders.

The existing process documentation describes a similar LEAP hierarchy of transport type, vehicle type, engine type, and fuel type, with Device Share used to split an engine type across fuels.

## Main responsibilities

Module 2 should:

- define the road branch structure;

- standardise vehicle type, drive, and fuel names;

- map input data into the branch structure;

- prepare base-year stock by branch;

- prepare base-year mileage by branch;

- prepare base-year efficiency by branch;

- prepare base-year fuel information;

- identify missing branches or missing values;

- prepare the data needed for stock projection and reconciliation.

## Important distinction

Module 2 should not yet do the main fuel reconciliation.

It should prepare:

- stock;

- mileage;

- efficiency;

- drive structure;

- fuel structure;

- branch mappings;

- default assumptions;

- validation checks.

The detailed fuel allocation and reconciliation process comes later in Module 6.

## Outputs

Module 2 should produce:

- base-year road branch table;

- stock table by transport type, vehicle type, and drive;

- mileage table;

- efficiency table;

- branch mapping table;

- fuel mapping table;

- missing-branch report;

- base-year preparation diagnostics.

# Module 3 - Stock target projection module

## Purpose

Module 3 derives annual target vehicle stocks before the survival, vintage, and sales module is applied.

Target stock should not be treated as a simple external input. Passenger and freight target stocks should be calculated internally.

The reason this matters is that the road model begins from sales and stock turnover rather than passenger-km or tonne-km. Existing documentation explains that the new LEAP approach starts with sales projections, with sales determined by ownership targets and stock turnover rather than being assumed independently.

## 3.1 Passenger stock projection

Passenger vehicle stocks are projected using a logistic / Gompertz-style motorisation curve.

### Required logic

The module should:

- calculate base-year passenger motorisation from observed passenger vehicle stocks and population;

- use capacity-weighted or vehicle-equivalent ownership rather than simple vehicle counts;

- apply vehicle-equivalent weights by vehicle type;

- estimate the S-curve growth parameter k from recent historical passenger road energy growth;

- use historical energy growth as a proxy for recent passenger stock growth;

- exclude COVID-affected years, especially 2020-2022, when estimating historical growth;

- use a configurable lookback window, defaulting to 10 years before the base year;

- clamp k to configured bounds, defaulting to \[0.0, 0.15\];

- project the passenger motorisation envelope toward a saturation level;

- use supplied saturation assumptions where available;

- otherwise default saturation using a documented fallback rule;

- convert projected motorisation into total passenger vehicle stock using population;

- allocate total projected passenger stock across vehicle types using fixed or time-varying vehicle-count shares.

### Vehicle-equivalent ownership

Passenger ownership should be calculated in vehicle-equivalent terms.

For example, default weights may be:

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>LPV = 1.0<br />
two-wheeler = 0.8<br />
bus = 20.0</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

These should be config-driven, not hard-coded.

This matters because one Bus should not be treated the same as one car when calculating the total ownership envelope. If the economy shifts toward Buses, the total number of physical vehicles may fall while the vehicle-equivalent transport capacity remains similar.

### Estimating k

Use recent historical road energy growth to estimate how quickly passenger motorisation is moving toward saturation.

Calculate:

| g_E = mean(log(E\[t\] / E\[t-1\])) |
|------------------------------------|

over the recent historical lookback window, excluding 2020-2022.

Then:

| k ~= g_E / (1 - M_base / M_sat) |
|---------------------------------|

Where:

- g_E = recent average annual log growth rate of passenger road energy;

- M_base = base-year motorisation level;

- M_sat = saturation motorisation level;

- k = estimated S-curve steepness.

Interpretation:

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>if g_E = 0.03<br />
and M_base / M_sat = 0.40<br />
<br />
k = 0.03 / 0.60<br />
k = 0.05</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

### Explanation of k bounds

k controls how quickly the passenger motorisation curve moves toward saturation.

Very high k values can create unrealistically fast stock growth. Negative k values would imply structural decline in the motorisation envelope, which should not be the default behaviour.

Therefore k should be clamped within configurable bounds.

Default:

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>k_min = 0.0<br />
k_max = 0.15</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

This means:

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>0.0 = no structural growth in the motorisation envelope<br />
0.15 = very fast upper-bound transition toward saturation</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

Any economy where k hits the upper or lower bound should be flagged for review.

### Supplied saturation assumptions

If researchers provide economy-specific saturation assumptions, use those directly.

Saturation assumptions may reflect:

- income level;

- land use;

- urban density;

- public transport availability;

- road infrastructure;

- role of Motorcycles;

- role of Buses;

- policy direction;

- known local constraints.

If no researcher-supplied saturation value is available, create a default using a documented fallback rule, such as a multiple of the base-year motorisation level.

For economies that are already close to or above the default saturation level, avoid forcing additional ownership growth simply because the default rule says so.

Record whether each saturation value came from:

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>researcher input<br />
default rule<br />
fallback<br />
manual override</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

### Already-saturated economies

If an economy is already saturated, avoid applying an S-curve that creates unrealistic continued growth.

In that case, ownership should remain broadly constant and stock should mainly change with population.

This is consistent with the earlier transport documentation, which explains that for saturated economies the ownership level stays broadly constant and stock changes mainly because population changes.

## 3.2 Freight stock projection

Freight road should also produce target vehicle stocks, not only activity.

Freight vehicle stocks are projected using GDP elasticity.

The current implementation uses total GDP as the default projection driver and calibrates elasticity from recent historical freight road energy and GDP growth. The method does not currently apply a separate manufacturing-versus-total GDP blend.

### Required logic

The module should:

- estimate historical freight energy growth over the configurable lookback window;

- estimate historical GDP growth over the same window;

- exclude COVID-affected years, especially 2020-2022;

- calculate freight stock elasticity;

- use freight energy growth as a proxy for freight stock growth;

- allow elasticity to be overridden by economy, scenario, vehicle type, or config;

- project freight stock from base-year stock and projected GDP;

- clamp elasticity to configured bounds, which may be tighter than earlier concept notes;

- keep freight stock projection separate from passenger ownership saturation logic.

### Elasticity calculation

Calculate:

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>average annual freight energy growth =<br />
(E_end / E_start) ^ (1 / n) - 1</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>average annual GDP growth =<br />
(GDP_end / GDP_start) ^ (1 / n) - 1</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

Then:

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>elasticity =<br />
average annual freight energy growth / average annual GDP growth</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

### Freight stock projection

Project freight stock using:

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>target_stock(y) =<br />
base_stock × (GDP(y) / GDP_base) ^ elasticity</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

### Why this works

The assumption is that pre-transition freight energy intensity is broadly stable enough that freight energy growth can be used as a proxy for freight stock growth.

The elasticity therefore captures how freight fleet size scales with economic activity.

### Fallbacks

If GDP growth is zero, negative, or unstable, use a fallback elasticity or configured stock growth assumption.

If historical freight road energy is unreliable, allow researcher override or economy-group defaults.

The transport documentation already notes that freight road is similar to passenger road but without ownership curves. In the current implementation this is expressed as a bounded GDP-elasticity method using total GDP by default.

## 3.3 Stock projection diagnostics

At the end of Module 3, produce diagnostics and graphs.

### Required outputs

- passenger motorisation curve by economy and scenario;

- passenger target stock by vehicle type;

- freight target stock by vehicle type;

- estimated passenger k;

- estimated freight GDP elasticity;

- historical energy growth rates used for calibration;

- GDP growth rates used for freight elasticity;

- flags showing which years were excluded from trend estimation;

- flags where default saturation, default elasticity, or fallback assumptions were used.

### Required plots

- historical passenger energy trend vs projected passenger stock trend;

- passenger motorisation level vs saturation level;

- freight energy trend vs GDP trend;

- freight projected stock vs GDP index;

- passenger vs freight target stock growth comparison.

### Validation checks

- passenger stock should not become negative;

- freight stock should not become negative;

- passenger ownership should not exceed saturation unless explicitly allowed;

- k should remain within configured bounds;

- freight elasticity should remain within configured bounds;

- all fallback assumptions should be flagged.

# Module 4 - Sales, survival, vintage, and turnover policy module

## Purpose

Module 4 converts projected stock targets into annual sales, retirements, surviving stock, and vintage profiles.

This module already mostly exists in code, so the guide should describe both the core stock-flow logic and the additional lifecycle and policy tools the code supports.

Existing documentation describes survival curves as the probability that a vehicle remains on the road at each age, and vintage curves as the distribution of vehicle ages in the fleet. It also explains that lifecycle profiles are used to keep stock-flow accounting coherent rather than as a direct fit to noisy real-world data.

## 4.1 Core stock-flow logic

### Required logic

The module should:

- start from target stocks produced by Module 3;

- start from base-year stock by vehicle type, drive, and vintage where available;

- age the fleet forward each year;

- apply natural survival curves;

- calculate surviving stock from previous vintages;

- calculate natural retirements;

- calculate required new sales;

- prevent negative sales unless explicitly allowed by config;

- handle cases where surviving stock exceeds target stock;

- split new sales by vehicle type and drive using sales-share assumptions;

- output annual stock, sales, retirements, and stock by vintage.

### Core calculation

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>required_sales =<br />
target_stock - surviving_stock</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

If surviving stock is lower than the target stock, new sales fill the gap.

If surviving stock is higher than the target stock, apply the configured surplus rule:

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>allow temporary stock overshoot<br />
increase scrappage<br />
cap surviving stock</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

The selected treatment should be explicit and recorded.

### Stock accounting check

After retirements, scrappage, and sales:

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>stock(y) =<br />
surviving_stock(y) + new_sales(y)</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

after any additional retirement or scrappage adjustment.

## 4.2 Additional retirement rate as a policy instrument

The module should support policy-driven forced retirement on top of natural survival.

### Required logic

The module should:

- read optional additional_retirement_rate assumptions;

- apply additional retirement after natural survival;

- allow additional retirement rates to vary by:

<!-- -->

- year;

- vehicle type;

- drive;

- age bucket;

- scenario;

<!-- -->

- support age_multipliers so policies can target older vehicles more strongly;

- ensure additional retirements cannot make stock negative;

- record natural retirements and additional retirements separately.

### Important LEAP split

Long-term structural changes to vehicle lifetimes can be represented through adjusted survival curves.

Temporary or year-specific scrappage policies should not be baked into a survival curve that applies across all years. They should be prepared as explicit scrappage assumptions and implemented in LEAP using the scrappage setting for the relevant years.

Python can help calculate required scrappage amounts, but LEAP should remain the place where specific year-by-year scrappage interventions are entered.

The process documentation identifies scrappage as additional early retirements beyond the normal survival profile, with related settings such as fraction of scrapped vehicles replaced and maximum scrappage fraction.

## 4.3 Survival multipliers and researcher-supplied survival curves

The module should support scaling survival curves rather than treating them as fixed.

### Required logic

The module should:

- accept researcher-supplied survival curves where available;

- accept default survival curves where researcher-supplied data are unavailable;

- read optional survival_multiplier by year;

- read optional survival_multipliers_by_age by vehicle age;

- apply multipliers to the base survival curve;

- ensure final survival rates remain between 0 and 1;

- store both original and adjusted survival curves;

- use adjusted survival curves for stock-flow calculations;

- convert the chosen survival assumptions into the actual curve format needed by LEAP.

### Important

Researcher-supplied survival curves should be treated as early-stage input data.

The system should still process these curves into internally consistent LEAP-compatible survival and vintage profiles. Do not assume that researcher-provided curves are already formatted exactly as LEAP requires.

Temporary scrappage effects should generally not be embedded into the survival curve unless they are intended to represent a permanent structural change in vehicle lifetime.

## 4.4 Initial fleet age shifting and researcher-supplied vintage profiles

The module should support shifting the base-year vintage profile to model an older or younger starting fleet.

### Required logic

The module should:

- accept researcher-supplied vintage profiles where available;

- accept researcher-supplied average fleet age assumptions where available;

- read optional analysis_initial_fleet_age_shift_years;

- use derive_initial_fleet_age_shift_vintage_profiles or equivalent logic;

- shift the base-year age distribution forward or backward;

- preserve total base-year stock after shifting;

- re-normalise vintage shares after shifting;

- convert the resulting vintage profile into the actual format needed by LEAP;

- flag economies where large age shifts are applied.

### Purpose

This allows the model to represent economies where the initial fleet is believed to be older or younger than the raw vintage data suggests.

It also allows researcher knowledge to improve economy-specific assumptions without breaking the accounting structure needed by LEAP.

## 4.5 Drive-level turnover policy derivation

The module should support deriving vehicle-bucket retirement policies from broader drive-level policies.

### Required logic

The module should:

- use derive_vehicle_turnover_policies_from_drive_policy or equivalent logic;

- take drive-level policy assumptions as inputs;

- weight the policy by current drive stock shares;

- convert drive-level policy into effective additional retirement rates by vehicle bucket;

- apply the resulting additional retirement rates in the stock-flow calculation where the policy is part of the Python-side calculation;

- store the derived policy separately from manually supplied vehicle-level policies.

### Important LEAP split

If the drive-level policy is a temporary or year-specific scrappage intervention, it should be passed to LEAP as explicit scrappage assumptions rather than permanently altering the survival curve.

If the drive-level policy represents a structural lifetime change, it may be represented through survival multipliers or adjusted survival curves.

Python should make this distinction explicit in diagnostics.

## 4.6 Policy merge, subtract, and counterfactual tooling

The module should support composing and decomposing turnover policies for scenario comparison.

### Required logic

The module should:

- support merging multiple turnover policies into a combined policy;

- support subtracting one turnover policy from another;

- support counterfactual turnover policies for scenario comparison;

- use existing functions such as:

<!-- -->

- \_merge_turnover_policies;

- \_subtract_turnover_policies;

- drive_policy_counterfactual_turnover_policies;

<!-- -->

- preserve transparent diagnostics showing:

<!-- -->

- base policy;

- added policy;

- removed policy;

- final combined policy;

<!-- -->

- avoid double-counting when multiple policies affect the same vehicle bucket.

### Important LEAP split

Policy composition tools can be used to prepare assumptions.

Temporary scrappage policies should ultimately be represented in LEAP through explicit year-specific scrappage settings.

The merged policy should clearly identify which parts are:

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>structural survival/lifetime changes<br />
temporary scrappage interventions<br />
scenario comparison or counterfactual adjustments</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

## 4.7 Turnover diagnostics

### Required outputs

- target stock;

- surviving stock;

- new sales;

- natural retirements;

- additional retirements;

- total retirements;

- stock by vintage;

- original survival curve;

- adjusted survival curve;

- researcher-supplied survival curve, where used;

- researcher-supplied vintage profile, where used;

- applied additional retirement rate;

- explicit LEAP scrappage assumptions by year, where used;

- derived drive-level policy effects;

- policy merge / subtract diagnostics.

### Required validation

- survival rates must remain between 0 and 1;

- additional retirement rates must remain within configured bounds;

- stock cannot become negative;

- sales shares must sum to 1;

- stock accounting must hold after additional retirement or scrappage;

- temporary scrappage must not be silently embedded into permanent survival curves;

- researcher-supplied survival and vintage curves must be converted into internally consistent LEAP-compatible profiles.

# End of Part 1

Part 2 should continue from Module 5 and cover:

- base-year vehicle sales share preparation;

- EV sales share defaults;

- researcher-entered future sales shares in LEAP;

- LEAP handoff package;

- base-year fuel allocation and reconciliation;

- BEV/PHEV electricity treatment;

- Device Share calculation;

- optional Python mirror and post-LEAP validation.

Road transport model workflow guide — Part 2 of 2

This second half continues from the first part of the guide.

Part 1 covered:

- Module 1 — Road input data and defaults

- Module 2 — Base-year road structure and calibration preparation

- Module 3 — Stock target projection

- Module 4 — Sales, survival, vintage, and turnover policy

Part 2 covers:

- Module 5 — Vehicle sales share preparation

- Module 6 — Road LEAP input package, base-year reconciliation, and Device Shares

- Module 7 — Optional Python mirror and post-LEAP validation

The main purpose of Part 2 is to describe how the Python system prepares the final road transport assumptions for LEAP.

The main Python output is the LEAP-ready input package. LEAP then runs the official road stock-turnover projection, including researcher-entered future sales shares, mileage adjustment variables, efficiency adjustment variables, and specific scrappage amounts for selected years.

# Module 5 — Vehicle sales share preparation module

## Purpose

Module 5 prepares base-year vehicle sales shares by vehicle type and drive before assumptions are passed into LEAP.

This module should create sensible default base-year sales-share assumptions. Researchers will enter and edit future sales-share trajectories directly in LEAP, using the base-year sales shares as the starting point.

Tools to help researchers design future sales-share trajectories may be useful later, but they are not required for the first implementation.

## 5.1 Base-year EV sales share defaults

### Purpose

The base-year sales-share system should use observed EV sales data where available, then fill the remaining sales shares using the existing stock structure.

This makes the base-year transition point more realistic than simply assuming sales shares equal stock shares.

### Required logic

The module should:

- start with observed current vehicle sales shares where available;

- for economies and vehicle types with available EV sales data, use that data to set base-year EV sales shares;

- use IEA EV sales data and other known external sources to prepare default EV sales shares;

- treat these as starting assumptions, not final researcher-approved values;

- allow researcher-provided values to override default values;

- allow overrides by:

<!-- -->

- economy;

- scenario;

- year;

- vehicle type;

- drive.

### Key principle

EV sales shares should be considered first.

After the EV sales share is set, the remaining sales share is allocated across the non-EV drive types.

This avoids underestimating EV sales in economies where EV sales are already growing but the stock share is still small.

## 5.2 Remaining drive share allocation

After EV sales shares are assigned, allocate the remaining sales share across the other drive types within the same vehicle type.

### Required logic

For each economy, scenario, year, and vehicle type:

remaining_sales_share =

1 - EV_sales_share

Then allocate remaining_sales_share across all remaining drive types according to their current stock proportions.

Example:

EV sales share = 10%

remaining sales share = 90%

non-EV stock proportions:

gasoline ICE = 80%

diesel ICE = 20%

base-year sales shares:

EV = 10%

gasoline ICE = 90% × 80% = 72%

diesel ICE = 90% × 20% = 18%

### Required checks

The module should:

- ensure sales shares sum to 1 within each vehicle type;

- ensure EV sales shares are not negative or greater than 1;

- ensure remaining drive shares are not negative;

- flag any case where stock proportions are missing or zero;

- use fallback assumptions only when needed.

### Suggested fallback hierarchy

If stock proportions or sales data are missing, use the following hierarchy:

1\. researcher-provided sales share;

2\. observed sales share data;

3\. current stock proportions;

4\. regional or economy-group default;

5\. global default;

6\. explicit warning if no suitable fallback exists.

## 5.3 Future sales shares in LEAP

Researchers will enter future sales shares directly in LEAP.

Python should not hard-code long-term EV adoption trajectories as fixed policy assumptions.

The Python system does, however, produce a seeded future sales-share trajectory (T7f_future_shares) derived by scaling 9th edition trajectories to be consistent with the new base year. This seeded trajectory is an implementation bridge — a reasonable starting point for researchers — not an official policy scenario. Researchers may replace or extend it when entering assumptions in LEAP.

The Python system should provide:

- base-year sales shares (T7_sales_shares);

- scaled future trajectories anchored to the new base year (T7f_future_shares, described in section 5.5);

- source flags;

- scaling method flags;

- validation checks;

- any near-term observed sales data that may help researchers.

LEAP should provide the flexibility for researchers to define future sales-share paths by economy, vehicle type, and drive.

## 5.4 Sales-share outputs

Module 5 produces two output tables.

**T7_sales_shares** — base-year (2022) sales shares:

- economy, scenario, year, vehicle_type, drive_type;

- sales_share — share within the vehicle type;

- ev_sales_share_used — non-ICE share value for non-ICE drives, 0.0 for ICE;

- source_flag — how the share was derived (see below).

**T7f_future_shares** — full projection-period (2022–2060) sales share trajectories:

- economy, scenario, year, vehicle_type, drive_type;

- sales_share;

- scaling_method — method applied to the full vehicle type × scenario ("shape_preserve_ice_residual", "linear_interpolate", or "module5_base" for the base year row);

- drive_method — method applied to each individual non-ICE drive ("shape_preserve", "hold_flat", "hold_at_base").

### Source flags used in T7_sales_shares

**"iea_ev"** — EV shares derived from observed ev_sales_data (IEA or equivalent). Remaining non-EV drives allocated by stock proportion.

**"stock_proportion"** — no observed EV sales data available; all drive shares derived from base-year stock proportions.

**"researcher"** — researcher-provided override applied via researcher_sales_shares input.

Where total stock for a vehicle type is zero, shares are assigned equally across all present drive types.

## 5.5 Future sales share trajectory scaling

Future road sales shares in T7f_future_shares are seeded from the 9th edition system. The implementation scales those trajectories to be consistent with the new base year.

### Purpose

The purpose is to preserve the overall shape of the 9th edition non-ICE transition while anchoring the series to the recalibrated base-year sales shares used by this model.

### Year anchors

- Base year: 2022 (new model base year; T7_sales_shares values used as the starting point).
- Anchor year: 2023 (first projected year in the 9th edition data).
- End year: 2060 (terminal year of the 9th edition trajectory).

### Required logic

For each economy, scenario, vehicle type, and non-ICE drive:

- pin the starting value to the recalibrated base-year sales share (2022);

- pin the end value to the 9th edition terminal-year share (2060);

- preserve the shape of the 9th edition trajectory between those two points;

- calculate ICE as the residual after BEV, PHEV, and FCEV are set;

- if the residual ICE share becomes negative in any year, fall back to linear interpolation across all drives from the new base year to the 9th edition terminal and flag the case.

### Conceptual formula

For a non-ICE drive:

weight(t) =

(share_9th(t) - share_9th(anchor)) / (share_9th(end) - share_9th(anchor))

scaled_share(t) =

new_base_share + weight(t) × (share_9th(end) - new_base_share)

Then:

ICE_share(t) =

1 - sum(non_ICE_shares(t))

### Special cases for individual drives

**hold_flat** — applied when the 9th edition has no trajectory for a drive type (anchor = 0 and terminal = 0) but the new base year has a non-zero share. The drive share is held constant at the new base-year value.

**hold_at_base** — applied when the 9th edition trajectory is flat (anchor ≈ terminal), meaning there is no shape to follow. The drive share is held constant at the new base-year value.

**shape_preserve** — the standard case; the weight formula above is applied.

ICE is always the residual and does not have an individual drive method flag.

### Scaling method flags in T7f_future_shares

- **"shape_preserve_ice_residual"**: the shape-preserving method was applied successfully for all non-ICE drives; ICE is the residual.

- **"linear_interpolate"**: the shape-preserving method caused ICE to go negative in at least one year; all drives were replaced with straight-line interpolation from the new base year to the 9th edition terminal, then renormalised.

### 9th edition vehicle and drive type mapping

The 9th edition source codes are collapsed to model buckets as follows:

Drive type collapsing to ICE: ice_g, ice_d, cng, lpg, lng, hev, hev_g, hev_d.

Drive type collapsing to BEV: bev.

Drive type collapsing to PHEV: phev_g, phev_d, erev_g, erev_d.

Drive type collapsing to FCEV: fcev.

Vehicle type collapsing to LPVs: car, suv, lt.

Vehicle type collapsing to Motorcycles: 2w.

Vehicle type collapsing to Buses: bus.

Vehicle type collapsing to Trucks: ht, mt.

Vehicle type collapsing to LCVs: lcv.

Where multiple 9th edition source vehicle types map to the same model bucket (e.g. ht and mt both map to Trucks), shares are aggregated using stock-weighted averaging so that the result sums to 1 within the model bucket.

### Important note

This scaling is an implementation bridge between the 9th edition trajectories and the new model base year. Researchers still edit the official future sales shares in LEAP.

# Module 6 — Road LEAP input package, base-year reconciliation, and Device Shares

## Purpose

Module 6 creates the final Python-side road transport input package that will be passed into LEAP.

This is the main output of the Python road model.

After this module, LEAP is responsible for applying the official stock-turnover structure and calculating projected stocks, activity, and energy.

## 6.1 Main LEAP handoff package

### Required logic

The module should combine outputs from:

- base-year road structure preparation;

- passenger stock target projection;

- freight stock target projection;

- sales / survival / vintage calculations;

- turnover policy preparation;

- base-year vehicle sales share preparation;

- fuel allocation and Device Share calibration;

- base-year fuel reconciliation.

The package should keep passenger and freight road separate, and should preserve vehicle type, drive type, and fuel dimensions.

### Main outputs to LEAP

The LEAP-ready package should include:

- calibrated base-year stock;

- calibrated base-year mileage;

- calibrated base-year efficiency;

- calibrated base-year Device Shares;

- calibrated base-year energy by fuel;

- projected annual sales;

- sales share by vehicle type;

- base-year sales share by drive type;

- survival profiles;

- vintage profiles;

- mileage assumptions;

- efficiency assumptions;

- Device Share assumptions;

- explicit year-specific scrappage assumptions where used;

- turnover / scrappage / policy assumptions where used.

The current implementation already produces calibrated base-year stock, mileage, activity, efficiency (km/GJ), Device Shares, and sales-share outputs for LEAP handoff. Structured mileage and efficiency user-defined adjustment variable tables remain a later enhancement.

### Table naming convention used in implementation

Use schema table names consistently across documentation and outputs:

- base-year preparation: `T4_base_year_branches`;
- projection-year preparation: `T5_stock_targets`, `T6_sales_turnover`, `T6v_vintage_profiles`, `T7_sales_shares`;
- LEAP handoff and reconciliation: `T8_fuel_allocation`, `T9_reconciliation_scalars`, `T10_device_shares`, `T11_leap_ready`, `T12_reconciliation_diagnostics`;
- optional mirror/QA output: `T13_mirror_outputs`.

### Important LEAP responsibilities

LEAP should allow researchers to:

- enter future sales shares directly;

- adjust mileage using user-defined variables;

- adjust efficiency using user-defined variables;

- enter specific scrappage amounts in selected years.

Temporary scrappage policies should be entered as explicit LEAP scrappage assumptions, not baked into permanent survival curves.

## 6.2 Base-year energy calculation and reconciliation workflow

## Purpose

This section explains the base-year reconciliation workflow.

The goal is to create a calibrated base-year road model that matches ESTO road fuel totals before the assumptions are passed into LEAP.

The basic branch-level energy calculation is:

vehicle_km =

stock × mileage

energy_pj =

stock × mileage / efficiency_km_per_gj / 1,000,000

Efficiency is defined as distance travelled per unit of energy, for example km/GJ.

The reconciliation process should be done before final Device Shares are calculated. Device Shares depend on the final reconciled allocation of fuel energy across vehicle-drive branches.

Module 6 reconciles each branch iteratively: it applies the bounded stock/mileage/efficiency scalars, checks the residual energy gap, and repeats until the branch is close enough or the iteration cap is reached.

### Core workflow

stock, mileage, efficiency

→ initial branch energy

→ BEV/PHEV electricity reconciliation using the same process as Steps 5–6

→ PHEV liquid fuel subtraction from ESTO gasoline/diesel

→ remaining ESTO fuel totals for normal fuel reconciliation

→ fuel allocation across eligible branches

→ iterative bounded stock/mileage/efficiency adjustment for remaining fuels

→ final branch fuel energy

→ implied vehicles

→ Device Shares

## Step 1 — Calculate initial branch energy

Calculate initial branch energy by economy, vehicle type, drive, and fuel where possible.

initial_energy_pj =

stock × mileage / efficiency_km_per_gj / 1,000,000

This gives the first estimate of road energy before reconciliation.

## Step 2 — Reconcile BEV and PHEV electricity before normal fuel reconciliation

Electricity and PHEVs should be handled before reconciling normal liquid and gaseous fuels.

This stage reconciles BEV and PHEV electricity use to ESTO road electricity using the same iterative bounded stock/mileage/efficiency adjustment method described in Steps 5–6.

Do not repeat the full reconciliation method here. Use Steps 5–6 as the guide.

### Required logic

The module should:

- calculate initial BEV electricity use from BEV stock, mileage, and efficiency;

- calculate initial PHEV electricity use from PHEV stock, mileage, electric efficiency, and PHEV electric utilisation rate;

- compare calculated BEV + PHEV electricity against ESTO road electricity;

- derive the electricity correction factor;

- apply the same iterative stock/mileage/efficiency scalar process described in Steps 5–6;

- keep the PHEV electric utilisation rate fixed unless config explicitly allows it to move;

- recalculate PHEV liquid fuel use from the adjusted PHEV stock, adjusted mileage, fixed electric utilisation rate, and liquid-fuel efficiency.

### PHEV liquid fuel treatment

After this stage:

- subtract adjusted PHEV gasoline use from the ESTO gasoline total before normal gasoline reconciliation;

- subtract adjusted PHEV diesel use from the ESTO diesel total before normal diesel reconciliation;

- run the normal ICE fuel reconciliation on the remaining ESTO gasoline and diesel totals;

- add PHEV liquid fuel use back into final gasoline and diesel totals after reconciliation.

This preserves the ESTO fuel balance:

final_gasoline =

reconciled_non_phev_gasoline + adjusted_phev_gasoline

final_diesel =

reconciled_non_phev_diesel + adjusted_phev_diesel

PHEV liquid fuel use is likely to be small, so it should be calculated first and removed from the broader gasoline/diesel reconciliation. This prevents the normal ICE reconciliation from hiding or distorting the PHEV liquid/electric split.

### Validation

- BEV + PHEV electricity should match ESTO road electricity within tolerance.

- PHEV electric utilisation rate should remain between 0 and 1.

- PHEV liquid fuel use cannot be negative.

- Adjusted BEV/PHEV stock, mileage, and efficiency must remain within configured bounds.

- If electricity cannot be matched within bounds, flag the issue rather than forcing an impossible result.

## Step 3 — Calculate remaining ESTO fuel totals for normal reconciliation

After PHEV liquid fuel is removed:

remaining_esto_fuel =

ESTO_fuel_total - PHEV_liquid_fuel_use

Use remaining_esto_fuel for the normal ICE fuel reconciliation.

For fuels with no PHEV use, the remaining ESTO fuel total is just the full ESTO fuel total.

## Step 4 — Allocate remaining ESTO fuel to eligible branches

For each fuel, allocate the remaining ESTO fuel total across eligible vehicle-drive branches.

This creates:

allocated_branch_fuel_energy_pj

Meaning:

the portion of the remaining ESTO fuel total assigned to a specific vehicle-drive-fuel branch before final Device Shares are calculated

For example:

allocated_branch_fuel_energy_pj =

remaining_esto_fuel_pj × branch_allocation_share

Where branch_allocation_share is based on the configured allocation rule, such as:

- stock shares;

- initial energy shares;

- preferred freight/passenger allocation;

- researcher-provided allocation;

- another documented rule.

The current implementation uses stock-share allocation across eligible branches by default.

At this point, the allocation is still provisional. It tells the model where each fuel should go, but stock, mileage, and efficiency may still need to be adjusted so that the branch-level calculation is internally consistent.

The fuel allocation rules are described in section 6.3.

## Step 5 — Derive one energy correction factor

For each fuel or configured branch group:

energy_correction_factor =

allocated_branch_fuel_energy_pj / initial_branch_energy_pj

This is the factor needed to make the modelled branch energy match the allocated ESTO fuel energy.

If the branch has zero initial energy but non-zero allocated ESTO energy, the module should not divide by zero. It should use a configured fallback, such as:

- assigning a minimum stock/mileage/efficiency basis;

- reallocating the fuel to another valid branch;

- flagging the case as an impossible allocation.

## Step 6 — Adjust stock, mileage, and efficiency simultaneously

Apply stock, mileage, and efficiency adjustments at the same time.

Default weights:

stock = 0.50

mileage = 0.25

efficiency = 0.25

Because efficiency is measured as km/GJ, higher efficiency reduces energy use. Therefore the efficiency scalar moves in the inverse direction.

stock_scalar =

energy_correction_factor ^ 0.50

mileage_scalar =

energy_correction_factor ^ 0.25

efficiency_scalar =

energy_correction_factor ^ -0.25

Then:

adjusted_stock =

stock × stock_scalar

adjusted_mileage =

mileage × mileage_scalar

adjusted_efficiency =

efficiency × efficiency_scalar

The combined effect should reproduce the energy correction factor:

adjusted_energy_pj =

adjusted_stock × adjusted_mileage / adjusted_efficiency / 1,000,000

### Required records

The module should store:

- original stock, mileage, and efficiency;

- stock scalar;

- mileage scalar;

- efficiency scalar;

- default or configured weights;

- final adjusted stock, mileage, and efficiency;

- whether each scalar stayed within bounds.

In the current implementation, scalar bounds are per-scalar by default, with wider bounds for stock and tighter bounds for mileage and efficiency. This keeps mileage and efficiency adjustments closer to input assumptions while allowing stock to absorb larger residual reconciliation where needed.

Default behavior:

- stock scalar bounds: wide (for example $[0,\infty)$);
- mileage scalar bounds: tighter (for example $[0.85, 1.15]$);
- efficiency scalar bounds: tighter (for example $[0.90, 1.10]$).

Legacy shared bounds (single tuple min/max for all three scalars) remain supported for backward compatibility.

## Step 7 — Recalculate final branch fuel energy

After the scalars are applied, recalculate branch energy:

final_branch_fuel_energy_pj =

adjusted_stock × adjusted_mileage / adjusted_efficiency / 1,000,000

This final branch fuel energy should match the allocated ESTO fuel energy within tolerance.

## Step 8 — Calculate implied vehicles and Device Shares

Once final branch fuel energy has been calculated, estimate implied vehicles using each fuel:

energy_per_vehicle_pj =

adjusted_mileage / adjusted_efficiency / 1,000,000

implied_vehicles_using_fuel =

final_branch_fuel_energy_pj / energy_per_vehicle_pj

Then calculate Device Share:

Device Share =

implied_vehicles_using_fuel / adjusted_total_vehicles_in_branch

Device Shares should be calculated after reconciliation, not before, because they depend on the final reconciled stock, mileage, efficiency, and fuel allocation.

## Step 9 — Validate base-year reconciliation

Validate:

- final fuel energy matches ESTO fuel totals after PHEV liquid fuel is added back;

- stock, mileage, and efficiency scalars remain within bounds;

- Device Shares sum to 1 within each parent branch;

- no negative values are created;

- no impossible fuel/drive combinations are created.

Failure to match should be rare. If the model cannot match ESTO within configured bounds, treat it as an exceptional case caused by poor input data, overly tight bounds, missing branches, or an allocation error.

### Required outputs

Module 6 should produce:

- initial branch energy;

- PHEV liquid fuel subtraction table;

- remaining ESTO fuel totals for reconciliation;

- provisional fuel allocation table;

- energy correction factor table;

- stock scalar table;

- mileage scalar table;

- efficiency scalar table;

- final branch fuel energy;

- implied vehicles by branch and fuel;

- final Device Shares;

- final fuel-level comparison;

- validation status.

## 6.3 Fuel allocation rules and Device Share preparation

## Purpose

This section defines how remaining ESTO fuel totals are allocated across eligible vehicle-drive branches before final Device Shares are calculated.

The allocation rules are used in the reconciliation workflow above.

## Fuel allocation rules

### Motor gasoline

Motor gasoline is:

- used in passenger/freight ICE branches where gasoline use is valid;

- used in passenger/freight PHEV liquid-fuel branches where gasoline PHEVs exist;

- combined with biogasoline allocation logic.

Biogasoline is allocated proportionally alongside motor gasoline across the same eligible branches.

The model should not assume there is a separate “gasoline ICE branch” unless the actual LEAP road structure has one. The relevant branches are passenger/freight ICE branches where gasoline use is valid.

### Gas and diesel oil

Gas and diesel oil is:

- used in passenger/freight ICE branches where diesel use is valid;

- used in passenger/freight PHEV liquid-fuel branches where diesel PHEVs exist;

- allocated mainly to freight ICE/PHEV branches first.

If freight branches cannot plausibly absorb the observed diesel total, overflow can go into passenger ICE/PHEV branches.

Biodiesel is allocated proportionally alongside diesel across the same eligible branches.

The model should not assume there is a separate “diesel ICE branch” unless the actual LEAP road structure has one. The relevant branches are passenger/freight ICE branches where diesel use is valid.

### LPG, natural gas, and biogas

LPG, natural gas, and biogas are similar from an allocation-method perspective, but they should still be treated as separate fuels.

Rules:

- LPG, natural gas, and biogas are allocated across eligible ICE branches;

- LPG remains a separate fuel;

- natural gas remains a separate fuel;

- biogas remains a separate fuel if represented separately in the model data;

- biogas follows the same branch allocation pattern as natural gas;

- allocation should use stock, mileage, efficiency, and any researcher/default assumptions;

- implausible vehicle types can be excluded by config if needed, for example LPG Motorcycles.

### Electricity

Electricity is handled separately through the BEV/PHEV electricity process.

It should not be allocated across generic ICE branches.

### Hydrogen

Hydrogen is used in FCEV branches.

It is not expected to appear materially in most base-year road data. If present, allocate only to FCEV branches unless config explicitly allows another treatment.

### E-fuels

E-fuels are generally not expected in the base year.

In projections, they can be split across eligible ICE branches. This projection treatment does not need to affect the base-year Python system unless e-fuels appear in observed base-year data.

### Ammonia

Ammonia is generally not expected in the base year.

In projections, it may be used alongside hydrogen in FCEV-type branches if the LEAP structure represents it that way. This projection treatment does not need to affect the base-year Python system unless ammonia appears in observed base-year data.

## Allocation method

For each fuel:

- identify eligible vehicle-drive branches;

- allocate the remaining ESTO fuel total across eligible branches;

- use preferred branch rules where relevant;

- allow documented overflow from preferred branches to secondary branches;

- prevent invalid fuel/drive combinations unless explicitly allowed by config;

- flag any fuel that appears in ESTO but has no valid branch.

The allocation creates:

allocated_branch_fuel_energy_pj

This means the amount of a given ESTO fuel assigned to a specific model branch for reconciliation.

Device Shares should not be finalised until after stock, mileage, and efficiency reconciliation is complete.

## Required outputs

Section 6.3 should produce:

- fuel allocation rule table;

- branch eligibility table;

- remaining ESTO fuel totals;

- allocated branch fuel energy;

- overflow allocation table;

- invalid fuel/branch warning table.

## 6.4 PHEV and BEV electricity treatment

## Purpose

This section gives the specific BEV/PHEV calculations used inside section 6.2 Step 2.

Electricity should not be allocated like a generic ICE fuel. It should be handled through the BEV/PHEV process.

PHEVs require special treatment because they use both electricity and liquid fuel. Their electricity allocation must remain consistent with their total activity, electric utilisation rate, and liquid fuel use.

## BEV electricity

For each BEV branch:

BEV_electricity_pj =

BEV_stock × BEV_mileage / BEV_efficiency_km_per_gj / 1,000,000

This value is then reconciled to ESTO road electricity using the same simultaneous stock/mileage/efficiency method described in section 6.2 Steps 5–6.

## PHEV electricity and liquid fuel

For each PHEV branch:

PHEV_vehicle_km =

PHEV_stock × PHEV_mileage

PHEV_electric_km =

PHEV_vehicle_km × PHEV_electric_utilisation_rate

PHEV_liquid_km =

PHEV_vehicle_km × (1 - PHEV_electric_utilisation_rate)

PHEV_electricity_pj =

PHEV_electric_km / PHEV_electric_efficiency_km_per_gj / 1,000,000

PHEV_liquid_energy_pj =

PHEV_liquid_km / PHEV_liquid_efficiency_km_per_gj / 1,000,000

The PHEV electric utilisation rate should remain fixed unless config explicitly allows it to move.

The electricity component is reconciled to ESTO road electricity using the same simultaneous stock/mileage/efficiency method described in section 6.2 Steps 5–6.

The liquid component is calculated from the resulting adjusted PHEV stock, mileage, utilisation rate, and liquid-fuel efficiency.

## PHEV liquid fuel subtraction

PHEV liquid fuel use should be calculated before normal gasoline/diesel reconciliation.

Then:

remaining_gasoline_for_reconciliation =

ESTO_gasoline - PHEV_gasoline

remaining_diesel_for_reconciliation =

ESTO_diesel - PHEV_diesel

The normal ICE reconciliation is applied to the remaining gasoline and diesel totals.

After reconciliation:

final_gasoline =

reconciled_non_phev_gasoline + PHEV_gasoline

final_diesel =

reconciled_non_phev_diesel + PHEV_diesel

This keeps total ESTO gasoline and diesel unchanged while preventing the broader ICE reconciliation from hiding PHEV liquid/electric behaviour.

## Required validation

- PHEV electric utilisation rate must remain between 0 and 1.

- PHEV liquid fuel use cannot be negative.

- BEV + PHEV electricity should match ESTO road electricity within tolerance where data and bounds allow.

- Adjusted BEV/PHEV stock, mileage, and efficiency must remain within configured bounds.

- Final gasoline and diesel totals should match ESTO after PHEV liquid fuel is added back.

- Any remaining electricity gap should be flagged, not hidden.

## Required outputs

Section 6.4 should produce:

- BEV electricity estimate;

- PHEV electricity estimate;

- PHEV liquid fuel estimate;

- implied PHEV electric utilisation rate;

- implied PHEV liquid utilisation rate;

- road electricity gap before and after reconciliation;

- PHEV liquid fuel subtraction table;

- PHEV contribution to final gasoline/diesel totals;

- warning table for implausible PHEV behaviour.

## 6.5 LEAP input validation

## Purpose

Before passing data into LEAP, the Python system should validate the final input package.

## Required checks

The validation should confirm that:

- all required LEAP input fields are present;

- units are explicit;

- sales shares sum correctly;

- Device Shares sum correctly within each relevant branch;

- base-year energy by fuel matches ESTO after reconciliation;

- no negative stock, mileage, efficiency, sales, or energy values exist;

- fuel shares sum to 1 where relevant;

- adjustment factors remain within configured bounds unless explicitly allowed;

- zero-energy fuels are handled without divide-by-zero errors;

- large adjustments are flagged for review;

- year-specific scrappage assumptions are clearly separated from structural survival curve assumptions;

- mileage adjustment variables and efficiency adjustment variables are passed to LEAP in the correct format.

## Required outputs

Module 6 should produce:

- LEAP-ready input tables;

- pre-reconciliation energy by fuel;

- observed ESTO road fuel totals;

- gap between modelled and observed fuel totals;

- adjustment factor applied;

- adjustment variable used;

- post-reconciliation energy by fuel;

- remaining unresolved gap;

- validation flags;

- warning tables.

# Module 7 — Optional Python mirror and post-LEAP validation module

## Purpose

Module 7 replicates the road transport stock-turnover and energy calculations outside LEAP for QA and continuity.

Module 7 is implemented in `codebase/modules/module7_mirror.py`. The core mirror and LEAP comparison logic is complete. It is not currently called from the `road_workflow.py` orchestrator and must be invoked separately after Module 6.

This module has two roles:

1\. QA: check that LEAP results match the intended road model logic.

2\. Continuity: preserve a working Python version of the road model in case APERC later wants to move away from LEAP or maintain a parallel non-LEAP implementation.

The official Outlook workflow still uses LEAP as the main projection platform.

Reading researcher-edited LEAP assumptions back into Python is a later enhancement and is not required in the current implementation.

## 7.1 Python mirror of LEAP road projection

## Implementation

`run_module7_mirror()` in `module7_mirror.py` takes T6_sales_turnover and T9_reconciliation_scalars from Modules 4 and 6 and produces T13 (technology-level) and T13_fuel (fuel-level) outputs.

The mirror produces projections for all years present in the sales turnover table, or a caller-specified year subset. It accepts optional mileage and efficiency adjustment variable DataFrames, and optional explicit scrappage inputs.

`compare_with_leap()` populates the LEAP comparison columns (leap_stock, leap_vehicle_km, leap_energy_pj, and their difference columns) when extracted LEAP outputs are provided. If no LEAP data is provided those columns remain as `pd.NA` placeholders.

## Mirror calculations

stock(y) =

surviving_stock(y) + new_sales(y) - explicit_scrappage(y)

adjusted_mileage(y) =

base_mileage(y) × mileage_adjustment_variable(y)

vehicle_km(y) =

stock(y) × adjusted_mileage(y)

adjusted_efficiency(y) =

base_efficiency(y) × efficiency_adjustment_variable(y)

energy(y) =

vehicle_km(y) / adjusted_efficiency(y)

Then Device Shares from T10 are used to split technology-level energy to fuel-level energy in T13_fuel.

## Design note

The mirror uses the same T9 reconciled stock, mileage, and efficiency assumptions that were passed to LEAP, so the base year is already calibrated. Adjustment variables multiply the base assumptions from that point forward.

## 7.2 Later input from LEAP transport model

## Purpose

Later, the Python mirror may read researcher-entered LEAP assumptions after they have been entered into the LEAP transport model.

This is a later enhancement. The current implementation does not extract researcher-edited assumptions from LEAP.

## Potential future inputs from LEAP

Future inputs may include:

- researcher-entered future sales shares;

- mileage adjustment variables;

- efficiency adjustment variables;

- year-specific scrappage assumptions;

- Device Share assumptions;

- extracted LEAP stocks;

- extracted LEAP activity;

- extracted LEAP energy.

## Required later logic

The later enhancement should:

- extract researcher-entered LEAP assumptions;

- convert them into the Python mirror model input format;

- re-run the Python mirror using the same assumptions LEAP used;

- compare Python mirror results against extracted LEAP outputs;

- report formula-level differences.

This should not block the first implementation. Build the Python mirror so that it can accept these inputs later, but do not require LEAP extraction from the start.

## 7.3 Post-LEAP validation

## Purpose

Post-LEAP validation checks whether the official LEAP road results match the intended modelling logic.

`compare_with_leap()` accepts tidy LEAP output (columns: scenario, year, leap_branch_path, variable, value) and populates the comparison columns in T13. The function does not overwrite LEAP results; it adds difference columns for review.

## Comparison logic

The validation should:

- compare LEAP base-year road energy by fuel against ESTO;

- compare LEAP projected stocks against Python-prepared sales and survival expectations;

- compare LEAP activity against implied stock × mileage;

- compare LEAP energy against implied activity ÷ efficiency;

- compare LEAP fuel totals against Device Share and fuel allocation expectations;

- compare LEAP outputs against the optional Python mirror calculation if available;

- flag cases where LEAP results diverge from the intended logic.

## Required checks

The validation should check that:

- base-year fuel energy matches ESTO within tolerance;

- projected stocks are consistent with sales and survival assumptions;

- projected activity is consistent with stock × mileage;

- projected energy is consistent with activity ÷ efficiency;

- mileage adjustment variables are being applied as intended;

- efficiency adjustment variables are being applied as intended;

- year-specific scrappage assumptions are being applied as intended;

- Device Shares behave as expected;

- fuel shares and energy shares are not confused;

- no negative or impossible values are created;

- large changes in stock, mileage, efficiency, activity, or energy are flagged;

- passenger and freight road remain separate.

## 7.4 Module 7 outputs

`run_module7_mirror()` returns a dict with two DataFrames.

**T13 (T13_mirror_outputs)** — technology-level outputs, one row per year × economy × scenario × transport_type × vehicle_type × drive_type:

- mirror_stock, mirror_mileage_km_per_year, mirror_vehicle_km, mirror_efficiency_km_per_gj, mirror_energy_pj;

- mileage_adjustment, efficiency_adjustment (1.0 if no adjustment variables supplied);

- leap_branch_path (technology-level path, fuel segment stripped);

- leap_stock, leap_vehicle_km, leap_energy_pj — populated by compare_with_leap(), otherwise pd.NA;

- stock_difference, energy_difference_pj — populated by compare_with_leap(), otherwise pd.NA.

**T13_fuel (T13_mirror_fuel_outputs)** — fuel-level outputs derived by applying T10 Device Shares to T13 technology energy:

- all T13 dimension columns plus fuel and fuel_leap_branch_path;

- device_share;

- mirror_fuel_energy_pj.

# General implementation requirements for Part 2

The implementation should:

- keep modules independent and testable;

- use clear function names;

- avoid classes unless the repo already uses them heavily;

- prefer explicit function parameters over hidden global state;

- keep config-driven assumptions in YAML or existing config files;

- add docstrings explaining inputs, outputs, and units;

- add validation functions for each module;

- produce intermediate diagnostic tables;

- do not build input collection tools;

- do not build LEAP import/export tools;

- do not assume all economies have complete data;

- handle missing data with explicit fallback rules and warnings;

- preserve pre-adjustment and post-adjustment values wherever reconciliation or policy logic changes the model result;

- clearly distinguish:

<!-- -->

- official Python inputs to LEAP;

- official LEAP projection outputs;

- optional Python QA mirror outputs.

# End of Part 2
