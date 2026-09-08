# Reviewing road-model results against the 9th edition

## Purpose

This note is for researchers importing the new road model into LEAP and checking
whether its results are reasonable. It explains how to interpret differences
from the 9th-edition projection, what to check first, and when a difference
should be escalated for investigation.

The 9th-edition result is a useful comparator, not a target that the new model
must reproduce. A projection to 2060 can diverge substantially even when many
headline parameters appear similar, because modest differences in the base
year, fleet turnover, fuel allocation, and technology uptake compound over
time.

## Recommended review workflow

1. Import the current road-model package into the intended LEAP area and run the
   relevant projection scenario.
2. Compare the result with the 9th-edition dashboard at economy, scenario,
   transport-type, vehicle-type, drive-type, and fuel level where possible.
3. Identify the first year and lowest branch level at which the paths begin to
   diverge. Do not diagnose a 2060 total from the final-year difference alone.
4. Check whether the difference is explained by one of the known model changes
   below.
5. Review the underlying Module 1 assumptions and their sources. The supplied
   values are defaults and starting points, not immutable official assumptions.
6. If a result is not appropriate for the economy, the responsible researcher
   should update the relevant assumption. Seek modelling support when the
   correct lever or expected effect is unclear.
7. Escalate a case for code or data investigation when the result cannot be
   explained by an intentional assumption, a documented structural change, or
   normal long-run compounding.

## Likely drivers of differences

### Passenger/freight allocation of gasoline and diesel

Where more detailed evidence is unavailable, the new workflow uses a simplifying
allocation that places gasoline primarily in passenger road and diesel primarily
in freight road. This is a material structural change from a less explicit or
different historical allocation.

The allocation can change total fuel use by transport type and therefore change
the subsequent transition. Passenger and freight fleets do not evolve in the
same way: for example, freight may adopt electric vehicles later than passenger
road. A base-year transfer of fuel from one side to the other can therefore
produce a growing difference by 2060 even when aggregate road energy initially
matches.

When this appears to be the main driver, check both the aggregate road total and
the passenger/freight split. Do not treat an offsetting passenger and freight
difference as unexplained aggregate growth.

### Turnover and survival assumptions

The turnover method and survival assumptions have changed from the 9th-edition
workflow. The current method makes the stock-flow relationship more explicit:
surviving vehicles, retirements, sales, and any additional scrappage jointly
determine how the fleet reaches its stock target.

These assumptions affect the speed at which new drive types enter the fleet.
When technology uptake differs, inspect survival curves, vintage profiles,
retirements, new sales, and sales shares together. A sales-share change should
normally affect stock gradually as the fleet turns over, rather than replacing
the stock immediately.

### Reconciled base-year inputs and structural conversion

The new base-year package reflects newer energy data and reconciliation, revised
fuel allocation, migration to a new platform, and several category mapping
changes. Creating the LEAP-ready structure may require categories to be renamed,
aggregated, disaggregated, or otherwise adjusted.

Base-year changes to stock, mileage, fuel economy, vehicle composition, or fuel
allocation can propagate through every projected year. Review the base year
before interpreting later differences. In particular, distinguish:

- a different but internally reconciled starting point;
- a changed projection assumption;
- a branch-mapping or unit problem; and
- a genuine calculation defect.

## What should trigger investigation

Investigate rather than simply accepting the difference when any of the
following occurs:

- the imported base year does not reconcile to the intended ESTO road-fuel
  totals within the configured tolerance;
- shares under the same parent do not sum to 100%;
- stock changes immediately in response to a lever that should only affect
  mileage or efficiency;
- energy moves in the opposite direction from the intended mileage or
  efficiency change;
- a fuel appears under an ineligible technology or transport type;
- a discontinuity begins at the import year without a corresponding input
  change;
- the dashboard, T11 table, imported LEAP expressions, and calculated LEAP
  results disagree; or
- the difference remains unexplained after tracing it to the earliest divergent
  year and branch.

## Correction-factor verification in LEAP

`Mileage Correction Factor` and `Fuel Economy Correction Factor` rows are
accepted from Module 1 and exported to the corresponding fuel branches in T11.
The code test verifies that their year and numeric value survive that hand-off.
This does **not** yet prove that the target LEAP model applies the factors in the
intended direction or calculation order.

Until that LEAP-side behaviour has been tested, correction factors should be
treated as provisionally supported and should not be used for material scenario
changes without a small controlled check. For one isolated branch:

1. Record the baseline stock, mileage, fuel economy, activity, and energy.
2. Change only the Mileage Correction Factor (for example from 1.00 to 1.10),
   recalculate LEAP, and record which outputs change and by how much.
3. Restore the baseline, change only the Fuel Economy Correction Factor by the
   same amount, and repeat.
4. Confirm the direction against LEAP's displayed units. The imported road fuel
   economy is expressed as distance per unit of energy, so greater effective
   efficiency should reduce energy for fixed stock and distance.
5. Repeat once in Current Accounts and once in a projected scenario to establish
   inheritance and scenario behaviour.
6. Save screenshots or an export of the expressions and before/after results,
   then update this note with the verified formula and calculation order.

If changing a factor has no visible effect, first confirm that the factor is on
the exact active fuel branch, its expression is present in the active scenario,
and the result was recalculated. Do not infer that the factor works merely
because it imported successfully.

## Comparison dashboard

The actual local combined dashboard created for this comparison is:

- launcher: `results/qa_9th_dashboard_comparison/index.html`;
- economy pages: `results/qa_9th_dashboard_comparison/<economy>.html`;
- build evidence: `results/qa_9th_dashboard_comparison/comparison_manifest.json`;
  and
- generator: `scripts/build_9th_dashboard_with_new_model.py`.

The generator combines the original 9th-edition dashboard files in
`C:\Users\Work\Downloads\9th_transport_model_dashboards\transport_dashboards`
with new-model results in
`results/qa_9th_comparison/new_model_all_scenarios`. Its default output is
`results/qa_9th_dashboard_comparison`. The manifest records the exact source
paths and generated economy pages for a particular build.

The packaged copy named in the handover is also present locally at
`C:\Users\Work\Downloads\9th_transport_model_dashboards_road_updated.zip`.
Later local variants named `_v2.zip` and `_v3.zip` also exist, so use the exact
unversioned filename when reproducing the handover unless a later version is
explicitly selected and checked.

The same unversioned package is available from the shared road dashboard folder:

- [Shared road dashboard folder](https://drive.google.com/drive/folders/1GFH21NSIFS8mLZUMbt4XgdO7OmrPmtT0?usp=sharing)
- [Previously shared dashboard file](https://drive.google.com/file/d/1sf4FX3UHRv4UEvCSiwnougJK6ZB4_SJX/view?usp=drive_link)

The updated dashboard includes comparisons with 9th-edition data. Its new-model
series are based on the road model's defaults. They show what the current
starting assumptions produce; they do not remove the researcher's responsibility
to review and, where justified, change those assumptions for their economy.

## Ownership during initialisation

Researchers should raise uncertain results with the road-model contact. The
contact should help identify the relevant assumption or diagnostic and collect
recurring drivers across economies. Cases that still look wrong from a modelling
or data perspective should then be investigated in the source data, mappings,
handoff workbook, or model code as appropriate.
