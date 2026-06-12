# Road Transport Model Overview

> **Purpose note**
> This is a plain-English overview of the road transport model in `leap_road_model`. For implementation details, module sequencing, and output tables, see `road_transport_model_detailed.md`. For Module 1 data sourcing and the interface contract, see the road-model guide in the sibling `road_model_inputs_interface` repo.

![End-to-end road model workflow](End-to-end%20road%20model%20workflow%208062026.png)

*Primary reference for the full end-to-end workflow. Some implementation detail is not shown.*

![Road transport model - researcher detail](Road%20transport%20model%20%E2%80%94%20researcher%20detail.png)

*Simplified illustration of the stock-flow modelling logic.*

The road transport model is part of the APERC LEAP modelling system. It estimates future road transport energy demand for passenger and freight vehicles, including cars, motorcycles, buses, light commercial vehicles, and trucks. Its purpose is to translate assumptions about vehicle stock, sales, technology uptake, mileage, and fuel economy into energy demand by fuel.

The model is built around a simple idea:

**Energy use = vehicle stock x mileage x fuel economy**

In practice, the model contains many vehicle types, drive types, and fuels. Users do not need to understand every internal calculation to follow the logic. At a high level, the model asks:

* how many vehicles are on the road;
* what kinds of vehicles they are;
* how quickly older vehicles are replaced; and
* what fuels and technologies new vehicles use.

The workflow begins outside LEAP. This is not just a data-preparation step. A significant part of the road model is prepared before LEAP because stock, sales, retirements, and energy need to stay internally consistent.

Inputs are first prepared in a browser-based interface. The interface gives users one place to review, update, test, and document the main assumptions that describe the road transport system. These inputs fall into three broad groups.

First, the interface is used to update base-year evidence. This includes estimates of vehicle stock, mileage, and fuel economy. It also includes reconciliation settings such as weights, bounds, and adjustment rules, which help align the detailed vehicle data with the ESTO energy balances in the base year.

Second, the interface is used to prepare structural projection assumptions that are not intended to be edited directly in LEAP. These include the overall road stock and sales trajectory, projected vehicle-type shares such as cars, motorcycles, buses, and trucks, survival and vintage profile assumptions, freight stock-growth assumptions, and PHEV utilisation shares. These assumptions are important because they affect the stock-flow pathway itself. Changing them can affect sales, retirements, stock, and energy at the same time, so they are better prepared through the pre-LEAP workflow.

Third, the interface can be used to pre-set and test variables that may later be adjusted in LEAP. These include technology sales shares, mileage adjustment factors, fuel economy adjustment factors, fuel or device shares, and some scrappage settings. This means users can work in one place if they prefer: they can update base-year evidence, test projection assumptions, inspect the implied stock and energy outcomes, and then export a LEAP-ready package.

The Python workflow then converts these inputs into the structure that LEAP expects, creates import workbooks, and can run optional checks and simplified pre-LEAP simulations. These checks are not the official projection result, but they help users see whether their assumptions produce sensible stock, sales, retirement, and energy outcomes before the full LEAP model is run.

LEAP remains the official projection platform. Once the road transport inputs have been prepared and imported, LEAP calculates the official road transport energy projections as part of the wider APERC energy system model. This matters because road transport does not sit by itself: its fuel demand affects electricity generation, refining, biofuels, hydrogen, oil product demand, imports, exports, and the overall energy balance.

The Python workflow and dashboards should therefore be understood as support tools around LEAP. They help users prepare inputs, identify problems, compare assumptions, and understand model behaviour before and after running LEAP. They are especially useful because the road model is detailed and data-heavy, and because some stock-flow checks are easier to manage outside LEAP than inside it.

## What is prepared before LEAP?

Some assumptions are prepared through the browser interface and Python workflow before they are imported into LEAP. These are the assumptions that define the overall stock-flow pathway or the base-year calibration. They include:

* the overall road stock and sales trajectory;
* projected vehicle-type shares, such as cars, motorcycles, buses, and trucks;
* survival and vintage profile assumptions;
* freight stock-growth and elasticity settings;
* PHEV utilisation shares;
* base-year stock, mileage, and fuel economy estimates;
* reconciliation weights, bounds, and adjustment settings.

These assumptions are structural. For example, changing the share of cars, buses, or motorcycles is not just a simple split in LEAP: it can change total stock, total sales, retirements, and energy use. Similarly, survival and vintage profiles affect how quickly vehicles retire and how many new vehicles are needed to maintain the target stock pathway.

PHEV utilisation is also better prepared before LEAP because the calculation needed to convert a utilisation assumption into a fuel split can be complicated. The final fuel or device shares may appear in LEAP, but the underlying utilisation assumption is easier to manage in the pre-LEAP workflow.

These inputs are pre-set using the best available evidence and expert judgment, but users can review and adjust them if needed. The model is designed so that users can start with the most important variables and then explore more detailed assumptions if they want to go further. The goal is to keep the model flexible and transparent without requiring users to adjust every assumption manually.

## What can be adjusted in LEAP?

Some road transport assumptions can be adjusted directly in LEAP because they affect energy use or technology choice without necessarily changing the overall stock-flow structure. These include:

* mileage adjustment factors;
* fuel economy adjustment factors;
* technology sales shares, such as ICE, BEV, PHEV, and FCEV shares;
* fuel or device shares where the LEAP scenario requires them;
* scrappage or accelerated retirement settings, although these still need testing because they may interact with stock targets.

These variables are useful for scenario testing because they let users explore technology uptake, efficiency improvement, fuel switching, and changes in vehicle use within LEAP.

In practice, some of these same variables can also be pre-set and tested in the browser interface and Python workflow before they are imported into LEAP. This is useful when users want to check the effect of their assumptions in one place before running LEAP.

The interface also supports saving progress and moving data into Excel when that is faster for manual review or editing.

For road transport, the main principle is simple: LEAP is the official projection platform, but the road model is partly prepared before LEAP. Base-year evidence, reconciliation settings, and some projection assumptions are managed through the interface and Python workflow so that the stock-flow logic remains consistent. LEAP then uses those prepared inputs to calculate the official projection within the wider APERC model.

The model also needs to remain consistent with historical energy data. For the base year, road transport energy use should align with the ESTO energy balances. That means that even when detailed vehicle data are available, some calibration or reconciliation may still be needed. If the estimated number of vehicles, their mileage, and their fuel economy imply too much or too little fuel use, the model adjusts within reasonable bounds so that the base year remains consistent with observed energy totals.

In short, the road model acts as a bridge between transport assumptions and LEAP energy projections. The browser interface helps users update base-year data, set reconciliation rules, prepare structural projection assumptions, and test LEAP-adjustable variables. The Python workflow turns those assumptions into LEAP-ready inputs and quality checks. LEAP then produces the official energy projection within the wider APERC model. The goal is to keep a detailed road transport model while making it easier for users to understand, test, and explain.
