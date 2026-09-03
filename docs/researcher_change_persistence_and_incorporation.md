# Researcher change persistence and incorporation

## Purpose

Researchers need to be able to edit Module 1 values in the website without
losing those edits when the browser closes. The first objective is to preserve
exactly what they submitted. A later, reviewed process should incorporate
approved changes into future road-model datasets.

This document began as a design description and work specification. The
researcher archive path is now implemented in the interface and should be
validated with the minimum live test below after each deployment.

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

## Primary process: promote approved data into website defaults

The normal process for making an approved change appear as a new default in
the website is not `Upload Filled CSV`. That control is for a researcher
working copy or recovery. The primary promotion path is:

```text
Drive submission
  -> reviewer downloads and validates the CSV/metadata pair
  -> reviewer compares it with the exact baseline version
  -> reviewer approves individual rows and chooses the source owner
  -> reviewer updates the winning source file
  -> new immutable Module 1 version is generated
  -> frontend static bundle is generated from that same version
  -> interface repository is committed and pushed
  -> GitHub Actions synchronizes the interface snapshot to HF
  -> deployed website is hard-refreshed and checked
```

For a source-backed change, the reviewer must first determine which source
actually wins the source merge. For example, if a row exists in both
`processed_source/` and `manually_filled_rows/`, changing the lower-priority
manual row will not change the generated default. Confirm the resulting value
in the generated package rather than assuming the edited file was authoritative.

The source-version build should be run through the reviewer helper, which
passes the new version explicitly:

```python
from pathlib import Path
from scripts.review_researcher_submission import build_approved_source_version

build_approved_source_version("vYYYY_MM_DD_description")
```

Do not rebuild an existing immutable version in place. Use a fresh version name
for every promotion. The command-line entry point of the static builder is
intended for the configured default version and does not provide the same
explicit version argument as the reviewer helper.

The build requires the source package available under
`back-end/data/road_model/`, including the raw LEAP transport workbook inputs
when the active source method uses them. Those raw workbooks are intentionally
not part of the HF snapshot; the HF runtime uses the committed processed-source
outputs. A local promotion therefore needs the source workbooks available in
the local interface checkout or another approved source-preparation location.

After generation, verify all three layers for the affected row:

1. the generated package under
   `back-end/outputs/road_module1_defaults/<VERSION>/<ECONOMY>/`;
2. the static CSV under
   `front-end/road-module1-static/<VERSION>/`; and
3. `front-end/road-module1-static/index.json`, whose `default_version` should
   point to the new version.

Then commit the source update, generated package/static bundle, and
`UPDATE_METHOD.md` entry in the interface repository. Push its `main` branch,
wait for `sync_to_hf.yml` to succeed, hard-refresh the website, and confirm the
new value is displayed. Finally run the affected economy and retain the model
log, output timestamps, and dashboard/LEAP output links as evidence.

The promotion test must also check that the affected canonical key occurs only
once in the generated package and static CSV. This catches stale-output
accumulation and source-priority mistakes before deployment.

### Promotion dry-run findings

The disposable promotion test on 2026-09-03 found two additional checks that
must not be skipped:

- The review helper correctly compared the Australia test submission and
  produced the changed-row report, final-override candidate, and source-
  promotion plan. The plan left the source owner as a reviewer decision, as it
  should.
- Running `prepare_road_source.py` against the raw Target and Reference
  all-economies workbooks wrote 21 processed-source files. This is the required
  source-preparation step when the accepted value belongs to an upstream LEAP
  export; editing a generated `processed_source` CSV alone is not sufficient
  when the builder later overlays the upstream workbook.
- A clean test checkout did not contain the ignored raw LEAP workbooks, so the
  source-preparation inputs must be available locally for a source promotion.
  They are intentionally not copied into the HF snapshot.
- The current Australia generated package contains 608 duplicate rows across
  304 canonical `(Branch Path, Variable, Scenario, Year)` keys, while the
  generated static CSV contains no duplicate keys. The static step currently
  hides this problem by deduplicating. A conflicting promoted value can
  therefore remain hidden behind an older duplicate. Generated-package
  uniqueness must be fixed or made a hard promotion failure before treating a
  source promotion as fully verified.
