# Road transport model methodology guide

> **Purpose note**  
> This document explains the methodology of the road transport model in `leap_road_model`. It is intended for researchers, reviewers, and external readers who need to understand how the model works without reading the implementation code. It is more detailed than the front-page overview, but it does not replace `road_transport_model_detailed.md`, which remains the modeller/developer guide for module sequencing, output tables, file paths, validation rules, and implementation details.

## Contents

1. [What the road model is for](#1-what-the-road-model-is-for)
2. [Road branch structure in LEAP](#2-road-branch-structure-in-leap)
3. [Main variables and how they interact](#3-main-variables-and-how-they-interact)
4. [Why part of the model happens before LEAP](#4-why-part-of-the-model-happens-before-leap)
5. [Base-year setup](#5-base-year-setup)
6. [Passenger road stock projection](#6-passenger-road-stock-projection)
7. [Freight road stock projection](#7-freight-road-stock-projection)
8. [Sales, survival, and turnover](#8-sales-survival-and-turnover)
9. [Sales shares and technology uptake](#9-sales-shares-and-technology-uptake)
10. [Mileage, fuel economy, and energy use](#10-mileage-fuel-economy-and-energy-use)
11. [Fuel allocation and Device Shares](#11-fuel-allocation-and-device-shares)
12. [Base-year reconciliation to ESTO](#12-base-year-reconciliation-to-esto)
13. [What researchers can adjust before LEAP](#13-what-researchers-can-adjust-before-leap)
14. [What researchers can adjust in LEAP](#14-what-researchers-can-adjust-in-leap)
15. [Python QA, LEAP, and official results](#15-python-qa-leap-and-official-results)
16. [Open methodology items for Codex / developer follow-up](#16-open-methodology-items-for-codex--developer-follow-up)

![End-to-end road model workflow](End-to-end%20road%20model%20workflow%208062026.png)

*Primary reference for the full end-to-end workflow. Some implementation detail is not shown.*

![Road transport model — researcher detail](Road%20transport%20model%20%E2%80%94%20researcher%20detail.png)

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

The Python workflow is not intended to replace LEAP. It prepares the road model so that the stock-flow logic is internally consistent before the official projection is run in LEAP.

## 2. Road branch structure in LEAP

The road branch hierarchy runs:

```text
transport type → vehicle type → drive type + size where relevant → fuel type
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

This hierarchy matters because many variables are defined at different levels.

For example:

- total passenger road sales are defined high in the branch structure;
- vehicle-type stock shares are defined at the LPV, motorcycle, bus, truck, or LCV level;
- technology sales shares are defined at the drive type level;
- mileage and fuel economy are usually applied at fuel-level branches; and
- fuel or Device Shares are applied where a drive type can consume more than one fuel.

This means a change at one level can affect many branches below it. For example, changing BEV sales share under LPVs affects future BEV stock, electricity demand, ICE stock share over time, and liquid fuel demand. Changing mileage at a fuel branch affects energy use for that branch, but does not directly change stock or sales.

## 3. Main variables and how they interact

The core road model can be understood through a small number of interacting variables.

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

Device Shares are closely linked to fuel allocation and reconciliation. They should generally be interpreted as the model’s fuel split within a branch, not always as a literal count of separate vehicle technologies.

### Energy

At the simplest level:

```text
energy = stock × mileage × energy use per kilometre
```

Where fuel economy is represented as km/GJ, the same relationship is written as:

```text
energy = stock × mileage / fuel economy
```

The model uses this relationship at the branch level, then aggregates across branches to produce road energy demand by fuel.

## 4. Why part of the model happens before LEAP

LEAP remains the official projection platform. However, some assumptions need to be prepared before they are imported into LEAP because the road model is not a set of independent variables.

The most important interactions are:

- stock targets determine the scale of the future fleet;
- survival and vintage profiles determine how many existing vehicles remain;
- retirements determine how many replacement vehicles are needed;
- sales shares determine what technologies enter through those new sales;
- vehicle-type shares can affect the total number of physical vehicles needed;
- mileage and efficiency determine energy use from the resulting stock; and
- fuel allocation and Device Shares determine which fuels are consumed.

Because of these interactions, changing one structural assumption can require several other variables to be recalculated. For example, changing the passenger split between LPVs, buses, and motorcycles can affect the passenger stock pathway, the number of sales required, technology uptake timing, and energy use. Changing the survival profile affects retirements, which affects new sales, which affects the speed of technology change.

The pre-LEAP workflow exists to keep these relationships coherent. It lets researchers review and update important assumptions through an interface while the Python workflow handles the linked stock-flow calculations needed to prepare LEAP inputs.

## 5. Base-year setup

The base year is the starting point for the road model. It needs to be consistent in two ways:

1. it should reflect the best available transport evidence; and
2. it should align with the official ESTO road energy balances.

The starting data usually include vehicle stock, mileage, fuel economy, fuel eligibility, base-year sales shares, survival curves, vintage profiles, population, GDP, and ESTO road fuel totals.

The model first uses the transport data to build a bottom-up representation of the base-year fleet. This means it estimates energy use from vehicles, distance travelled, and efficiency. It then compares the implied energy demand with ESTO fuel totals.

The base-year setup is not just a data-loading step. It defines the starting fleet structure for the projection. If the base-year stock mix, mileage, efficiency, or fuel allocation is wrong, the projection can still run, but the future results may be difficult to interpret.

The base-year setup also creates the link between the detailed road model and the wider LEAP energy system. Since the wider APERC model is built around energy balances, the road model must begin from a base year that is consistent with those balances.

## 6. Passenger road stock projection

Passenger road stock is projected using a motorisation approach. The model estimates how passenger vehicle ownership changes as income, population, and saturation conditions change.

The key issue is that not all passenger vehicles represent the same transport capacity. One LPV, one motorcycle, and one bus should not be treated as equivalent physical units. A bus can represent many LPV-equivalent units of passenger mobility or ownership demand, while a motorcycle represents a smaller unit.

The model therefore uses vehicle-equivalent ownership. Physical passenger vehicle stocks are converted into a weighted stock measure before the overall passenger motorisation pathway is projected.

At a high level, the passenger method is:

1. convert base-year LPVs, motorcycles, and buses into vehicle-equivalent stock;
2. divide by population to estimate base-year vehicle-equivalent ownership per person;
3. compare this with a long-run saturation level;
4. project ownership toward saturation using an S-curve;
5. convert the projected vehicle-equivalent stock back into physical vehicle-type stock targets; and
6. pass those stock targets to the sales and turnover calculation.

The saturation level represents the long-run vehicle ownership level that the economy is expected to approach. Economies with low current ownership and rising incomes may continue to grow toward saturation. Economies that are already close to saturation may have flatter ownership growth, with stock changing mainly because of population.

The S-curve is used because vehicle ownership normally does not grow linearly forever. Growth is often slower at low income levels, faster during motorisation, and slower again as saturation is approached.

The passenger vehicle-type split matters because it changes how the aggregate vehicle-equivalent stock is converted back into physical vehicles. A shift toward buses can reduce the number of physical vehicles needed for a given passenger vehicle-equivalent pathway. A shift toward motorcycles can increase or decrease physical counts depending on the relative weights used and the starting fleet composition.

This is why passenger vehicle-type assumptions are better prepared before LEAP. They are not just cosmetic branch shares. They affect the stock target, sales requirements, and eventual energy use.

### Passenger stock interaction example

Suppose an economy has rising passenger vehicle-equivalent ownership. If most of the increase is allocated to LPVs, physical vehicle stock may rise strongly. If some of the increase is allocated to buses, the physical number of vehicles may rise less, because each bus represents more vehicle-equivalent capacity. That then changes the number of sales required, the future technology mix, and total energy demand.

This means vehicle-type shares, vehicle-equivalent weights, and saturation assumptions should be reviewed together rather than treated as separate inputs.

## 7. Freight road stock projection

Freight road stock is projected differently from passenger road stock. Freight does not use a passenger-style ownership saturation curve. Instead, the current method links freight stock growth to GDP growth through a GDP elasticity.

The elasticity answers a simple question:

```text
If GDP grows by 1%, how much should freight vehicle stock grow?
```

At a high level, the freight method is:

1. estimate a freight GDP elasticity from historical freight road energy and GDP trends where possible;
2. apply any reviewed adjustment to that elasticity;
3. clamp the elasticity within reasonable bounds;
4. project total freight stock using GDP growth; and
5. split the projected stock between trucks and LCVs using base-year proportions.

This makes freight stock growth responsive to economic activity while avoiding a more complex freight tonne-kilometre model. The method is intentionally simpler than the passenger method because freight data are often weaker, and because the current model does not yet include a detailed mode-choice or logistics-demand structure.

The truck/LCV split is currently treated as a fixed structural split based on the base year. This means the model focuses on the overall growth of freight road stock rather than projecting a detailed shift between truck and LCV activity. If stronger evidence becomes available in the future, this could be expanded, but for now the simpler method keeps the freight model transparent and easier to review.

### Freight stock interaction example

If GDP grows quickly and the freight elasticity is high, freight stock grows quickly. That increases future sales requirements and energy demand, unless offset by efficiency improvement, lower mileage, or a shift to more efficient technologies. If the elasticity is low, the freight fleet grows more slowly even if GDP rises.

This makes the freight elasticity one of the most important freight road assumptions. It should be reviewed against historical energy trends, economy structure, and whether freight demand is expected to decouple from GDP growth.

## 8. Sales, survival, and turnover

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

### Additional scrappage

Additional scrappage represents early retirement beyond normal survival. It can be used to test policies that retire older or inefficient vehicles faster. However, scrappage affects more than energy demand. It also affects sales, stock accounting, technology uptake, and possibly the timing of fleet replacement. It should therefore be tested carefully before being treated as a standard scenario lever.

### Turnover interaction example

Consider two economies with the same BEV sales share pathway. In the economy with faster retirements, BEVs enter the total stock more quickly because more old vehicles are replaced each year. In the economy with slower retirements, the same BEV sales share has a slower effect on total stock and fuel demand. This is why survival and vintage assumptions are not background details; they shape how quickly sales-share assumptions affect energy outcomes.

## 9. Sales shares and technology uptake

Sales shares allocate new sales across vehicle types, drive technologies, sizes, and sometimes fuels. They are one of the main ways that scenario assumptions enter the road model.

For example, in the LPV branch, sales shares can determine how new sales are divided between ICE, HEV, PHEV, BEV, and FCEV. In freight, they can determine how new truck or LCV sales are divided between ICE, BEV, FCEV, and any other included technologies.

Sales shares affect the model through time. They do not immediately change the whole fleet. Instead:

```text
sales shares → new sales by technology → stock by technology → energy by fuel
```

This delay is central to stock-flow modelling. A rapid increase in BEV sales may have a modest effect on total electricity demand at first if most of the existing fleet is still ICE. Over time, as old vehicles retire and BEVs accumulate in the stock, the effect becomes larger.

Base-year sales shares are used to initialise the stock-flow model. Future sales shares are scenario assumptions. They may be seeded from previous Outlook pathways, defaults, or user-edited assumptions, but they should be reviewed because they strongly affect the technology pathway.

### Sales-share interaction example

If BEV sales shares increase while total sales are low, the stock changes slowly because few new vehicles are entering the fleet. If BEV sales shares increase while total sales are high, the stock changes faster. Therefore, technology uptake depends on both sales shares and the total sales pathway.

This is why stock, survival, sales, and sales shares should be reviewed together. Sales shares are important, but they do not determine stock outcomes on their own.

## 10. Mileage, fuel economy, and energy use

Mileage and fuel economy determine how much energy each vehicle uses.

The branch-level energy calculation can be understood as:

```text
vehicle-km = stock × mileage
energy = vehicle-km × energy intensity
```

Where fuel economy is expressed as km/GJ, this becomes:

```text
energy = stock × mileage / fuel economy
```

Mileage affects energy demand without changing stock. A lower mileage assumption can represent reduced travel, mode shift, lower vehicle utilisation, teleworking, logistics efficiency, or other demand-side changes. A higher mileage assumption increases energy use if stock and efficiency are unchanged.

Fuel economy affects the amount of energy required per kilometre. Better fuel economy lowers energy demand for the same stock and mileage. It can improve over time because of technology improvement, policy standards, or a shift toward more efficient drive types.

The model separates technology switching from within-technology efficiency improvement. For example, moving from ICE to BEV changes the drive technology mix. Improving ICE efficiency changes the energy use of remaining ICE vehicles. Both can reduce energy demand, but they work through different variables.

### Mileage and efficiency interaction example

If stock grows by 20%, mileage stays constant, and fuel economy improves by 20%, total energy demand may remain roughly stable. If stock grows but mileage also falls, energy may grow more slowly than stock. If stock grows and efficiency does not improve, energy will usually rise unless the technology mix shifts strongly toward more efficient vehicles.

This is why energy results should not be interpreted from one variable alone. Stock growth, mileage, efficiency, and technology mix all interact.

## 11. Fuel allocation and Device Shares

The model must convert vehicle activity and technology assumptions into fuel demand. This requires fuel allocation rules and Device Shares.

A single-fuel branch is straightforward. For example, a BEV branch consumes electricity and an FCEV branch consumes hydrogen. Multi-fuel branches are more complicated. ICE branches may be linked to several liquid or gaseous fuels. PHEV and EREV branches consume both electricity and liquid fuel.

Device Shares describe how a technology branch is split across fuels. They are calculated or prepared so that LEAP can represent fuel use within each technology branch.

For PHEVs and EREVs, the electric utilisation assumption is especially important. It determines how much travel is treated as electric driving and how much is assigned to liquid fuel. This affects both electricity demand and liquid fuel demand.

Fuel allocation also matters in the base year because ESTO reports road energy by fuel, while the bottom-up model estimates energy by vehicle branch. The workflow needs to allocate observed fuel totals to eligible branches in a way that is consistent with the branch structure and known transport patterns.

### Fuel allocation interaction example

If an economy has high diesel road demand, the model needs to decide which diesel-eligible branches receive that fuel. In most cases this should be concentrated in freight vehicles before passenger vehicles, because trucks and LCVs are usually the main diesel users. If the model allocates too much diesel to passenger branches, the base-year stock and Device Shares may look implausible even if the total road diesel demand matches ESTO.

This is why fuel allocation is both a calibration step and a plausibility check.

## 12. Base-year reconciliation to ESTO

The bottom-up estimate of base-year road energy will not always match the ESTO road fuel totals. This is expected. Vehicle stock, mileage, and fuel economy are all uncertain, and fuel allocation across vehicle branches may not be directly observed.

The model therefore reconciles the base-year road model to ESTO. The purpose is to keep the detailed stock-flow model consistent with official energy balances.

The reconciliation process can be understood as:

1. calculate initial branch energy from stock, mileage, and fuel economy;
2. allocate ESTO fuel totals to eligible road branches;
3. compare allocated fuel energy with initial branch energy;
4. calculate the correction needed for each branch;
5. split that correction across stock, mileage, and fuel economy using configurable weights;
6. apply bounds so the correction does not make inputs implausible;
7. recalculate final energy; and
8. calculate final Device Shares and diagnostics.

The correction is split across stock, mileage, and fuel economy because the model does not assume that all error comes from one source. Stock may be uncertain, mileage may be uncertain, and fuel economy may be uncertain. The reconciliation weights determine which variables absorb more of the adjustment.

For example, if the bottom-up model estimates too little gasoline demand, the reconciliation can increase stock, increase mileage, reduce km/GJ fuel economy, or some combination of these. Bounds prevent these adjustments from moving too far from the original evidence.

This reconciliation affects the projection because the reconciled base-year stock, mileage, and fuel economy become the starting point for future modelling. If base-year stock is adjusted substantially, the stock target pathway may also need to be re-anchored so the future projection starts from the reconciled fleet.

### Reconciliation interaction example

Suppose the model has good stock data but weak mileage data. The user may want reconciliation to adjust mileage more than stock. If the model has weak stock data but reasonable mileage and fuel economy, the user may allow more adjustment to stock. The reconciliation weights and bounds therefore express modelling judgement about which inputs are most uncertain.

## 13. What researchers can adjust before LEAP

The pre-LEAP workflow is used for assumptions that define the stock-flow pathway or base-year calibration. These include:

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

These variables are prepared before LEAP because they often affect several downstream calculations at once. The goal is to make them visible and reviewable without requiring researchers to manually maintain every dependent LEAP variable.

For example, changing survival assumptions affects retirements and sales. Changing passenger vehicle-type shares affects vehicle-equivalent stock allocation. Changing PHEV utilisation affects electricity and liquid fuel demand. These are all better handled through a workflow that recalculates the connected variables together.

## 14. What researchers can adjust in LEAP

Some variables are suitable for direct LEAP scenario editing because they are useful levers once the stock-flow structure has been prepared. These include:

- mileage adjustment factors;
- fuel economy or efficiency adjustment factors;
- technology sales shares, such as ICE, BEV, PHEV, and FCEV shares;
- fuel or Device Share settings where relevant; and
- scrappage or accelerated retirement settings, once implementation is tested.

These variables are useful for EED or scenario design because they let researchers test changes to travel demand, efficiency, technology uptake, and fuel use.

However, users should remember that even LEAP-editable variables interact with the stock-flow model. For example, changing sales shares affects future stock gradually through turnover. Changing mileage affects energy demand directly but does not change stock. Changing scrappage affects retirements and may affect replacement sales.

The general rule is:

- use the pre-LEAP workflow for structural stock-flow assumptions and base-year reconciliation; and
- use LEAP for official projection runs and controlled scenario changes.

## 15. Python QA, LEAP, and official results

LEAP is the official projection platform. Once the road inputs are prepared and imported, LEAP calculates the road transport projection as part of the wider APERC energy system model.

The Python workflow supports LEAP by preparing inputs, reconciling the base year, generating import workbooks, and running optional QA checks. It can also run a mirror calculation to help users understand expected behaviour before or after LEAP is run.

The Python mirror is not a replacement for LEAP. It is a diagnostic tool. Its purpose is to help users identify problems, understand model behaviour, and explain why the LEAP results look the way they do.

This matters because road transport affects the rest of the energy system. Road fuel demand can affect electricity generation, refining, biofuels, hydrogen, oil product demand, imports, exports, and the final energy balance.

A useful way to interpret the workflow is:

```text
Interface = review and update assumptions
Python workflow = prepare, reconcile, and check road inputs
LEAP = official projection and integration with the whole energy system
Dashboards = compare, diagnose, and explain results
```

## 16. Open methodology items for Codex / developer follow-up

The following items should be checked against the current code before this document is treated as final.

### TODO: confirm exact sales and turnover handling when surviving stock exceeds target

This document explains the general logic that target stock is compared with surviving stock to determine sales. Codex should confirm the exact current treatment when surviving cohorts exceed the target stock, including whether the model scales surviving stock, records unmet target behaviour, or handles the case differently by vehicle type or scenario.

### TODO: confirm current scrappage implementation

This document treats scrappage as a possible scenario lever that still needs careful testing. Codex should confirm which scrappage variables are currently exported to LEAP, which branches they apply to, and whether the implementation is ready for routine EED scenario use.

### TODO: confirm exact PHEV and EREV utilisation method

This document explains PHEV and EREV fuel splitting conceptually. Codex should confirm the exact formula used to convert electric utilisation into electricity and liquid fuel demand, how efficiency differences between electric and liquid operation are handled, and whether EREV is treated identically to PHEV or with separate efficiency assumptions.

### TODO: confirm future sales-share seeding method

This document says that future sales shares may be seeded from previous Outlook assumptions or defaults. Codex should confirm the current source hierarchy, re-anchoring method, fallback rules, and which future sales-share variables researchers are expected to edit directly in LEAP.

### TODO: confirm which methodology assumptions are visible in the interface

This document describes the intended researcher-facing assumptions. Codex should confirm which of these are currently visible and editable in the browser interface, which are present but hidden, and which still need interface support.
