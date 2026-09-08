# `Demand\Nonspecified road` fallback for unprojected fuels

## Purpose and status

The LEAP mappings retain a first-level demand sector named
`Demand\Nonspecified road`. Its intended use is to carry an economy's road fuel
projection when that fuel has historical road demand but is outside the detailed
road model's projected fuel scope.

The maintained mapping contract in the sibling `leap_mappings` repository now
maps this branch to aggregate road and admits two fuel pairs:

- `Kerosene` / `07_06_kerosene`; and
- `Fuel oil` / `07_08_fuel_oil`.

These are currently the only historical road fuels that could not be assigned
to passenger or freight road. The detailed road model does not project them.
The initialisation workflow must still populate the branch with the applicable
economy projection; the mapping does not create values by itself.

Module 6 explicitly excludes these two canonical fuel names from its detailed
road reconciliation targets. They are therefore not allocated to passenger or
freight vehicle branches and are not reported as unreconciled in T12 or the
road dashboard. This exclusion is deliberately an exact two-fuel list: any new
fuel appearing in a later ESTO vintage will still be reported by reconciliation
QA until its classification and mapping have been reviewed.

## When to use the fallback

Use `Demand\Nonspecified road` only when all of the following are true:

- the economy has non-zero road demand for the fuel in the agreed historical
  energy dataset;
- the detailed road model does not produce a projection for that economy/fuel;
- the missing projection is an intentional model-scope gap, not a failed branch
  mapping, excluded zero-data branch, stale Module 1 package, or unsuccessful
  road-model run; and
- an explicit projection series and documented source or method are available.

Do not use this sector to absorb unexplained reconciliation residuals, duplicate
a fuel already projected in passenger or freight road, or hide a failed detailed
road import.

## Routing rule

For each `(economy, scenario, fuel)`:

```text
if detailed road projection exists:
    import it only to its detailed passenger/freight road branches
elif historical road demand is non-zero and an approved fallback projection exists:
    import the fallback series to Demand\Nonspecified road for that fuel
else:
    do not create a nonspecified-road projection; report the missing case
```

The detailed and fallback routes must be mutually exclusive. The selection
should be made at economy/fuel/scenario level before rows are written, with a
duplicate-energy check after assembly.

## Dashboard treatment

The mapping rolls `Nonspecified road` into the ordinary `Road`, `Transport`, and
`Total final energy consumption` comparison categories. Therefore, when the
branch contains data, the Common ESTO dashboard includes it in total road and
fuel charts without a fuel-specific dashboard rule. It remains unallocated
between passenger and freight and should not appear as either one.

If the dashboard omits the values, check that the source export contains the
branch/fuel pair, the mapping pipeline was rerun after the mapping change, and
the dashboard is using the refreshed Common ESTO output.

## New ESTO vintages and new road fuels

The approved pair list describes the current ESTO vintage, not a permanent
claim that kerosene and fuel oil are the only possible cases. When a 2026 or
later ESTO vintage introduces another non-zero fuel under road that the detailed
road model cannot assign:

1. confirm that the value is genuine road demand and not a subtotal, renamed
   product, or data error;
2. confirm that no detailed passenger/freight road branch projects it;
3. add the corresponding LEAP fuel pair under `Nonspecified road` in
   `leap_mappings/config/outlook_mappings_single_axis.xlsx`;
4. rerun the mapping pipeline and its coverage checks; and
5. refresh the dashboard inputs.

No new allocation method or dashboard code should be necessary. The mapping QA
should surface the new non-zero source pair as unmapped so the required action
is clear: review and add that one mapping.

### Review record at 8 September 2026

All ESTO road data available in the project as at 8 September 2026 was reviewed
for fuels that have non-zero demand in the latest year but cannot be assigned to
a detailed passenger or freight road branch. The review covered the 2025 ESTO
vintage through 2023 and the preliminary 2026 ESTO vintage through 2024. It did
not cover the finalised 2026 ESTO vintage, which was not yet available.

Only two fuels required `Nonspecified road` treatment:

| Fuel | Latest-year economies found | Evidence |
| --- | --- | --- |
| Kerosene (`07_06_kerosene`) | Chile (`04_CHL`) | Non-zero in 2023 in the 2025 vintage and in 2024 in the preliminary 2026 vintage. |
| Fuel oil (`07_08_fuel_oil`) | China (`05_PRC`); Chile (`04_CHL`) in the preliminary 2026 vintage | China is non-zero in both reviewed latest-year snapshots. Chile first appears as non-zero in the preliminary 2026 latest year. |

Natural gas liquids (`06.02 Natural gas liquids`) was also found under road for
the United States (`20_USA`), but only in 2009 and 2010. It is zero in the latest
year of both reviewed vintages. It therefore does not affect the current base
year or projection and does not require a `Nonspecified road` mapping at this
stage.

This is a dated review result. Repeat the check when the finalised 2026 vintage
or any later ESTO vintage is adopted.

## Required input shape

The fallback should use the canonical structure expected by the initialisation
pipeline rather than introducing a one-off file format. At minimum, each series
needs:

- economy;
- scenario;
- year;
- canonical fuel/product code or mapped LEAP fuel branch;
- value and energy unit;
- destination branch `Demand\Nonspecified road`;
- source/provenance; and
- a reason identifying the detailed road-model scope gap.

If the pipeline writes a LEAP import workbook, it must preserve the normal LEAP
header rows and metadata and use `(Branch Path, Variable, Scenario, Region)` as
the row key. IDs from another LEAP area must not be used for matching.

## Projection method

The fallback does not itself define how an absent fuel should grow. The series
must come from an approved source or a separately documented projection rule.
Acceptable examples might include an existing reviewed transport projection or
an explicit assumption that holds or phases the historical value. The chosen
method must be visible in provenance and applied consistently across scenarios.

Do not silently copy the trend of an unrelated fuel. If no defensible projection
is available, report the gap for a modeller decision.

## Validation checklist

Before importing a fallback series, confirm that:

- the detailed road output contains no row for the same economy, scenario, fuel,
  and year;
- the historical value is genuinely non-zero and is classified as road demand;
- the fuel maps to the intended LEAP fuel leaf;
- units and signs match the demand-sector convention;
- the series covers the required projection years without an unintended gap or
  discontinuity at the base year;
- Current Accounts contains only the calibrated historical/base-year treatment,
  while projection scenarios contain the intended future series;
- detailed road plus nonspecified road equals the intended total road demand
  exactly once for every economy, scenario, fuel, and year; and
- the resulting LEAP import contains no duplicate
  `(Branch Path, Variable, Scenario, Region)` keys.

After import, compare total road energy by fuel before and after adding the
fallback. Only the previously missing fuel should change. Passenger road and
freight road results should remain unchanged.

## Initialisation implementation work item

Implement this near the final assembly of initialisation demand projections,
where detailed road outputs and other demand-sector series can be compared. Keep
the fallback outside the detailed road model unless later scope explicitly adds
that fuel to the model. Add tests for detailed-only, fallback-only, zero-data,
missing-projection, and duplicate detailed-plus-fallback cases.