- Rebuilding an immutable version in place can accumulate stale rows. Every
  promotion test and production update must use a new version directory.

The dry run therefore verified the review and source-preparation artifacts, but
it did not authorize a production source change or HF deployment. The next
implementation task is to remove or reject duplicate generated keys, then
repeat the promotion with a visible before/after value and the full GitHub-to-HF
verification.

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

## Minimum live acceptance test

This is the smallest useful deployed test. It proves that a researcher edit
travels through the browser, the Module 1 hand-off, the model workflow, and
the archive notification. Use a harmless, reversible change and record the
before and after values.

1. Hard-refresh the deployed interface after the HF Space rebuild and select
   one economy, such as Australia (`01AUS`). Confirm that the packaged economy
   list loads.
2. Choose one visible Module 1 value. Record its full row key, units, and
   original value. For example:

   ```text
   Economy:       01AUS
   Scenario:      Current Accounts
   Branch Path:   Demand\Freight road\Trucks\PHEV heavy\Electricity
   Variable:      Fuel Economy
   Year:          2022
   Units:         MJ/100 km
   Before:        831.01
   After:         831.02
   ```

3. Enter a short source/reason note, such as `Live round-trip test; reversible
   0.01 MJ/100 km change`, and press `Run Road Model`. Accept the archive
   warning when it appears.
4. Preserve proof from the run log. At minimum it should show:

   - `Module 1 CSV saved`;
   - `Researcher submission archive saved successfully`;
   - `Module 1 complete` with the loaded row count;
   - `Module 6 complete` with the LEAP-ready row count; and
   - `Completed successfully` with links to the dashboard and LEAP workbook.

5. Check the read-only archive status endpoint:

   ```text
   /api/v1/road-module1/archive-status
   ```

   The expected response is `available: true`. The run-log archive success
   message proves that this particular submission was accepted for archiving;
   the status endpoint proves that the configured archive is reachable.
6. Download the generated reconciled Module 1 CSV and verify that it remains
   canonical-long, contains the required columns, and has the changed row.
   Load that CSV with `load_module1_for_economy()` and run
   `road_workflow.py` in a temporary output directory. The second run should
   complete without changing the production defaults or static bundle.
7. Upload the downloaded CSV through the browser's `Upload Filled CSV` control
   and confirm that the interface accepts it. This upload is mandatory for the
   full acceptance test because it verifies the actual researcher re-entry
   path. Restore the original value and remove the test note afterwards.
   Automated browser sessions may be unable to operate the operating system's
   hidden native file picker; in that case, the loader plus temporary workflow
   run is a useful partial/diagnostic check, but the full acceptance test is
   incomplete until a person performs and records the upload step.

### Recorded example: Australia live test

On 2026-09-03, the deployed HF app was tested using the Australia row above.
The observed evidence was:

| Check | Result |
|---|---|
| Original value | `831.01 MJ/100 km` |
| Test value | `831.02 MJ/100 km` |
| Submitted rows | `21,420` canonical-long rows |
| Module 1 | `948` base input rows loaded |
| Module 5 | `3,471` future sales-share rows |
| Module 6 | `22,818` LEAP-ready rows |
| Workflow | Completed successfully in `54.2 seconds` |
| Archive | `Researcher submission archive saved successfully` |
| Archive status | `available: true` |
| Re-import processing | Python loader and temporary `road_workflow.py` run completed successfully |
| Browser CSV upload | Not automated; manual upload still required for full acceptance |
| Cleanup | Original value and note restored in the deployed UI |

This proves the deployed application can carry a changed value into a model
run and produce a re-importable package. The recorded run is not a complete
acceptance test until the downloaded CSV has also been uploaded through the
browser. It also does not, by itself, prove the contents of the Google Drive
file; that requires opening the configured Drive archive and checking the
timestamped CSV and metadata pair.

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

The archive save and review path is implemented in the active
`road_model_inputs_interface` branch. The Drive archive remains a record of
submissions rather than an automatic source for new defaults; incorporation
still requires a separate reviewed promotion process.
