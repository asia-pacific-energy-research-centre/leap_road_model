# `Demand\Nonspecified road` fallback for unprojected fuels

## Purpose and status

The LEAP mappings retain a first-level demand sector named
`Demand\Nonspecified road`. Its intended use is to carry an economy's road fuel
projection when that fuel has historical road demand but is outside the detailed
road model's projected fuel scope.

This is a proposed initialisation fallback. It is not currently implemented in
`leap_road_model`, and no matching routing logic was found in the local
`leap_initialisation` or `leap_mappings` code during preparation of this note.
Implementation should therefore be verified against the then-current
initialisation code and mappings before release.

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

## Proposed routing rule

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

## Implementation work item

Implement this near the final assembly of initialisation demand projections,
where detailed road outputs and other demand-sector series can be compared. Keep
the fallback outside the detailed road model unless later scope explicitly adds
that fuel to the model. Add tests for detailed-only, fallback-only, zero-data,
missing-projection, and duplicate detailed-plus-fallback cases.
