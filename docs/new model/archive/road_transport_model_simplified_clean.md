# Road transport model conceptual guide

> **Purpose note**  
> This document explains how the road transport model works from an outside perspective. It focuses on the modelling logic, the main assumptions, and how users should interpret the workflow. For module sequencing, implementation details, output files, and full validation rules, use `road_transport_model_detailed.md`. For Module 1 data sourcing, the CSV contract, researcher UI workflow, and static row contract, use the Module 1 guide in the sibling `road_model_inputs_interface` repo.

## Contents

1. [What the road model is for](#1-what-the-road-model-is-for)
2. [Road branch structure in LEAP](#2-road-branch-structure-in-leap)
3. [Core stock-flow logic](#3-core-stock-flow-logic)
4. [Why part of the model happens before LEAP](#4-why-part-of-the-model-happens-before-leap)
5. [What researchers can adjust before LEAP](#5-what-researchers-can-adjust-before-leap)
6. [What can be adjusted in LEAP](#6-what-can-be-adjusted-in-leap)
7. [Passenger road stock projection](#7-passenger-road-stock-projection)
8. [Freight road stock projection](#8-freight-road-stock-projection)
9. [Sales, survival, and turnover](#9-sales-survival-and-turnover)
10. [Sales shares and technology uptake](#10-sales-shares-and-technology-uptake)
11. [Base-year energy and reconciliation](#11-base-year-energy-and-reconciliation)
12. [LEAP, Python QA, and official results](#12-leap-python-qa-and-official-results)

![End-to-end road model workflow](End-to-end%20road%20model%20workflow%208062026.png)

*Primary reference for the full end-to-end workflow. Some implementation detail is not shown.*

![Road transport model — researcher detail](Road%20transport%20model%20%E2%80%94%20researcher%20detail.png)

*Simplified illustration of the stock-flow modelling logic.*

## 1. What the road model is for

The road transport model estimates future energy demand from road vehicles. It covers passenger and freight road transport, including LPVs, motorcycles, buses, trucks, and light commercial vehicles.

The model is part of the wider APERC LEAP modelling system. Its job is to translate transport assumptions into energy demand by fuel. The most important assumptions are:

- how many vehicles are on the road;
- what kinds of vehicles they are;
- how far they travel;
- how efficient they are;
- how quickly old vehicles are replaced; and
- what technologies and fuels new vehicles use.

The model is detailed because road transport is one of the few demand sectors where stock-flow data can often explain energy use relatively well. If vehicle stock, mileage, fuel economy, and fuel shares are reasonable, the implied fuel demand can often be close to observed energy totals. The challenge is that these data are time-consuming to collect and can be incomplete or inconsistent across economies.

The workflow therefore combines three things:

1. a browser-based interface for reviewing and updating inputs;
2. a Python workflow for preparing, checking, and reconciling those inputs; and
3. LEAP as the official projection platform.

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

This structure is deliberately detailed. It lets the model distinguish between different types of vehicles, technologies, sizes, and fuels. That detail is useful for scenario analysis because changes such as faster BEV uptake, better ICE efficiency, lower mileage, or higher PHEV electric use can affect fuels in different ways.

## 3. Core stock-flow logic

At a conceptual level, the model is built around this relationship:

```text
energy use = vehicle stock × mileage × energy use per kilometre
```

In some parts of the workflow, fuel economy is represented as distance per unit of energy, such as km/GJ. In that case, higher fuel economy means lower energy use, so the calculation is written as stock × mileage divided by fuel economy. The interpretation is the same: energy demand depends on the number of vehicles, how much they are used, and how energy-efficient they are.

The stock-flow part of the model adds another relationship:

```text
future stock = surviving existing vehicles + new sales - additional retirements
```

This means the model does not simply draw a line for future energy demand. It builds energy demand from the fleet. Older vehicles survive or retire, new vehicles enter the fleet, and the mix of technologies changes over time through sales shares.

## 4. Why part of the model happens before LEAP

LEAP remains the official projection platform, but some road transport assumptions need to be prepared before data are imported into LEAP. This is because road transport is not just a set of independent variables. Stock, sales, retirements, vehicle-type shares, survival curves, mileage, fuel economy, and fuel allocation all interact.

For example, changing the share of buses, motorcycles, or LPVs is not just a simple branch split. It can change the passenger motorisation pathway, the number of vehicles required, future sales, and energy demand. Similarly, changing survival curves affects retirements, which affects sales, which affects the technology mix of the fleet.

The pre-LEAP interface and Python workflow exist to keep these relationships coherent. They allow users to review inputs, update important assumptions, run checks, and prepare a LEAP-ready package without needing to manually edit every related variable inside LEAP.

## 5. What researchers can adjust before LEAP

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

These assumptions can still be reviewed by researchers. The point is not to hide them in code, but to expose them in a controlled workflow so users can understand what is being changed and how the change affects the stock-flow pathway.

## 6. What can be adjusted in LEAP

Some variables can be adjusted directly in LEAP because they are useful scenario levers and do not necessarily require the whole stock-flow pathway to be rebuilt. These include:

- mileage adjustment factors;
- fuel economy or efficiency adjustment factors;
- technology sales shares, such as ICE, BEV, PHEV, and FCEV shares;
- fuel or Device Share settings where relevant; and
- scrappage or accelerated retirement settings, although these still need careful testing.

In practice, some of these variables may also be pre-set in the interface before LEAP import. That gives users a way to test assumptions and inspect likely outcomes before running the official LEAP projection.

The general rule is:

- use the pre-LEAP workflow for structural stock-flow assumptions; and
- use LEAP for official projection runs and controlled scenario changes.

## 7. Passenger road stock projection

Passenger road stock is projected using a motorisation approach. The model estimates how many passenger vehicles an economy is likely to have as income, population, and vehicle ownership change.

The key idea is vehicle-equivalent ownership. One LPV, one motorcycle, and one bus should not be treated as equal units when estimating passenger mobility or ownership saturation. A bus can replace many private vehicles, while a motorcycle represents a smaller transport unit. The model therefore converts physical vehicle stock into a weighted passenger vehicle-equivalent stock before projecting the overall motorisation envelope.

The broad method is:

1. calculate base-year passenger vehicle-equivalent ownership per person;
2. compare this with a long-run saturation level;
3. project ownership toward saturation using an S-curve;
4. split the projected vehicle-equivalent stock back into LPVs, motorcycles, and buses; and
5. convert the resulting stock pathway into sales and retirements.

This allows the model to represent economies at different stages of motorisation. Some economies may still have strong growth in vehicle ownership, while others may already be close to saturation and mainly change with population.

## 8. Freight road stock projection

Freight road stock is projected more simply than passenger road stock. The current method links freight stock growth to GDP growth using a bounded GDP elasticity. In plain terms, the model asks: if GDP grows by a certain amount, how much should freight vehicle stock grow?

The broad method is:

1. estimate a freight GDP elasticity from historical freight road energy and GDP trends where possible;
2. apply any reviewed adjustment to that elasticity;
3. clamp the elasticity within reasonable bounds;
4. project total freight road stock using GDP growth; and
5. split the stock between trucks and LCVs using base-year proportions.


## 9. Sales, survival, and turnover

Once stock targets are prepared, the model needs to work out how many new vehicles are sold each year. This depends on how many existing vehicles survive.

Survival curves describe the probability that a vehicle remains on the road at each age. Vintage profiles describe the age structure of the fleet. Together, they let the model estimate retirements and the new sales needed to reach the target stock pathway.

This is important because technology change happens mainly through new sales. If BEV sales shares increase, the total BEV stock does not change instantly. It changes gradually as new BEVs enter the fleet and older vehicles retire. Faster scrappage can accelerate this process, but it needs to be tested carefully because it can affect total sales, stock accounting, and the timing of technology turnover.

## 10. Sales shares and technology uptake

Sales shares control the technology mix of new vehicles. For example, sales shares determine how much of new LPV sales are ICE, HEV, PHEV, BEV, or FCEV.

Base-year sales shares are prepared from the best available evidence. Future sales-share pathways may be seeded from previous Outlook assumptions or other defaults, but they are intended to be reviewed and adjusted for scenario analysis.

Sales shares are one of the most important LEAP-side scenario levers. They let users test faster uptake of efficient or zero-emission vehicles while keeping the broader stock-flow structure intact.

## 11. Base-year energy and reconciliation

The base-year model calculates energy from stock, mileage, and fuel economy. However, this bottom-up estimate will not always match the official ESTO energy balance totals.

There are several reasons for this:

- vehicle stock data may be incomplete;
- mileage estimates may be uncertain;
- real-world fuel economy may differ from test-cycle values;
- fuel allocation across vehicle types may be uncertain; and
- ESTO road fuel totals may include activities that are difficult to assign perfectly to model branches.

The model therefore reconciles base-year road energy to ESTO fuel totals. This does not mean the vehicle data are ignored. Instead, the workflow adjusts stock, mileage, and fuel economy within configurable weights and bounds so that the final base-year model remains close to observed energy totals while preserving as much branch-level detail as possible.

This reconciliation step is important because the Outlook projection should begin from a base year that is consistent with official energy balances.

Fuel allocation is part of this reconciliation process. The workflow assigns observed ESTO road fuel totals to eligible vehicle and technology branches using reviewed rules, then checks whether the resulting stock, mileage, efficiency, and fuel shares are plausible.

## 12. LEAP, Python QA, and official results

LEAP is the official projection platform. Once the road inputs are prepared and imported, LEAP calculates the road transport projection as part of the wider APERC energy system model.

The Python workflow supports LEAP by preparing inputs, reconciling the base year, generating import workbooks, and running optional QA checks. It can also run a mirror calculation to help users understand expected behaviour before or after LEAP is run.

These Python checks are not a replacement for LEAP. They are diagnostic tools. Their purpose is to help users identify problems, understand model behaviour, and explain why the LEAP results look the way they do.

This matters because road transport affects the rest of the energy system. Road fuel demand can affect electricity generation, refining, biofuels, hydrogen, oil product demand, imports, exports, and the final energy balance.
