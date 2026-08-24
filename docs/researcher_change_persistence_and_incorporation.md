# Researcher change persistence and incorporation

## Purpose

Researchers need to be able to edit Module 1 values in the website without
losing those edits when the browser closes. The first objective is to preserve
exactly what they submitted. A later, reviewed process should incorporate
approved changes into future road-model datasets.

This document is a design description and work specification. It does not
require the implementation to be built immediately.

## Researcher-facing behaviour

The existing `Run Road Model` action should remain the natural save point.

1. The website detects whether the researcher changed any input values.
2. Only when changes are detected, small explanatory text appears below the
   `Run Road Model` button.
3. The text explains that the changed values will be saved and may be used in
   future road-model datasets. It should also explain that previous submissions
   can be retrieved if the researcher later loses their local copy.
4. When the researcher runs the model, the completed economy CSV is saved as an
   immutable, timestamped submission in the shared Google Drive archive.
5. The model run continues using the submitted values, regardless of whether
   the archive save succeeds. A save failure should be reported clearly and
   should not silently imply that the submission was archived.

Suggested archive folder:

`https://drive.google.com/drive/folders/1vxeVur4Bnc6w-K4kUqIPxxTbgaB9k3pr`

The archive should be organised by economy, with no overwriting of previous
submissions. A submission filename should contain at least the economy,
timestamp with timezone, and Module 1/default version. Researcher or session
identity should be included when available.

Example:

```text
20_USA/
  2026-08-24T14-32-18+09-00_researcher_module1_v2026_06_05.csv
  2026-08-24T14-32-18+09-00_researcher_module1_v2026_06_05_metadata.json
```

The CSV should be the complete submitted economy package, not only the changed
rows. A metadata record should identify the submission time, economy, source
version, researcher/session where available, and the application run ID.

## Canonical data format

The preferred comparison and archive format is the canonical long Module 1
format. Its important identity fields are:

```text
Economy, Scenario, Branch Path, Variable, Year
```

The value and provenance fields include:

```text
Value, Scale, Units, Source, Comment, Input Status, Shown In Interface
```

Older packages use a legacy wide layout. They identify a row with metadata and
store years as columns such as `2022`, `2030`, `2040`, and `2050`. The model
still accepts this format for compatibility, but it should not be the format
used for new archives or comparisons.

The easiest compatibility approach is to normalize both formats at the review
boundary:

- Read either long or legacy wide CSV.
- Convert legacy wide year columns into one long row per year.
- Normalize compact economy codes such as `20USA` to `20_USA`.
- Use the `Scale` value when converting legacy internal values to the display
  values used in the website.
- Compare rows by `(Economy, Scenario, Branch Path, Variable, Year)`.
- Treat exact duplicate rows as one row, but reject duplicates with conflicting
  values.
- Keep the original archived CSV unchanged for audit purposes.

This avoids forcing an immediate rewrite of all historical data while giving
the future process one stable representation.

## Comparing a submission with defaults

Every submission must be compared with the exact defaults package/version that
was used to run it. The comparison should produce a review table containing:

```text
Economy, Scenario, Branch Path, Variable, Year,
Baseline Value, Submitted Value, Delta, Action
```

`Action` should identify at least:

- `changed` — both rows exist but values differ;
- `added` — the submission contains a row absent from the baseline;
- `removed` — the baseline contains a row absent from the submission.

Rows should be compared in the same scale/display convention before the delta
is calculated. Numeric comparisons need a small tolerance so harmless floating
point representation differences are not treated as researcher changes.

## Two approved incorporation paths

After review, each change should be assigned one of two meanings.

### Path A: retain as a final override

Use this when the change is economy-specific, temporary, still under review, or
does not clearly belong in a reusable upstream source file.

The existing `final_value_overrides/` mechanism is the natural target. Its
override rows use:

```text
Branch Path, Variable, Scenario, Year, Value, Units,
share_decreased_from, note, DO_NOT_USE
```

The generated override must convert website/display values back to the
internal model units expected by the override engine. In particular, values
shown in Millions or Thousands must not be written to the override file as if
they were raw model values.

For `Sales Share` and `Stock Share`, the reviewer must decide how the sibling
share is balanced. `share_decreased_from` can identify the sibling that absorbs
the change; when it is blank, the existing rebalance logic scales the remaining
sibling shares. The generated override report should be inspected before the
override is treated as approved.

### Path B: promote into a new source version

Use this when the change is accepted as the new underlying economy data and
should become part of the normal defaults for future runs.

Do not edit an old generated version in place. Instead:

1. Identify the correct source owner: processed source, manually filled rows,
   supplemental source data, or a reviewed final override.
2. Apply the approved change to that source location.
3. Archive the previous source/generated version.
4. Build a new immutable, dated defaults version.
5. Regenerate the frontend static bundle from that same version.
6. Run the affected economy and inspect the change report, model outputs, and
   dashboard.
7. Record the source, method, affected economy, and validation in
   `UPDATE_METHOD.md`.

The promotion path is deliberately more controlled than the override path. A
complete researcher CSV should not be copied wholesale into processed source
data, because the CSV may contain generated rows, derived rows, hidden rows,
or values that belong to a different source category.

## Review and testing process

The first implementation should be tested without changing production data:

1. Select one economy and copy its exact baseline package into a temporary test
   area.
2. Make a few controlled edits covering at least a normal scalar, a scaled
   value such as Stock/Mileage, and one share value.
3. Save the test submission in both canonical-long and legacy-wide forms if
   compatibility is being tested.
4. Normalize both submissions and produce the per-row change report.
5. Test Path A by applying the generated override to a temporary new build.
6. Verify the expected Module 1 rows, model outputs, share balancing, and
   dashboard values.
7. Test Path B separately by applying one approved change to the appropriate
   source location and generating a new version.
8. Remove the temporary override/source edits and regenerate the test package.
9. Confirm the original values and outputs are restored.

The test must not overwrite the production defaults version, the active static
bundle, or the real Drive archive. Test submissions should be clearly marked
as temporary and kept outside the production processing queue.

## Important boundaries

- The Drive archive is a record of researcher submissions, not automatically a
  source of truth for the model.
- Archived files must never be silently merged into new defaults.
- A complete submission is useful for recovery, but incorporation is a
  per-row, reviewed decision.
- Generated output folders are not source files and should not be edited as a
  substitute for source promotion.
- The old wide format should remain readable during migration, but new tools
  should emit and compare canonical long files.

## Current implementation status

The implementation described during this task has intentionally been kept out
of the active branch. A future agent may inspect the named Git stash in the
`road_model_inputs_interface` repository and reuse or revise it, but the design
above is authoritative if the implementation is rebuilt.
