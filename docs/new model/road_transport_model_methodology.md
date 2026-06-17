# Road transport model methodology guide

> **Purpose note**  
> This document explains the methodology of the road transport model in `leap_road_model`. It is intended for researchers, reviewers, and external readers who need to understand how the model works without reading the detail required for using or managing the code. It is more detailed than the front-page overview, but it does not replace `road_transport_model_modeller_guide.md`, which remains the modeller guide.

## Contents

1. [What the road model is for](#1-what-the-road-model-is-for)
2. [Road branch structure in LEAP](#2-road-branch-structure-in-leap)
3. [Main variables and how they interact](#3-main-variables-and-how-they-interact)
4. [Why some road preparation happens before LEAP](#4-why-some-road-preparation-happens-before-leap)
5. [Overall model workflow](#5-overall-model-workflow)
6. [Base-year setup](#6-base-year-setup)
7. [Passenger road stock projection](#7-passenger-road-stock-projection)
8. [Freight road stock projection](#8-freight-road-stock-projection)
9. [Sales, survival, vintage profiles, and turnover](#9-sales-survival-vintage-profiles-and-turnover)
10. [Technology sales shares and LEAP scenario assumptions](#10-technology-sales-shares-and-leap-scenario-assumptions)
11. [Base-year fuel allocation and reconciliation](#11-base-year-fuel-allocation-and-reconciliation)
12. [What researchers can adjust before LEAP](#12-what-researchers-can-adjust-before-leap)
13. [What researchers can adjust in LEAP](#13-what-researchers-can-adjust-in-leap)
14. [Python simulated outputs, LEAP, and official results](#14-python-simulated-outputs-leap-and-official-results)
15. [Open methodology items for Codex / developer follow-up](#15-open-methodology-items-for-codex--developer-follow-up)

![End-to-end road model workflow](End-to-end%20road%20model%20workflow%208062026.png)

*Primary reference for the full end-to-end workflow. Some implementation detail is not shown.*

![Road transport model â€” researcher detail](Road%20transport%20model%20%E2%80%94%20researcher%20detail.png)

*Simplified illustration of the stock-flow modelling logic.*

## 1. What the road model is for

The road transport model estimates road transport energy demand by fuel. It covers passenger and freight road transport, including LPVs, motorcycles, buses, trucks, and light commercial vehicles.

The model translates transport assumptions into energy demand. The main questions it answers are:

- how many vehicles are on the road;
- what types of vehicles they are;
- what technologies they use;
- how far they travel;
- how efficient they are;
- what fuels they consume; and
- how quickly old vehicles are replaced by new vehicles.

The model is detailed because road transport is one of the demand sectors where bottom-up stock-flow data can explain energy use relatively well. If vehicle stock, mileage, fuel economy, fuel shares, and technology shares are reasonable, the implied road fuel demand can often be close to observed energy totals.

However, the data are not always complete or consistent. Some economies have strong vehicle registration data, but weaker mileage or fuel economy data. Others have reasonable aggregate road fuel demand, but limited vehicle-level detail. For this reason, the model combines bottom-up transport assumptions with reconciliation to the official ESTO energy balances.

The workflow combines three parts:

1. a browser-based interface for reviewing and updating assumptions;
2. a Python workflow for preparing, checking, and reconciling inputs; and
3. LEAP as the official projection platform.

The Python workflow is not intended to replace LEAP. It prepares the road model so that the stock-flow inputs are coherent and reviewable before the official projection is run in LEAP.

## 2. Road branch structure in LEAP

The road branch hierarchy runs:

```text
transport type â†’ vehicle type â†’ drive type + size where relevant â†’ fuel type
```

Each leaf in the tree below is a LEAP branch.

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

The intention is to provide detail where it is useful, not to make every branch equally detailed. LPVs receive the most detail because they are usually the largest part of the fleet, have better data, and are where many technology-transition assumptions are most policy-relevant. Smaller or less data-rich branches are kept simpler where extra detail would add work without improving the result. At the same time, the model still needs enough detail to represent the different needs of APEC economies. Reducing detail is useful for keeping the model understandable and manageable, but it has to be weighed against the need to represent economies with different fuels, technologies, and vehicle structures.

This hierarchy matters because variables are defined at different levels, which is a result of model design decisions, which was sometimes influenced by the way LEAP works.

This means a change at one level can affect many branches below it. For example, changing BEV sales share under LPVs affects future BEV stock, electricity demand, ICE stock share over time, and liquid fuel demand. Changing mileage at a fuel branch affects energy use for that branch, but does not directly change stock or sales.

Current scope rules (important when comparing to the 9th edition and earlier 10th edition LEAP models):

- `HEV` and `EREV` are LPV-only.
- Truck `PHEV` is out of scope.
- LPVs use `small`, `medium`, and `large` size labels.
- Trucks use `medium` and `heavy` size labels where truck-size splits are needed.
- `Fuel Economy` is the canonical Module 1 efficiency variable. `Final On-Road Fuel Economy` can be accepted only as a legacy input alias.

The changes were generally intended to 
The same vehicle/drive/size matrix should be used by Module 1 validation and
Module 2 branch generation. Module 1 rows outside this matrix should be rejected
or explicitly recategorized before export; Module 2 should not create branches
outside this matrix during skeleton generation.


## 3. Main variables and how they interact

This section introduces the main variables used in the road model. Later sections explain them in the order that the model uses them.

### Stock

Stock is the number of vehicles on the road. Stock can be described at different levels: total passenger road stock, LPV stock, BEV stock, or fuel-specific stock implied by Device Shares.

Stock is central because more vehicles usually means more energy use, unless offset by lower mileage, better efficiency, or a shift to more efficient technologies.

### Sales

Sales are new vehicles entering the fleet in a given year. Sales determine how quickly the fleet changes. A future BEV sales share of 80% does not mean that 80% of the fleet is immediately BEV. It means that 80% of new sales are BEV, and the stock share changes gradually as older vehicles retire.

### Retirements

Retirements are vehicles leaving the fleet. Retirements are mostly determined by survival curves and vintage profiles. Additional scrappage can also be used where a policy causes vehicles to retire earlier than normal.

Retirements matter because they create the need for replacement sales. Faster retirement can accelerate technology turnover, but it can also increase total sales and change the timing of stock changes.

### Survival and vintage profiles

A survival profile describes how likely a vehicle is to remain on the road at each age. A vintage profile describes the age distribution of the fleet in the base year.

These profiles connect the stock target to sales. If the fleet is young and vehicles survive for a long time, fewer replacement sales are needed. If the fleet is old or vehicles retire quickly, more sales are needed to maintain the same stock.

### Mileage

Mileage is the average distance travelled per vehicle per year. Higher mileage increases energy use without changing the number of vehicles. Mileage can represent travel demand, vehicle utilisation, modal shift effects, or other behavioural and operational changes.

### Fuel economy / efficiency

Fuel economy describes how much energy is needed to travel a given distance. In the current workflow, fuel economy may be represented as distance per unit of energy, such as km/GJ. Under that convention, higher fuel economy means lower energy use.

This is important for interpreting scalars and correction factors: increasing a km/GJ efficiency value reduces energy demand, while increasing an MJ/km energy-intensity value would increase energy demand.

### Sales shares

Sales shares split new sales across vehicle types, technologies, and sometimes sizes. They are the main way that technology uptake enters the stock-flow model.

Sales shares affect future energy demand indirectly. They first change new sales, then stock, then activity by technology, and finally energy use by fuel.

### Stock shares

Stock shares describe how total stock is split across vehicle types or technologies. In the base year, they help define the starting fleet structure. In projection assumptions, some stock shares can define structural pathways, such as the split between LPVs, motorcycles, and buses.

Stock shares are not always safe to edit directly in LEAP because they can change the stock-flow pathway that sales and turnover need to satisfy.

### Device Shares

Device Shares split a technology branch across fuels. For example, a PHEV branch may consume both electricity and liquid fuel. An ICE branch may have gasoline, diesel, LPG, natural gas, or biofuel-related fuel branches depending on the branch structure.

Device Shares are closely linked to fuel allocation and reconciliation. They should generally be interpreted as the modelâ€™s fuel split within a branch, not always as a literal count of separate vehicle technologies.

### Energy

At the simplest level:

```text
energy = stock Ã— mileage Ã— energy use per kilometre
```

Where fuel economy is represented as km/GJ, the same relationship is written as:

```text
energy = stock Ã— mileage / fuel economy
```

The model uses this relationship at the branch level, then aggregates across branches to produce road energy demand by fuel.

## 4. Why some road preparation happens before LEAP

LEAP remains the official projection platform, and many important interactions still happen inside LEAP. The reason part of the road model is prepared before LEAP is not that LEAP cannot represent stock-flow behaviour. The reason is that several of the road model inputs are difficult to prepare, calibrate, and review directly inside LEAP.

The main pre-LEAP preparation tasks are:

- the overall road stock and sales trajectory;
- survival and vintage profile assumptions;
- PHEV utilisation shares;
- base-year stock, mileage, and fuel economy estimates; and
- base-year reconciliation to ESTO road fuel totals.

These tasks involve linked calculations, source-data cleaning, judgement about uncertain inputs, and checks against historical energy balances. Preparing them outside LEAP simplifies the modelling process because researchers can review the main assumptions in a focused interface while Python prepares the dependent LEAP inputs consistently.

This should not be understood as a separation where Python does all interactions and LEAP simply stores the result. Some interactions occur before LEAP because they are easier to prepare there, while others occur in LEAP during the official stock-turnover projection. The pre-LEAP workflow is therefore a preparation and QA layer around LEAP, not a replacement for LEAP.

## 5. Overall model workflow

The road model workflow follows the same broad order as the modelling logic.

1. **Prepare base-year evidence.**  
   The workflow starts with stock, mileage, fuel economy, fuel eligibility, observed road fuel demand, sales shares where available, and supporting macroeconomic data.

2. **Project road stock targets.**  
   Passenger stock is projected through a vehicle-equivalent ownership and saturation method. Freight stock is projected through a GDP-elasticity method.

3. **Convert stock targets into sales and retirements.**  
   Survival curves and vintage profiles are used to determine how many vehicles remain each year and how many new sales are needed to reach the stock target.

4. **Prepare or seed sales shares.**  
   Base-year sales shares initialise the model, while future sales-share assumptions are mainly scenario levers. Some may be seeded before LEAP, but a large part of technology uptake is expected to be reviewed and adjusted in LEAP.

5. **Allocate fuels and reconcile the base year.**  
   The model calculates initial branch energy from stock, mileage, and fuel economy, allocates ESTO fuel totals to eligible branches, adjusts uncertain inputs within bounds, and calculates Device Shares.

6. **Export LEAP-ready inputs.**  
   The prepared inputs are imported into LEAP, where the official projection is run as part of the wider APERC energy system.

7. **Use dashboards and simulated outputs for QA.**  
   Python can produce simulated outputs and diagnostics to help users understand likely effects, but LEAP remains the official projection.

## 6. Base-year setup

The base year is the starting point for the road model. It needs to be consistent in two ways:

1. it should reflect the best available transport evidence; and
2. it should align with the official ESTO road energy balances.

The starting data usually include vehicle stock, mileage, fuel economy, fuel eligibility, base-year sales shares, survival curves, vintage profiles, population, GDP, and ESTO road fuel totals.

The model first uses the transport data to build a bottom-up representation of the base-year fleet. This means it estimates energy use from vehicles, distance travelled, and efficiency. It then compares the implied energy demand with ESTO fuel totals during the reconciliation step.

The base-year setup is not just a data-loading step. It defines the starting fleet structure for the projection. If the base-year stock mix, mileage, efficiency, or fuel allocation is wrong, the projection can still run, but the future results may be difficult to interpret.

The base-year setup also creates the link between the detailed road model and the wider LEAP energy system. Since the wider APERC model is built around energy balances, the road model must begin from a base year that is consistent with those balances.

## 7. Passenger road stock projection

Passenger road stock is projected using a motorisation approach. The model estimates how passenger vehicle-equivalent ownership changes with population, GDP per capita, recent passenger road energy growth, and saturation conditions.

The key issue is that not all passenger vehicles represent the same transport capacity. One LPV, one motorcycle, and one bus should not be treated as equivalent physical units. A bus can represent many LPV-equivalent units of passenger mobility or ownership demand, while a motorcycle represents a smaller unit.

The model therefore uses vehicle-equivalent ownership. Physical passenger vehicle stocks are converted into a weighted stock measure before the overall passenger motorisation pathway is projected.

At a high level, the passenger method is:

1. convert base-year LPVs, motorcycles, and buses into vehicle-equivalent stock;
2. divide by population to estimate base-year vehicle-equivalent ownership per person;
3. compare this with a long-run saturation level;
4. estimate a GDP-per-capita income elasticity from historical passenger road energy growth and historical GDP-per-capita growth;
5. project ownership with future GDP-per-capita growth, damping that growth as ownership approaches saturation;
6. convert the projected vehicle-equivalent stock back into physical vehicle-type stock targets; and
7. pass those stock targets to the sales and turnover calculation.

The saturation level represents the long-run vehicle-equivalent ownership level that the economy is expected to approach. Economies with low current ownership may continue to grow toward saturation as GDP per capita rises. Economies that are already close to saturation should not be forced to keep increasing ownership simply because historical energy grew.

For economies that are not saturated, the model uses passenger road energy as the activity proxy and compares its historical growth with historical GDP-per-capita growth. The resulting income elasticity is bounded, multiplied by the reviewed passenger stock growth-rate adjustment, and then checked against the same bounds again. If the historical data are insufficient or GDP-per-capita growth is near zero, the model uses the default passenger income elasticity.

For each projection year, GDP-per-capita growth is applied to the previous year's vehicle-equivalent ownership level. The growth effect is multiplied by the remaining distance to saturation, expressed as `1 - current motorisation / saturation motorisation`. This keeps the projection responsive to future income growth while making ownership growth fade as saturation is approached.

For economies that are already saturated, the model holds vehicle-equivalent ownership broadly flat. Physical stock can still change if population changes or if the vehicle-type split changes, but the model is no longer assuming structural growth in ownership per person.

The passenger vehicle-type split matters because it changes how the aggregate vehicle-equivalent stock is converted back into physical vehicles. A shift toward buses can reduce the number of physical vehicles needed for a given passenger vehicle-equivalent pathway. A shift toward motorcycles can increase or decrease physical counts depending on the relative weights used and the starting fleet composition.

This is why passenger vehicle-type assumptions are better prepared before LEAP. They are not just cosmetic branch shares. They affect the stock target, sales requirements, and eventual energy use.

### Passenger stock interaction example

Suppose an economy has rising passenger vehicle-equivalent ownership. If most of the increase is allocated to LPVs, physical vehicle stock may rise strongly. If some of the increase is allocated to buses, the physical number of vehicles may rise less, because each bus represents more vehicle-equivalent capacity. That then changes the number of sales required, the future technology mix, and total energy demand.

This means vehicle-type shares, vehicle-equivalent weights, saturation assumptions, and passenger growth adjustments should be reviewed together rather than treated as separate inputs.

## 8. Freight road stock projection

Freight road stock is projected differently from passenger road stock. Freight does not use a passenger-style ownership saturation curve. Instead, the current method links freight stock growth to GDP growth through a GDP elasticity.

The elasticity answers a simple question:

```text
If GDP grows by 1%, how much should freight vehicle stock grow?
```

At a high level, the freight method is:

1. estimate a freight GDP elasticity from historical freight road energy and GDP trends where possible;
2. clamp the estimated elasticity within reasonable bounds;
3. apply any reviewed adjustment to that bounded elasticity and check it against the same bounds again;
4. project total freight stock using GDP growth; and
5. split the projected stock between trucks and LCVs using base-year proportions.

The freight activity proxy is historical freight road energy growth. Unlike the passenger method, the freight method estimates compound endpoint growth rates over the filtered lookback window: one for freight road energy and one for GDP. It then divides freight energy growth by GDP growth to estimate a GDP elasticity. If either series has fewer than two usable observations, if the first usable value is not positive, or if GDP growth is effectively zero, the default elasticity is used instead.

This makes freight stock growth responsive to economic activity while avoiding a more complex freight tonne-kilometre model. The method is intentionally simpler than the passenger method because freight data are often weaker, and because the current model does not yet include a detailed mode-choice or logistics-demand structure.

The truck/LCV split is currently treated as a fixed structural split based on the base year. This means the model focuses on the overall growth of freight road stock rather than projecting a detailed shift between truck and LCV activity. If stronger evidence becomes available in the future, this could be expanded, but for now the simpler method keeps the freight model transparent and easier to review.

### Freight stock interaction example

If GDP grows quickly and the freight elasticity is high, freight stock grows quickly. That increases future sales requirements and energy demand, unless offset by efficiency improvement, lower mileage, or a shift to more efficient technologies. If the elasticity is low, the freight fleet grows more slowly even if GDP rises.

This makes the freight elasticity one of the most important freight road assumptions. It should be reviewed against historical energy trends, economy structure, and whether freight demand is expected to decouple from GDP growth.

## 9. Sales, survival, vintage profiles, and turnover

After passenger and freight stock targets are prepared, the model needs to determine sales and retirements. This is the stock-flow part of the model.

The basic accounting identity is:

```text
ending stock = surviving prior stock + new sales - additional retirements
```

A stock target says how many vehicles should be on the road in a future year. The model then uses survival and vintage assumptions to estimate how many vehicles from previous years remain. The difference between the target stock and surviving stock determines how many new sales are needed.

If surviving stock is below the target, new sales fill the gap. If surviving stock is already above the target, the model needs to handle this carefully. This can happen when the target stock is flat or declining but the existing fleet survives for a long time.

Turnover is important because it controls the speed of technology change. Even if new sales become mostly BEV, the existing ICE fleet remains until it retires. A younger fleet with long lifetimes changes slowly. An older fleet or a policy with additional scrappage changes more quickly.

### Survival curves

A survival curve describes the probability that a vehicle is still operating at each age. A curve with long survival keeps more older vehicles in the fleet. A curve with shorter survival causes faster retirements and higher replacement sales.

### Vintage profiles

A vintage profile describes the base-year age distribution of the fleet. Two economies can have the same total stock but very different age structures. If one fleet is much older, it may have higher near-term retirements and therefore faster stock turnover.

### How profiles are checked and adjusted

Survival and vintage profiles are not just imported as decorative assumptions. Module 4 normalises survival curves and vintage profiles, aligns them to the same age range, and uses them in cohort stock-flow accounting.

If lifecycle calibration factors are available, the workflow can scale survival curves to meet turnover-rate bounds and then re-derive vintage profiles from the calibrated survival curves. A base-year fleet age shift can also be applied before the stock-flow calculation. These adjustments are recorded in the Module 4 lifecycle outputs and exported through the lifecycle profile workbooks.

Where surviving vehicles exceed the target stock, the model does not produce negative sales. It scales the surviving cohorts down to the target, records `stock_above_target = True`, and stores the applied scale factor. This is important for economies or vehicle types where the stock path is flat or declining while the existing fleet remains on the road for a long time.

### Additional scrappage

Additional scrappage represents early retirement beyond normal survival. It can be used to test policies that retire older or inefficient vehicles faster. However, scrappage affects more than energy demand. It also affects sales, stock accounting, technology uptake, and possibly the timing of fleet replacement. It should therefore be tested carefully before being treated as a standard scenario lever.

### Turnover interaction example

Consider two economies with the same BEV sales share pathway. In the economy with faster retirements, BEVs enter the total stock more quickly because more old vehicles are replaced each year. In the economy with slower retirements, the same BEV sales share has a slower effect on total stock and fuel demand. This is why survival and vintage assumptions are not background details; they shape how quickly sales-share assumptions affect energy outcomes.

## 10. Technology sales shares and LEAP scenario assumptions

Sales shares allocate new sales across vehicle types, drive technologies, sizes, and sometimes fuels. They are one of the main ways that technology uptake enters the road model.

For example, in the LPV branch, sales shares can determine how new sales are divided between ICE, HEV, PHEV, BEV, and FCEV. In freight, they can determine how new truck or LCV sales are divided between ICE, BEV, FCEV, and any other included technologies.

Sales shares affect the model through time. They do not immediately change the whole fleet. Instead:

```text
sales shares â†’ new sales by technology â†’ stock by technology â†’ energy by fuel
```

This delay is central to stock-flow modelling. A rapid increase in BEV sales may have a modest effect on total electricity demand at first if most of the existing fleet is still ICE. Over time, as old vehicles retire and BEVs accumulate in the stock, the effect becomes larger.

A large part of technology uptake is intended to be handled in LEAP. The pre-LEAP interface can provide preliminary sales-share assumptions and allow users to observe simulated outputs, but the official projection depends on how LEAP applies its own stock-turnover calculations, scenario expressions, and calculation order. For that reason, pre-LEAP technology results should be described as simulated outputs or QA outputs, not official projections.

Base-year sales shares are used to initialise the stock-flow model. Future sales shares may be seeded from previous Outlook pathways, defaults, or user-edited assumptions, but they should be reviewed in LEAP because they strongly affect the technology pathway.

### Sales-share interaction example

If BEV sales shares increase while total sales are low, the stock changes slowly because few new vehicles are entering the fleet. If BEV sales shares increase while total sales are high, the stock changes faster. Therefore, technology uptake depends on both sales shares and the total sales pathway.

This is why stock, survival, sales, and sales shares should be reviewed together. Sales shares are important, but they do not determine stock outcomes on their own.

## 11. Base-year fuel allocation and reconciliation

The base-year reconciliation step is where stock, mileage, fuel economy, fuel allocation, and Device Shares come together. This is why it is better to explain these variables as part of the reconciliation process rather than as completely separate modelling steps.

The purpose of reconciliation is to make the detailed bottom-up road model consistent with ESTO road fuel totals while keeping the underlying transport assumptions plausible. The bottom-up estimate will not always match ESTO because stock, mileage, fuel economy, and fuel split assumptions are all uncertain.

At the simplest level, initial branch energy is calculated as:

```text
vehicle-km = stock Ã— mileage
energy = vehicle-km / fuel economy
```

where fuel economy is expressed as distance per unit of energy, such as km/GJ. Under this convention, a higher fuel economy value reduces energy use.

The reconciliation process can be understood as the following sequence.

### Step 1 â€” Calculate initial branch energy

The model first calculates energy for each road branch using the current stock, mileage, and fuel economy assumptions. This gives an initial bottom-up estimate of road energy use by branch and fuel.

This first estimate is useful because it shows what the transport data imply before forcing the result to match the energy balance.

### Step 2 â€” Handle electricity for BEVs, PHEVs, and EREVs first

Electricity is handled before ordinary liquid fuel allocation because BEVs, PHEVs, and EREVs need to be reconciled against the road electricity total. BEVs are straightforward because they use electricity only. PHEVs and EREVs are more complicated because they split travel between electricity and liquid fuel.

The PHEV utilisation assumption controls the share of PHEV/EREV driving treated as electric. This is difficult to manage directly in LEAP because it affects both electricity demand and liquid fuel demand. The pre-LEAP workflow therefore prepares the implied fuel split so users can review whether the electric/liquid split is plausible.

### Step 3 â€” Subtract PHEV/EREV liquid fuel from liquid fuel pools

After electricity use is calculated for PHEVs and EREVs, the corresponding liquid fuel use is removed from the relevant ESTO liquid fuel pools before the remaining liquid fuels are allocated to ICE and HEV branches.

This prevents the same liquid fuel being allocated twice. For example, if some gasoline is already assigned to PHEV liquid operation, that gasoline should not also be assigned to ordinary ICE vehicles.

In the current methodology, PHEV and EREV liquid fuel is treated as gasoline-family fuel. Diesel and biodiesel are not assigned to PHEV/EREV branches unless the model is changed deliberately.

### Step 4 â€” Allocate remaining ESTO fuels to eligible branches

For ordinary fuel allocation, eligibility depends on the vehicle and drive structure. Electricity is handled first for BEV/PHEV/EREV branches, PHEV/EREV liquid fuel is handled separately as gasoline-family fuel, and the remaining liquid or gaseous fuels are allocated to eligible ICE, HEV, and other configured branches.

Fuel allocation is not only a mathematical split. It also embeds transport judgement. The allocation needs to reflect likely fuel use by vehicle type, especially where ESTO reports fuel totals but does not say exactly which road branches consumed that fuel.

The main allocation logic is:

- diesel and biodiesel are allocated to freight ICE vehicles first, with Trucks and LCVs sharing the freight tier in proportion to initial branch energy, before any remaining amount is allowed to spill into passenger vehicles;
- gasoline and biogasoline are allocated to passenger vehicles first, then to LCVs if needed, and are not normally allocated to trucks;
- within a priority group, allocation is proportional to initial branch energy, not raw vehicle stock;
- electricity is handled through the BEV/PHEV/EREV electricity process before ordinary liquid fuel reconciliation;
- hydrogen is allocated only to FCEV branches where relevant; and
- other fuels use their configured eligibility rules and are allocated by energy share across eligible branches unless a reviewed priority rule exists.

The exact fuel allocation order matters because it affects the reconciled stock, mileage, fuel economy, and Device Shares. For example, putting too much diesel into passenger branches may make the base-year model match total diesel demand but produce an implausible vehicle/fuel structure.

### Step 5 â€” Compare allocated fuel energy with initial branch energy

After fuel has been allocated to eligible branches, the model compares allocated ESTO-consistent fuel energy with the initial bottom-up energy estimate.

This comparison gives the correction required for each branch. If the bottom-up estimate is too low, the model needs to increase implied branch energy through stock, mileage, or fuel economy adjustments. If the estimate is too high, it needs to reduce implied branch energy through those same variables.

### Step 6 â€” Split the correction across stock, mileage, and fuel economy

The model does not assume that all error comes from one variable. Stock may be uncertain, mileage may be uncertain, and fuel economy may be uncertain. The correction is therefore split across these variables using reconciliation weights.

For example, if the bottom-up estimate is below the allocated fuel energy, the model could:

- increase stock;
- increase mileage;
- reduce km/GJ fuel economy; or
- use a combination of all three.

The reconciliation weights express judgement about which inputs are most uncertain. If stock data are considered strong but mileage data are weak, more adjustment can be directed toward mileage. If mileage and fuel economy are considered reliable but stock data are weak, more adjustment can be directed toward stock.

### Step 7 â€” Apply bounds to keep adjustments plausible

Reconciliation is not allowed to move values without limit. Bounds are applied so that stock, mileage, and fuel economy do not shift too far from the source evidence.

If the required correction is larger than the bounds allow, a residual gap can remain. That gap should be reported through diagnostics rather than hidden. Large corrections are important review signals because they may indicate weak source data, a wrong fuel allocation rule, missing branches, or a mismatch between transport data and ESTO fuel totals.

If ESTO reports positive energy for a fuel but all eligible branches have zero stock, Module 6 can seed a small positive stock so reconciliation has a branch to adjust. For zero-stock rows that remain in the output, mileage and fuel-economy scalars can be inherited from comparable peer branches so future calculations do not lose adjustment information.

### Step 8 â€” Recalculate final energy

After stock, mileage, and fuel economy are adjusted, final branch energy is recalculated. The recalculated fuel totals should match ESTO within tolerance unless the bounds prevented full reconciliation.

This recalculated base year becomes the starting point for the projection. If base-year stock changes substantially during reconciliation, the future stock pathway may need to be re-anchored so that the projection starts from the reconciled stock level rather than the original unreconciled estimate.

### Step 9 â€” Calculate Device Shares

Device Shares are calculated after reconciliation because the fuel split depends on final stock, mileage, fuel economy, and allocated fuel energy.

For single-fuel technologies, Device Share is straightforward. BEV branches consume electricity, and FCEV branches consume hydrogen. For multi-fuel technologies, Device Shares describe the modelled fuel split within the branch.

This is especially important for PHEVs and EREVs, where Device Shares need to reflect the electric/liquid split implied by the utilisation assumption and the reconciliation results.

### Step 10 â€” Validate and review

The final reconciliation outputs should be checked for:

- whether road fuel totals match ESTO;
- whether stock, mileage, and fuel economy adjustments are within bounds;
- whether Device Shares sum correctly within each branch;
- whether PHEV/EREV utilisation remains plausible;
- whether fuel allocation produced plausible vehicle/fuel combinations; and
- whether any residual gaps or fallback rules need review.

Reconciliation is therefore both a calibration step and a QA step. It makes the model consistent with ESTO, but it also shows where source data or assumptions may need to be revisited.

## 12. What researchers can adjust before LEAP

The pre-LEAP workflow is used for assumptions that are difficult to prepare directly in LEAP or that need linked calculations before import. These include:

- the overall road stock and sales trajectory;
- base-year vehicle stock;
- base-year mileage;
- base-year fuel economy;
- passenger saturation assumptions;
- vehicle-equivalent weights;
- passenger vehicle-type shares;
- freight GDP-elasticity settings;
- survival and vintage profile assumptions;
- PHEV electric utilisation assumptions;
- reconciliation weights and bounds; and
- notes or metadata explaining overrides.

These variables are prepared before LEAP because they often require several dependent calculations to be updated together. The aim is to simplify the workflow for users while still keeping the assumptions visible and reviewable.

For example, changing survival assumptions affects retirements and sales. Changing passenger vehicle-type shares affects vehicle-equivalent stock allocation. Changing PHEV utilisation affects electricity and liquid fuel demand. Changing reconciliation weights changes how the base-year difference between bottom-up data and ESTO is allocated across stock, mileage, and fuel economy.

## 13. What researchers can adjust in LEAP

Once the pre-LEAP workflow has prepared the stock-flow structure, some assumptions can be adjusted directly in LEAP as scenario levers. These are mainly variables that affect technology uptake, utilisation, efficiency, or fuel splits without rebuilding the underlying stock, sales, and turnover pathway.

The safest LEAP edits are made in projection scenarios, not Current Accounts. Current Accounts should normally remain the calibrated base-year setup.

| Change | Where to change it | What it does | Main checks |
| --- | --- | --- | --- |
| Technology uptake | `Sales Share` at vehicle-type or drive/engine level. | Changes which technologies enter the fleet through new sales. The effect appears gradually as the stock turns over. | Shares must sum to 100% within each parent. Check that stock changes gradually, not instantly. |
| Mileage Correction Factor | `Mileage Correction Factor` at fuel branches. | Changes distance travelled per vehicle and therefore energy demand. This should not be changed without strong reasoning, because mileage often stays relatively stable over time. | Check that energy changes directly. Stock should not change just because mileage changed. |
| Efficiency Correction Factor | `Fuel Economy Correction Factor` at fuel branches. | Changes the effective fuel economy or efficiency used in the energy calculation. This can represent efficiency improvement within a technology, separate from shifts between ICE, BEV, PHEV, and other technologies. As a rough benchmark, new-vehicle efficiency has often improved by around 1.5-2% per year, while whole-fleet efficiency usually changes more slowly because older vehicles remain in the stock. | Check the unit direction before deciding whether the factor should rise or fall. |
| Fuel split within a technology | `Device Share` at fuel branches. | Changes how a technology branch is split across fuels. | Device Shares under one parent must sum to 100%. PHEV and EREV Device Shares should usually come from the pre-LEAP utilisation workflow, because the resulting electricity utilisation share is difficult to infer manually. |
| Technology availability | `First Sales Year`. | Prevents a technology from receiving sales before a specified year. | Check whether sales shares before that year are ignored or reallocated as intended. |
| Scrappage / accelerated retirement | Scrappage-related variables at drive/engine type branches. | Can accelerate retirement beyond normal survival profiles. | Advanced only. Check sales, retirements, stock, and replacement assumptions together. These settings are not yet part of the routine `T11` LEAP import workflow, so use them carefully until the hand-off is extended. |

The general rule is to use the pre-LEAP workflow for base-year calibration and structural stock-flow assumptions, then use LEAP for controlled scenario changes. Variables such as vehicle-type stock shares, survival profiles, vintage profiles, passenger saturation, freight elasticity, PHEV utilisation, and reconciliation weights should generally not be changed directly in LEAP, because they affect several linked calculations at once.

## 14. Python simulated outputs, LEAP, and official results

LEAP is the official projection platform. Once the road inputs are prepared and imported, LEAP calculates the road transport projection as part of the wider APERC energy system model.

The Python workflow supports LEAP by preparing inputs, reconciling the base year, generating import workbooks, and running optional QA checks. It can also run a mirror calculation to help users understand expected behaviour before or after LEAP is run.

The Python mirror and interface outputs should be called simulated outputs or QA outputs. They are useful because they show the likely effect of assumptions before the full LEAP model is run, and they help users understand whether inputs are plausible. However, the final result still depends on LEAP's own stock-turnover calculations, scenario expressions, calculation order, and integration with the wider energy system.

This matters because road transport affects the rest of the energy system. Road fuel demand can affect electricity generation, refining, biofuels, hydrogen, oil product demand, imports, exports, and the final energy balance.

A useful way to interpret the workflow is:

```text
Interface = review and update assumptions
Python workflow = prepare, reconcile, and simulate/check road inputs
LEAP = official projection and integration with the whole energy system
Dashboards = compare, diagnose, and explain results
```

## 15. Open methodology items for Codex / developer follow-up

The following items should be checked against the current code before this document is treated as final.

### Scrappage implementation boundary

Module 4 stores explicit scrappage values as `scrappage_for_leap`, and Module 7 can use scrappage inputs in the Python mirror. The current Module 6 LEAP-ready table does not emit routine `Scrappage` rows, so this is not yet a standard LEAP hand-off lever. Before routine use, decide the exact LEAP variable rows, branch levels, and interface controls.

### Future sales-share seeding status

The current workflow can read explicit future sales-share inputs, use projected Module 1 sales-share rows, or fall back to base-year-flat trajectories. When previous Outlook trajectories are available, Module 5 re-anchors non-ICE drive trajectories to the new base-year shares while preserving the provided shape; ICE is the residual. If the shape-preserving method would make ICE negative, Module 5 switches that vehicle/scenario group to linear interpolation and records method flags.

### Interface visibility status

The current static contract in `road_model_inputs_interface/back-end/data/road_model/config/road_module1_static_contract.csv` marks all rows as shown in the base interface. In the projected editing view, projected `Sales Share` rows are the exception: they are present in the hand-off contract but marked hidden, so they can seed the model without being part of the routine projected-assumption editing workflow.
