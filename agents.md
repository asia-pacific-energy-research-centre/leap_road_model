# AGENTS.md - Road Model and Interface Guide for AI Assistants

This file documents the system from an agentic perspective: invariants, non-obvious
design decisions, deprecated patterns, and data flow. Read this before touching
scenarios, LEAP import logic, Module 1 defaults, or the interface hand-off.

---

## Background and glossary

APERC is the Asia Pacific Energy Research Centre. APERC prepares the APEC Energy
Demand and Supply Outlook, usually shortened to the Outlook. The road model in
this repo supports the transport part of that Outlook by preparing road-transport
inputs and LEAP import packages.

ESTO is the APERC team and dataset that maintains the APEC energy balances used
as historical energy inputs. In this model, ESTO road energy anchors base-year
fuel reconciliation. Routine road runs use the repo-local snapshot
`input_data/esto_transport_2000_2022.csv`.

The 9th edition refers to the previous APERC Outlook cycle. Several current
inputs are still seeded from 9th-edition macro, sales-share, and LEAP export
materials while the 10th-edition workflow is being built. Treat those inputs as
bridge assumptions unless a source doc says they have been reviewed for the 10th
edition.

The road model is separate from non-road transport because road has vehicle
stock, turnover, drive-type, fuel-allocation, PHEV, and lifecycle-profile logic
that needs more detail than the aggregate transport model. Non-road transport
remains outside this repo.

Glossary:

| Term | Meaning |
|------|---------|
| `Module 1` | The road input/default package: stock, stock share, mileage, fuel economy, survival, vintage, sales-share, PHEV, and reconciliation assumptions. |
| `Static bundle` | Generated long CSV package under `road_model_inputs_interface/front-end/road-module1-static/` that the browser loads. It is generated UI data, not source data. |
| `Hand-off contract` | The canonical long Module 1 CSV columns and row keys passed from the interface to this model. |
| `Source merge` | Interface-side generation step that combines processed source files, manually filled rows, and supplemental source files using documented priority rules. |
| `T11` | Module 6 LEAP-ready long table used to write the LEAP import workbook. |
| `Current Accounts` | LEAP base-year scenario convention. In this model it is derived from the base-year slice of `Target`, not run as its own projection. |

## Related docs to read

Read these when the task touches the relevant area:

| Area | Doc |
|------|-----|
| Road model modeller guide | `docs/new model/road_transport_model_modeller_guide.md` |
| Road model methodology | `docs/new model/road_transport_model_methodology.md` |
| Interface/Module 1 contract | `../road_model_inputs_interface/docs/new model/multinode_road_module1_repo_guide.md` |
| Interface source update method | `../road_model_inputs_interface/back-end/data/road_model/UPDATE_METHOD.md` |
| LEAP export file format | `C:\Users\Work\.codex\AGENTS_LEAP_EXPORT.md` |
| Balance table conventions | `C:\Users\Work\.codex\AGENTS_BALANCE_TABLES.md` |

---

## Repos and their roles

| Repo | Role |
|------|------|
| `leap_road_model` | Model engine. Runs modules 1-6, produces T11 (LEAP-ready table), writes the LEAP import workbook. |
| `road_model_inputs_interface` | Plain HTML/JS + Tailwind CSS front-end + FastAPI back-end. Researchers edit module 1 assumptions here. Writes the module1 CSV and launches `road_workflow.py` as a subprocess. |
| `leap_transport` | Upstream source data, including `9th_macro_data.csv` and ESTO energy CSVs. It was originally written to translate 9th-edition energy projections and base-year data into the LEAP structure, including newer categories. This is useful for understanding transformations between 9th-edition data and LEAP. Treated as read-only by the model. Occasionally provides fallback reference exports and examples for structuring LEAP imports. |
| `leap_utilities` | Miscellaneous LEAP tooling. Occasionally provides fallback reference exports and examples for structuring LEAP imports. |

The interface and model repos are expected to be sibling directories:
```
github/
  leap_road_model/
  road_model_inputs_interface/
  leap_transport/
```

---

## How to work across both repos

Most useful work on the road model involves both `leap_road_model` and
`road_model_inputs_interface`. Treat them as one pipeline with clear ownership
boundaries, not as interchangeable codebases.

### Ownership boundaries

| Area | Owner repo | Notes |
|------|------------|-------|
| Module 1 source files, default generation, researcher UI rows | `road_model_inputs_interface` | Source files live under `back-end/data/road_model/`; generated UI bundle lives under `front-end/road-module1-static/`. |
| Module 1 CSVs consumed by the model | `leap_road_model` | Runtime inputs live under `input_data/module1_defaults/<version>/<economy>/`. These are written by the interface when the user runs the model. |
| Modules 2-6 model logic | `leap_road_model` | Keep downstream stock, sales, reconciliation, and LEAP handoff logic here. |
| LEAP import workbook writing | `leap_road_model` | Strict writer merges T11 against a LEAP reference export and preserves LEAP IDs/metadata. |
| Browser UI behavior | `road_model_inputs_interface` | Front-end editing, upload/download, input status, API calls, and static bundle loading belong here. |

### Before editing

1. Decide which side owns the behavior:
   - If the problem is a wrong default value shown in the browser, start in
     `road_model_inputs_interface/back-end/data/road_model/`.
   - If the problem is how a valid Module 1 row affects projection outputs, start
     in `leap_road_model/codebase/`.
   - If the problem is the saved CSV shape, check both the interface writer and
     `codebase/adapters/road_module1_defaults.py`.
2. Inspect both repos when the change crosses the hand-off. Do not assume the
   interface and model use the same naming convention without checking.
3. Keep generated files separate from source files in your mental model. If you
   update source defaults, regenerate the static bundle; do not hand-edit static
   CSVs unless the user explicitly asks for a one-off inspection/fix.

### Cross-repo paths to know

| Purpose | Path |
|---------|------|
| Interface source data | `../road_model_inputs_interface/back-end/data/road_model/` |
| Interface Module 1 static config | `../road_model_inputs_interface/back-end/data/road_model/config/` |
| Interface default workflow | `../road_model_inputs_interface/back-end/build_road_model_static_defaults.py` |
| Interface static bundle | `../road_model_inputs_interface/front-end/road-module1-static/` |
| Interface local model runner | `../road_model_inputs_interface/back-end/api/run_model_router.py` |
| Model Module 1 runtime inputs | `input_data/module1_defaults/` |
| Model workflow entrypoint | `codebase/road_workflow.py` |
| Model Module 1 adapter | `codebase/adapters/road_module1_defaults.py` |
| Model results | `results/<economy>/` |
| LEAP import workbook | `results/<economy>/module6/<economy>_leap_import.xlsx` |
| QA dashboard | `results/<economy>/diagnostics/dashboard/index.html` |

---

## Naming and file conventions

### Economy codes

The model uses canonical underscore economy codes such as `20_USA`. The
interface may expose compact codes such as `20USA` in static bundle filenames or
browser state. Normalize before comparing paths or keys.

Key examples:

| Context | Example |
|---------|---------|
| Model economy code | `20_USA` |
| Interface compact code | `20USA` |
| Interface static CSV | `front-end/road-module1-static/<version>/20USA.csv` |
| Model runtime CSV | `input_data/module1_defaults/<version>/20_USA/road_module1_values_20_USA.csv` |
| Model output workbook | `results/20_USA/module6/20_USA_leap_import.xlsx` |

The interface runner normalizes compact codes in
`back-end/api/run_model_router.py::_to_canonical_economy()`.

### Module 1 long-row columns

Canonical hand-off columns:

```text
Economy, Scenario, Branch Path, Variable, Year, Value, Scale, Units, Source, Comment, Input Status, Shown In Interface
```

`Input Status` is the default/researcher provenance marker. The
`leap_road_model` adapter still accepts older 9-column files without this field;
when it is absent, rows are treated as `provided` for backward compatibility.
`Shown In Interface` controls browser presentation only: `False` rows are hidden
from the editable UI but must still be preserved through download/upload and
sent to the model.

`Scale` is a LEAP-style display/import scale. Generated Module 1 long CSVs can
use compact values such as `Stock = 384.781, Scale = Millions` or
`Mileage = 40, Scale = Thousands`; the model expands these back to raw devices
or kilometres when loading inputs. Default scale labels are configured in
`road_model_inputs_interface/back-end/data/road_model/road_module1_default_parameters.json`.
`Scale` is optional for backward compatibility. When present, numeric LEAP-style
scales such as `Thousand`, `Thousands`, `Million`, `Millions`, `Billion`, and
`Billions` are applied as multipliers on input values before model calculations;
`%` is preserved as a display/import scale and is not converted to a fraction.

### Generated versus source files

Do not treat these as equivalent:

| Type | Path | Edit directly? |
|------|------|----------------|
| Source/default method files | `road_model_inputs_interface/back-end/data/road_model/` | Yes, when changing default data logic or inputs. |
| Interface generated backend outputs | `road_model_inputs_interface/back-end/outputs/road_module1_defaults/` | Usually no; regenerate from source. |
| Interface static bundle | `road_model_inputs_interface/front-end/road-module1-static/` | Usually no; regenerate from source. |
| Model runtime Module 1 CSV | `leap_road_model/input_data/module1_defaults/` | Sometimes; the interface writes here during local model runs. |
| Model results | `leap_road_model/results/` | No; these are run outputs. |

### Static bundle is the model hand-off source

For local interface-driven runs, the frontend static CSV is the authoritative
Module 1 package that gets handed to the model. The model-side runtime CSV under
`leap_road_model/input_data/module1_defaults/<version>/<economy>/` is just the
last CSV written by the interface runner. Treat it as a cache/output, not as a
separate source of truth.

Once a row is present in the static CSV, the browser and local runner should
preserve it losslessly through load, edit, download/upload, and run-model export.
Do not drop rows merely because they are not prominent in the main editor. Some
examples of less-visible rows that still must travel through the hand-off are:

- `PHEV Electric Driving Share` (Module 6 passenger/freight PHEV electricity/liquid split)
- `Survival Rate` (Module 4 turnover)
- `Vintage Profile Share` (Module 4 base-year vintage distribution)
- reconciliation weights/bounds, passenger saturation, and vehicle equivalent
  weights

The only row filtering should happen during static sync. The static contract is
defined by the combination of:

- `back-end/data/road_model/config/road_module1_static_contract.csv`
  (operator-maintained `(Branch Path, Variable)` row contract with
  `Current Accounts`, `Projected Scenario`, units, and interface visibility
  flags)
- `back-end/data/road_model/config/road_module1_static_fuel_branch_exclusions.csv`
  (economy-specific missing fuel branch exceptions, allowed only with reason
  `0 data for fuel in esto dataset`)
- the fuel-level completeness rule in `build_road_model_static_defaults.py`
  (fuel branches are globally required; every present fuel branch must have both
  `Mileage` and `Fuel Economy`; missing fuel branches must be justified by the
  ESTO-zero exclusion config)
- branch parsing/normalisation logic in `back-end/core/road_module1_defaults.py`

After static sync, all loaded static rows are part of the hand-off contract.

If `road_workflow.py` fails because Module 1 rows are missing, first check the
interface static CSV, for example:

```text
../road_model_inputs_interface/front-end/road-module1-static/<version>/20USA.csv
```

If the static CSV has the rows but the model runtime CSV does not, the runtime
CSV is stale or the browser/API hand-off dropped rows. Reload/run from the
interface, or overwrite the runtime CSV from the current static CSV for a
manual smoke check. Do not fix this by adding model fallbacks or hand-editing
`input_data/module1_defaults/` as if it were source.

---

## Routine workflows

### Run the model directly

Use this when checking model behavior independently of the browser UI:

```powershell
cd C:\Users\Work\github\leap_road_model
python codebase\road_workflow.py 20_USA --scenario Target --vis
```

Runtime defaults for `road_workflow.py` live in:

```text
codebase/config/workflow_defaults.yaml
```

This file controls workflow switches and paths, including the default scenario,
years, Module 1 package root/version, visualisations, CSV output, progress
printing, LEAP row diagnostics, module run/skip switches, future sales-share
auto-loading, Module 6 match tolerance, and LEAP import value scale export mode.
It does not provide model assumption fallbacks; stock, mileage, efficiency,
survival, PHEV, and reconciliation inputs still come from the generated Module 1
package.

CLI flags override the YAML for a single run. Useful examples:

```powershell
python codebase\road_workflow.py 15_PHL --no-vis --module1-defaults-dir ..\road_model_inputs_interface\back-end\outputs\road_module1_defaults --module1-defaults-version v2026_06_05_road_module1_sources
python codebase\road_workflow.py 20_USA --no-save-csv-outputs --no-auto-future-sales-shares --module6-match-tolerance 0.02
python codebase\road_workflow.py 20_USA --leap-import-raw-values
python codebase\road_workflow.py 20_USA --skip-m7
```

By default, LEAP import workbooks preserve numeric `Scale` labels where available
(`Stock = 384.781`, `Scale = Millions`). Use
`leap_import.export_values_in_raw_units: true` or `--leap-import-raw-values` to
write raw values instead (`Stock = 384781000`, blank numeric scale). `%` scale
labels are preserved for share rows in both modes.

Expected outputs:

- `results/20_USA/module6/T11_leap_ready.csv`
- `results/20_USA/module6/20_USA_leap_import.xlsx`
- `results/20_USA/diagnostics/dashboard/index.html` when visualisations are enabled

Do not run `--scenario "Current Accounts"`; Current Accounts is derived after
Target runs.

For notebook-style or offline checks, `scripts/offline_workflow.py` is the
friendlier entry point. It runs the same workflow functions without requiring the
website. By default it reads Module 1 defaults from the sibling interface repo:

```text
../road_model_inputs_interface/back-end/outputs/road_module1_defaults/
```

If that folder is unavailable, it falls back to this repo's legacy
`input_data/module1_defaults/`. Edit the constants at the bottom of
`scripts/offline_workflow.py` or call `run_offline()` / `run_offline_all()` from
a notebook.

### Run the model from the interface

Use this when checking the full researcher workflow:

1. Start the interface backend from `road_model_inputs_interface`:

```powershell
cd C:\Users\Work\github\road_model_inputs_interface
python back-end\run.py
```

2. Open or serve the front-end. The front-end calls:

```text
POST /api/v1/road-module1/run-model
GET  /api/v1/road-module1/run-model-stream?run_id=<run_id>
```

3. The backend writes:

```text
leap_road_model/input_data/module1_defaults/<version>/<economy>/road_module1_values_<economy>.csv
```

4. The backend launches:

```text
python leap_road_model/codebase/road_workflow.py <economy>
```

The runner assumes the repos are siblings unless `LEAP_ROAD_MODEL_DIR` is set.

### Dashboard HTML is generated at runtime — never cached

The QA dashboard pages under `results/<economy>/diagnostics/dashboard/` are **not
pre-generated static files**. They are produced fresh on every model run:

1. The interface backend launches `road_workflow.py` as a subprocess via
   `asyncio.create_subprocess_exec` in `run_model_router.py`.
2. `road_workflow.py` calls `write_module_pages(outputs, dashboard_dir)` near the
   end of the run, which writes new HTML files to
   `results/<economy>/diagnostics/dashboard/`.
3. The HTML served at `/road-results/<economy>/diagnostics/dashboard/module6.html`
   is always from the **last completed pipeline run** for that economy — not from
   a build step, not from a deploy artifact.

If the dashboard still shows old results after a code change, the economy has not
been re-run since the change. Re-run the economy through the interface (or directly
via `road_workflow.py`) to regenerate the dashboard. Do not claim the dashboard
reflects a code change until a fresh run has completed.

### Regenerate Module 1 build/static sync

Use this when source files in the interface have changed:

```powershell
cd C:\Users\Work\github\road_model_inputs_interface
python back-end\build_road_model_static_defaults.py
```

`build_road_model_static_defaults.py` is intentionally treated as the static
sync gate even though it still has many direct file references. If refactoring it,
keep behavior unchanged first: move paths and source lists behind named config or
small helper functions, then rerun the build and compare output row counts and
contract failures before changing source logic.

Then inspect:

- `back-end/outputs/road_module1_defaults/`
- `front-end/road-module1-static/`
- `front-end/road-module1-static/index.json`

The static bundle is generated UI data, not the source of truth. Source methods
belong in `back-end/data/road_model/UPDATE_METHOD.md`. If upstream
`leap_import_workbooks/` changed, run the separate source prep step first:
`back-end/scripts/prepare_road_source.py` reshapes the upstream workbook data
into `back-end/data/road_model/processed_source/`. Source prep is not part of
the regular build.

### Validate a cross-repo change

For a change that touches the hand-off between the interface and model, the
minimum useful check is:

1. Confirm the interface can write a long Module 1 CSV with the expected columns.
2. Confirm `load_module1_for_economy()` can load that CSV for the same economy and
   version.
3. Run `python codebase\road_workflow.py <economy> --scenario Target --no-vis`.
4. Inspect Module 6 outputs and any LEAP import warnings in
   `results/<economy>/module6/`.
5. If input provenance changed, open the dashboard and check the Module 1 source
   category display.

---

## Interface data loading and processing pattern

Use this pattern when changing `road_model_inputs_interface`. The core idea is:
data processing is an offline/package-generation concern; browser loading is a
simple read of an already-generated canonical package; researcher edits are an
overlay on top of that package.

### Named stages

| Stage | Name | Main files | Contract |
|-------|------|------------|----------|
| 1 | Source package | `back-end/data/road_model/` | Versioned, documented CSV/XLSX inputs. Missing required files should fail generation. |
| 2 | Source prep | `back-end/scripts/prepare_road_source.py` | Separate upstream-update step: reshape `leap_import_workbooks/` into `processed_source/`. Not part of the regular build. |
| 3 | Source merge | `back-end/core/road_module1_defaults.py` | Combine `processed_source/`, `manually_filled_rows/`, and `supplemental_source_files/` into one priority-ranked row pool. Missing required rows are a hard error. |
| 4 | Stock share derivation | `back-end/core/road_module1_defaults.py` | Compute `Stock Share` percentages from base-year `Stock` rows in the merged data. This is the only legitimate derived-row step. |
| 5 | Final override | `back-end/data/road_model/final_value_overrides/` | Optional final replacement of existing generated rows after source merge and stock share derivation. |
| 6 | Build | `back-end/outputs/road_module1_defaults/<version>/<economy>/` | Per-economy generated Module 1 package. This is a build output, not hand-authored source. |
| 7 | Static sync | `front-end/road-module1-static/<version>/<economy>.csv` | Filter to static-eligible variables, apply row-level interface visibility, and write the canonical long CSV used by the browser. |
| 8 | Browser working copy | `front-end/app.js` | Fetch `index.json` and CSV, parse long rows, convert to UI-wide rows for editing only. |
| 9 | Researcher overlay | `front-end/app.js` state maps and upload preview | Manual edits/uploads change existing row keys, validate values, and mark researcher-modified rows. |
| 10 | Export/model handoff | `convertRoadWideUiRowsToLongRows()` and `run_model_router.py` | Convert UI rows back to canonical long CSV and write to `leap_road_model/input_data/module1_defaults/`. |

### The simple explanation

The interface has one real row format at its boundary: the canonical long Module
1 CSV. Everything else is either source material used to generate that CSV, or a
temporary view model used so the browser can present the rows ergonomically.

```text
source package
  -> source prep (only when upstream LEAP import workbooks change)
  -> source merge (processed_source + manually_filled_rows + supplemental_source_files)
  -> stock share derivation
  -> final override
  -> build
  -> static sync
  -> browser working copy
  -> exported long CSV
  -> leap_road_model
```

The browser should not become a data-processing layer. It can validate,
compare row keys, collect edits, and convert between long rows and UI-wide rows,
but it should not decide default values, source priority, branch construction,
or supplemental-source merging.

### Rules for each layer

1. Source files under `back-end/data/road_model/` are the only source of truth
   for generated defaults. If a value changes because of a data update, update
   source files and `UPDATE_METHOD.md`, then regenerate.
2. `prepare_road_source.py` owns source prep from `leap_import_workbooks/` to
   `processed_source/`; run it only when the upstream export changes.
3. `road_module1_defaults.py` owns source merge, source priority, provenance,
   stock share derivation, final override application, and package generation.
   Treat `processed_source/`, `manually_filled_rows/`, and
   `supplemental_source_files/` as one ranked source pool, not as separate
   overlay phases.
4. `build_road_model_static_defaults.py` owns static sync and hard completeness
   checks against
   `back-end/data/road_model/config/road_module1_static_contract.csv`.
5. `build_road_model_static_defaults.py::write_frontend_static_bundle()` owns
   static sync from build outputs to static frontend CSVs.
6. `front-end/app.js` owns only UI loading, display, upload/download, edit
   tracking, and model-run API calls.
7. `run_model_router.py` is a bridge. It writes the browser's completed long
   rows into `leap_road_model`; it should not reinterpret the values.
8. `leap_road_model` owns all downstream modeling behavior after the Module 1
   CSV is written.

### Canonical versus internal formats

| Format | Where used | Purpose |
|--------|------------|---------|
| Source-specific CSV/XLSX | `back-end/data/road_model/` | Raw documented inputs. Shape can vary by source. |
| Internal wide schema | `MODULE1_INPUT_COLUMNS` in `road_module1_defaults.py` | Convenient Python processing shape with one column per model year. |
| Canonical long CSV | `MODULE1_LONG_COLUMNS` / `ROAD_MODULE1_LONG_COLUMNS` | Stable boundary format for generated static defaults, browser download/upload, and model handoff. |
| UI-wide rows | `normalizeRoadModule1RowsForUi()` in `app.js` | Browser-only editing shape. Do not persist as the formal package. |

When confused, prefer the canonical long CSV as the explanation and contract.
The internal wide schema exists because it is convenient for Python and UI
editing, not because it is the conceptual model.

### Validation gates

Changes to loading/processing should preserve these gates:

- Required source files exist before generation starts.
- Required source files have expected columns.
- Source priority conflicts at the same row/year are detected before output.
- Required rows absent from all source-merge folders fail the build. Do not
  reintroduce silent row-completion fallbacks.
- Placeholder defaults are rejected when strict source-backed generation is on.
- Frontend output only includes `(Branch Path, Variable)` pairs in
  `config/road_module1_static_contract.csv`.
- Every generated static `(Branch Path, Variable)` pair is present in
  `config/road_module1_static_contract.csv`.
- Every contract row with `Current Accounts = True` is present in each
  economy's Current Accounts output unless it is an allowed fuel-branch
  exclusion.
- Every contract row with `Projected Scenario = True` is present in each
  non-Current Accounts scenario output unless it is an allowed fuel-branch
  exclusion.
- Fuel branches are globally required. A missing fuel branch is valid only when
  ESTO road data in `leap_road_model/input_data/esto_transport_2000_2022.csv`
  has zero data for that economy/fuel and the exclusion reason is exactly
  `0 data for fuel in esto dataset`.
- Every fuel-level branch that is present has both `Mileage` and `Fuel Economy`.
- Uploaded researcher CSVs cannot introduce new row keys.

### Good change patterns

- Adding a new source-backed measure:
  update the appropriate source-merge folder or source prep logic, add the
  relevant `(Branch Path, Variable)` rows to
  `config/road_module1_static_contract.csv`, set scenario and visibility flags,
  regenerate, then test one economy through the model.
- Changing source priority:
  update `road_module1_source_priorities.csv` or the relevant priority logic,
  regenerate, and inspect the generated source/provenance fields.
- Changing browser presentation:
  keep the long CSV unchanged unless the actual handoff contract changed.
  Convert to/from the UI-wide view model at the edge.
- Changing the handoff contract:
  update Python `MODULE1_LONG_COLUMNS`, JS `ROAD_MODULE1_LONG_COLUMNS`, upload
  validation, and the `leap_road_model` adapter as needed, followed by a direct
  model check.

### Anti-patterns

- Do not load raw source workbooks directly in the browser.
- Do not make the backend generate defaults on each normal page load.
- Do not hand-edit `front-end/road-module1-static/` as if it were source data.
- Do not let uploads add rows; uploads fill existing template keys.
- Do not add a second JSON package format for the same data unless there is a
  concrete performance or deployment reason.
- Do not describe supplemental files as a separate overlay phase in docs or new
  code. They are part of source merge unless the code explicitly implements a
  later replacement step.
- Do not add row-completion helpers that silently invent required rows. Missing
  required rows should fail the build unless they are covered by the documented
  ESTO-zero fuel exclusion.

---

## ESTO road energy input

The road model's default ESTO energy source is the repo-local deployment file:

```text
input_data/esto_transport_2000_2022.csv
```

`codebase/adapters/esto_inputs.py` owns all access to this file. The default path
is `_DEFAULT_ESTO_CSV = leap_road_model/input_data/esto_transport_2000_2022.csv`.
Explicit function arguments and `ROAD_MODEL_ESTO_CSV` can override it for a
one-off run, but routine model runs should use the repo-local file so local,
interface, and deployment behavior match. This file is a snapshot of the ESTO transport energy data as of the last update. It is not automatically updated from the upstream source; update it with the `prepare_esto_for_deployment.py` script when the upstream ESTO file changes. ESTO is the APERC team responsible for creating the energy balances which are inputs to the energy outlook.

### Relationship to the upstream ESTO file

The source-of-record upstream file is normally:

```text
../leap_transport/data/00APEC_2024_low_with_subtotals.csv
../leap_utilities/data/00APEC_2025_low_with_subtotals.csv
etc...
```

Treat `leap_transport` and `leap_utilities` as read-only. When the upstream ESTO file changes, refresh
the road-model copy with:

```powershell
python scripts\prepare_esto_for_deployment.py
```

That script keeps detailed transport flows (`15.01`, `15.02`, etc.) and year
columns from 2000 onward, and writes `input_data/esto_transport_2000_2022.csv`.
It intentionally drops the top-level `15 Transport` aggregate because it is a
sum of detailed transport flows.

### Road-only filtering

The road model should only use ESTO `15.02 Road` rows. Do not use `15 Transport`
or other detailed transport flows such as air, rail, navigation, or pipeline for
road reconciliation.

Two adapter functions use the file:

| Function | Used by | ESTO rows used | Purpose |
|----------|---------|----------------|---------|
| `load_esto_road_energy()` | Module 3 | `flows == "15.02 Road"` and `products == "19 Total"` | Historical total road energy. Split into passenger/freight with the configured passenger share because ESTO does not provide that split. |
| `load_esto_fuel_totals()` | Module 6 | `flows == "15.02 Road"` and `is_subtotal == False` | Base-year road fuel totals by actual product/fuel for reconciliation. |

### Fuel mapping

Module 6 does not infer diesel from total road energy. It reads product-level
`15.02 Road` rows and maps `products` to model fuel names using the latest
`config/leap_mappings*.xlsx` workbook, sheet `fuel_product_final_proposed`. This may be updated from time to time using the file of the same name from `leap_utilities`.

Examples:

| ESTO product | Model fuel |
|--------------|------------|
| `07.01 Motor gasoline` | `Motor gasoline` |
| `07.07 Gas/diesel oil` | `Gas and diesel oil` |
| `16.06 Biodiesel` | `Biodiesel` |
| `16.05 Biogasoline` | `Biogasoline` |
| `17 Electricity` | `Electricity` |

Alternative fuels follow the fossil fuel family they substitute for in Module 6
fuel allocation:

- `Biodiesel` can go into diesel-capable branches (`Gas and diesel oil` family).
- `Biogasoline` can go into gasoline-capable branches (`Motor gasoline` family).
- `Efuel` can go into ordinary liquid-fuel ICE-style branches unless a narrower
  reviewed rule exists.

Alternative fuels are spread so they make up a constant proportion of the
corresponding original fuel family's use across eligible branches.

PHEV and EREV are treated the same in Module 6: EREV is modeled like a more
efficient PHEV. Their liquid side is gasoline-family only for both passenger and
freight branches: `Motor gasoline`, `Biogasoline`, and `Efuel` are allowed;
`Gas and diesel oil` and `Biodiesel` are not.

After mapping, `load_esto_fuel_totals()` groups by model fuel and returns:

```text
fuel, energy_pj
```

Those per-fuel road totals are what Module 6 reconciles against. If diesel or
gasoline results look wrong, first inspect this adapter output before changing
Module 6 allocation logic.

Quick inspection example:

```powershell
python - <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, str(Path("codebase").resolve()))
from adapters.esto_inputs import load_esto_fuel_totals
print(load_esto_fuel_totals("20_USA", base_year=2022).to_string(index=False))
PY
```

### Common mistakes

- Do not read `15 Transport` for road model reconciliation; it includes non-road
  transport energy.
- Do not use `products == "19 Total"` for Module 6 fuel reconciliation; that row
  is useful for total road energy but cannot distinguish diesel from gasoline.
- Do not bypass `load_esto_fuel_mapping()` with ad hoc string matching. Use the
  mapping workbook so naming stays consistent with LEAP and the import writer.
- Do not edit `input_data/esto_transport_2000_2022.csv` by hand. Regenerate it
  from the upstream source with `scripts/prepare_esto_for_deployment.py`.
- respect the subtotal flag. Only non-subtotal rows should be mapped to fuels and reconciled against. Subtotals are useful for diagnostics but should not be treated as reconciliation targets or we risk double-counting energy.
---

## Module pipeline

Brief summary of each module's role:

- **Module 1** — Loads base-year road assumptions (stock, mileage, efficiency, survival curves, passenger/freight PHEV utilisation rates, reconciliation bounds). Source: module1 CSV written by the interface.
- **Module 2** — Builds the base-year branch table by cross-joining vehicle taxonomy with module 1 data. Produces T4.
- **Module 3** — Projects passenger stock with the motorisation envelope and freight stock with GDP elasticity, including Module 1 growth/elasticity adjustment controls. Produces T5.
- **Module 4** — Derives sales, retirements, and vintage distributions from stock targets. Produces T6.
- **Module 5** — Prepares vehicle sales shares (drive-type mix over time). Uses future sales share inputs if provided; otherwise falls back to a flat projection from base-year shares.
- **Module 6** — Reconciles fuel energy against ESTO observed totals (base year only), computes device shares, and assembles T11 (the LEAP-ready table). See *Module 6 reconciliation* below.

### T-table lineage and naming

The `T*` names are workflow tables, not always one-to-one module numbers. Use
these names when tracing outputs, diagnostics, and dashboard pages:

| Table | Producer | Main CSV path | Meaning |
|-------|----------|---------------|---------|
| `T4_base_year_branches` | Module 2 | `results/<economy>/module2/T4_base_year_branches.csv` | Base-year technology/fuel branch table built from Module 1 assumptions and road taxonomy. Carries stock, mileage, efficiency, branch path, source flags, and dimensions. |
| `T5_stock_targets` | Module 3 | `results/<economy>/module3/T5_stock_targets.csv` | Vehicle-type stock target paths by year. Includes passenger motorisation diagnostics and freight GDP-elasticity diagnostics. |
| `T6_sales_turnover` | Module 4 | `results/<economy>/module4/T6_sales_turnover.csv` | Sales, surviving stock, retirements, target stock, and stock-flow diagnostics by vehicle type/year. |
| `T6v_vintage_profiles` | Module 4 | `results/<economy>/module4/T6v_vintage_profiles.csv` | Base-year vintage/age distribution used by Module 4 turnover. |
| `T7_sales_shares` | Module 5 | Usually in memory/diagnostics; may be saved when enabled | Base-year sales shares by vehicle/drive bucket. |
| `T7f_future_shares` | Module 5 | Usually in memory/diagnostics; may be saved when enabled | Future sales-share trajectories from explicit inputs, Module 1 projected rows, or fallback logic. |
| `T8_fuel_allocation` | Module 6 | `results/<economy>/module6/T8_fuel_allocation.csv` | Provisional allocation of ESTO fuel totals to eligible road branches before scalar reconciliation. |
| `T9_reconciliation_scalars` | Module 6 | `results/<economy>/module6/T9_reconciliation_scalars.csv` | Branch/fuel reconciliation scalars and adjusted base-year stock, mileage, and efficiency. |
| `T10_device_shares` | Module 6 | `results/<economy>/module6/T10_device_shares.csv` | LEAP Device Share rows derived after reconciliation. |
| `T11_leap_ready` | Module 6 | `results/<economy>/module6/T11_leap_ready.csv` | LEAP-ready long table of variables, values, branch paths, years, scenarios, units, and source metadata. This is the source for the strict LEAP import workbook. |
| `T12_reconciliation_diagnostics` | Module 6 | `results/<economy>/module6/T12_reconciliation_diagnostics.csv` | Fuel-level reconciliation status, residual gaps, ECFs, scalar-bound status, and validation flags. |
| `T12_phev_utilisation_diagnostics` | Module 6 | `results/<economy>/module6/T12_phev_utilisation_diagnostics.csv` | PHEV electric/liquid split diagnostics and back-calculated utilisation checks. |
| `T13_mirror_outputs` | Module 7 | `results/<economy>/module7/T13_mirror_outputs.csv` | Optional Python mirror of LEAP-side stock, vehicle-km, and energy calculations for QA. |
| `T13_mirror_fuel_outputs` | Module 7 | `results/<economy>/module7/T13_mirror_fuel_outputs.csv` | Optional fuel-level mirror outputs and comparisons. |

### Pre- and post-reconciliation T5/T6 naming

Conceptually, `T5`, `T6`, and `T6v` are the pre-reconciliation stock and
turnover outputs produced by Modules 3 and 4. During a full run, Module 6 may
then re-anchor stock trajectories to reconciled base-year stock and rerun Module
4. When that happens, `road_workflow.py` saves the original tables as:

- `T5_pre_reconciliation`
- `T6_pre_reconciliation`
- `T6v_pre_reconciliation`

and replaces the active workflow outputs with the adjusted tables:

- `T5` / `T5_post_reconciliation`
- `T6` / `T6_post_reconciliation`
- `T6v` / `T6v_post_reconciliation`

This naming is about runtime timing, not model concept. If no Module 6 stock
re-anchoring happened, plain `T5`, `T6`, and `T6v` are already
pre-reconciliation. Dashboard rule: `module3.html` should show the original
pre-reconciliation stock/turnover view; `module3_post_reconciliation.html`
should show only charts whose values changed after re-anchoring.

---

## Scenarios

This is the most error-prone area. Read carefully. It may be updated from time to time as we add new scenarios or adjust the handling.

### Which scenarios exist

| Label | Meaning | Run or derived? |
|-------|---------|-----------------|
| `Target`/`TGT` | Current run scenario. At present this is seeded from the 9th-edition Target scenario and is a placeholder until the 10th-edition policy scenario is settled. | **Run** |
| `Current Accounts`/`CA` | Base-year (2022) stock/sales values only. Scalar LEAP expressions. A LEAP convention; normally just called the base year. | **Derived** from the base-year slice of `Target`; never run separately. |
| `Reference`/`REF` | 9th-edition macro/reference scenario label. Still present in `9th_macro_data.csv` and old Module 1 CSVs. Not currently present in the LEAP reference export used by the road model. | Not currently run. May be reintroduced later if the Outlook needs a no-policy-change counterfactual. |

The base year is the same in 9th-edition `Target` and `Reference` source data.
Do not describe `Reference` as permanently dead; it is simply outside the
current model run/export contract.

### How Current Accounts is produced

After module 6 completes, `_extract_current_accounts_base_year()` in `road_workflow.py`
takes the base-year (2022) slice of the Target rows in T11 and relabels them
`scenario = "Current Accounts"`. These rows produce **scalar** LEAP expressions
(not `Data(...)` time series) because `to_leap_expression()` in
`adapters/leap_expressions.py` returns a bare number for a single-point series.

**Never run a separate "Current Accounts" scenario through the model.**
Current Accounts in LEAP holds base-year calibration constants; the projection
is entirely under Target.

### Macro data and scenarios

`9th_macro_data.csv` (population, GDP) has `Reference` and `Target` scenarios.
The model runs for `Target` and loads `Target` macro data via `load_population()`
and `load_gdp()` in `adapters/esto_inputs.py`.

`MACRO_SCENARIO_FALLBACK` in `esto_inputs.py` is an empty dict by default.
Extend it if a new scenario is added before dedicated macro data is available,
e.g. `{"My New Scenario": "Target"}` to borrow Target macro data temporarily.

Current macro data is still based on the 9th edition. When 10th-edition macro
data is available, update the macro source and rerun scenario checks before
treating 10th-edition scenario outputs as final.

### "Reference" in old module1 CSVs

Pre-built module1 defaults files (in `road_model_inputs_interface/back-end/outputs/`)
still carry `Scenario = "Reference"`. This is handled gracefully: in `road_workflow.py`
around line 532, the workflow detects that Target is missing from the loaded module1
data and replicates the Reference rows under the Target label before passing them to
module 2. Base-year assumptions are scenario-agnostic so this is safe.

**Do not rename these files or strip the Reference label from them** — the replication
logic handles it automatically.

### LEAP reference export and scenario names

The LEAP reference export files (`transport_leap_export_combined_*.xlsx`) contain:
- `Current Accounts` — scalar expressions (base year only)
- `Target` — full `Data(2022, ..., 2060, ...)` time series

The `build_leap_import_tables()` function in `adapters/leap_import_writer.py`
merges T11 against this reference on `(Branch Path, Variable, Scenario)`.
T11 must therefore use exactly these scenario labels — `"Target"` and
`"Current Accounts"` — for the merge to succeed.

If `Reference` or another scenario is added to the LEAP model, regenerate the
`transport_leap_export_combined_*.xlsx` reference exports with matching scenario
rows before expecting the import writer to preserve that scenario. The likely
source is `leap_transport`, but that repo may need cleanup before it can be used
as a repeatable export-generation tool.

---

## Data flow: interface -> model -> LEAP

```
Researcher edits assumptions in the front-end
        |
POST /api/v1/road-module1/run-model
        |
run_model_router.py: _write_module1_csv()
  Writes rows to:
  leap_road_model/input_data/module1_defaults/<version>/<economy>/
        |
Subprocess: python road_workflow.py <economy> [--scenario Target]
        |
Modules 1-6 run; T11 produced
        |
_validate_t11_base_year_consistency()  <- warns if base year differs across scenarios
_extract_current_accounts_base_year()  <- appends CA rows (base year slice of Target)
        |
write_leap_import_workbook()
  Merges T11 with reference export on (Branch Path, Variable, Scenario)
  Writes <economy>_leap_import.xlsx
        |
Researcher imports workbook into LEAP
```

The workflow also writes user-facing follow-up files:

- `results/<economy>/lifecycle_profiles/` contains LEAP-compatible lifecycle
  profile workbooks, a manifest, and `<economy>_lifecycle_profiles.zip`.
- `results/<economy>/module6/<economy>_module1_reimport_reconciled.csv` is a
  canonical Module 1 CSV with reconciled base-year stock, stock share, mileage,
  and fuel economy values. It is designed for upload back into the interface
  using existing row keys.

### LEAP import workbook structure

The LEAP import workbook is not just a user-facing report. It is a strict import
package that must match LEAP's expected export/import shape so LEAP can identify
the correct branch, variable, scenario, and region for every expression.

The strict writer lives in `codebase/adapters/leap_import_writer.py`. It loads a
reference LEAP export, filters to road branches, and merges T11 on:

```text
Branch Path, Variable, Scenario
```

The reference export supplies LEAP's internal IDs and metadata. T11 supplies the
new model values. The resulting workbook has metadata rows above the header,
with the real column header on row index 2 when read with pandas.

Required `LEAP` sheet columns, in order:

```text
BranchID, VariableID, ScenarioID, RegionID,
Branch Path, Variable, Scenario, Region,
Scale, Units, Per..., Expression,
Level 1, Level 2, Level 3, Level 4, Level 5, Level 6, Level 7, Level 8...
```

Column meanings:

| Column group | Purpose |
|--------------|---------|
| `BranchID`, `VariableID`, `ScenarioID`, `RegionID` | LEAP internal identifiers copied from the reference export. Do not invent or reorder these. |
| `Branch Path`, `Variable`, `Scenario`, `Region` | Human-readable logical row key for the LEAP value being imported. |
| `Scale`, `Units`, `Per...` | LEAP display/import metadata. `Scale` may be preserved for compact values such as `Millions` or blanked when exporting raw values. |
| `Expression` | The value LEAP imports, either a scalar such as `384.781` or a time-series expression such as `Data(2022, ..., 2060, ...)`. |
| `Level 1` to `Level 8...` | Branch hierarchy columns derived from `Branch Path` by splitting on `\`. Unused levels are blank. |

The `FOR_VIEWING` sheet carries the same identifying columns, including the
Level columns, but replaces `Expression` with individual year columns for easier
inspection. It is diagnostic/human-readable; `LEAP` is the import sheet.

Keep the Level columns synchronized with `Branch Path`. For example:

```text
Branch Path = Demand\Passenger road\LPVs\BEV\Electricity
Level 1 = Demand
Level 2 = Passenger road
Level 3 = LPVs
Level 4 = BEV
Level 5 = Electricity
Level 6..Level 8... = blank
```

Do not hand-edit these columns separately from `Branch Path`. If branch naming
changes, regenerate them from the branch path in the writer. This mirrors the
LEAP export convention used in `C:\Users\Work\github\leap_utilities\data\full model export.xlsx`.

Update the reference export whenever the LEAP branch or variable structure
changes. New branches and variables need valid `BranchID` and `VariableID`
values from the target LEAP area; do not invent IDs in Python. For most economy
areas, `RegionID` is expected to remain `1` because each area has one modeled
region. Still verify the `Region` name from the reference export matches the
economy being imported, because LEAP may use names such as `United States of
America`, `Philippines`, or `The Philippines` differently from the model's
canonical economy code.

### Interface scenario priority

`TRANSPORT_LEAP_EXPORT_SCENARIO_PRIORITY` in
`road_model_inputs_interface/back-end/core/road_module1_defaults.py`
controls which scenario the interface prefers when overlaying LEAP transport
export values into the module1 defaults. Currently `["Current Accounts", "Target"]`.
The new LEAP export files do not have a `Reference` scenario, so `Reference`
must not appear in this list unless regenerated reference exports actually
include `Reference` rows. If `Reference` is reintroduced, add it here in the
intended priority order and verify the source overlay still selects base-year
values correctly.

---

## Module 6 reconciliation

The reconciliation (ECF — energy correction factor) adjusts stock, mileage, and
efficiency scalars so that the model's implied base-year fuel energy matches the
ESTO observed totals.

**It operates on the base year only.** Reconciliation scalars are computed from
base-year branch data (T4) and written to T11 at `year = base_year`. Projection
years in T11 carry only Sales and Sales Share from modules 4–5 — not
reconciliation-adjusted stock/mileage/efficiency.

This is intentional: the reconciliation anchors LEAP to observed data in 2022;
future years evolve through the sales/turnover model.

---

## Key invariants

These must always be true. Violations indicate a bug.

1. **Base year values are scenario-agnostic.** Stock, mileage, and efficiency in
   2022 come from observations and should be identical across all scenarios in T11.
   Checked by `_validate_t11_base_year_consistency()`.

2. **Current Accounts rows contain only the base year.** If CA rows span multiple
   years, `to_leap_expression()` will produce `Data(...)` instead of a scalar,
   which does not match the LEAP reference format.

3. **Module 6 reconciliation is base year only.** Do not extend it to future years
   without careful review — the projection is driven by the sales/turnover model,
   not by re-reconciling against ESTO at each future year.

4. **T11 scenario labels must match the LEAP reference export exactly.**
   Currently `"Target"` and `"Current Accounts"`. A mismatch causes
   `build_leap_import_tables()` to raise `ValueError: No T11 rows matched`.

---

## Common mistakes to avoid

- **Adding "Reference" back casually as a LEAP scenario.** `Reference` is not in
  the current LEAP reference export contract. It is fine to reintroduce later,
  but only with matching macro data, Module 1 scenario handling, LEAP reference
  export rows, and scenario-priority updates.

- **Running the model with `--scenario "Current Accounts"`.** CA is a post-processing
  step, not a model run. Running it as a scenario produces a full projection under CA
  which then writes `Data(...)` expressions instead of scalars into the LEAP import.

- **Changing `to_leap_expression()` to always return `Data(...)`.** Single-point
  series must return a bare scalar for CA rows to match LEAP's expected format.

- **Removing the module1 scenario replication logic** (road_workflow.py ~line 532).
  Old module1 CSVs with `Reference` rows rely on it. Without it, Target scenarios
  get no base-year data.

- **Changing `TRANSPORT_LEAP_EXPORT_SCENARIO_PRIORITY` to include `"Reference"`
  before the reference exports include it.** The lookup would find nothing and
  fall through to Target, which hides the fact that the export contract was not
  updated. If `Reference` is added back, add it to the priority list as part of
  that same scenario change.

---

## Module 1 input-status classification

### How values move from the interface to the dashboard

1. The interface front-end loads default data from
   `road_model_inputs_interface/front-end/road-module1-static/{version}/{economy}.csv`.
2. When the user saves to model, the interface writes a
   `road_module1_values_{economy}.csv` into `input_data/module1_defaults/<version>/<economy>/`.
3. `load_module1_for_economy()` -> `_normalise_long_module1_df()` in
   `codebase/adapters/road_module1_defaults.py` reads the `Input Status` column
   and stores it as `input_source`.
4. `_module1_source_category()` in `codebase/diagnostics/plotly_dashboard.py`
   maps `input_source` to one of three dashboard categories.

### The `Input Status` / `input_source` vocabulary

| Value | Meaning | Dashboard category |
| --- | --- | --- |
| `"default"` | Value came from static bundle, untouched by user | Default value |
| `"provided"` | Legacy synonym for `"default"` — used before terminology changed | Default value |
| `"default_filled"` | Explicit default marker (older format) | Default value |
| `"researcher"` | Value explicitly entered or imported by user via the interface | Researcher-provided |
| `"researcher_import"` | Same intent as `"researcher"` | Researcher-provided |
| `"researcher_provided"` | Same intent as `"researcher"` | Researcher-provided |

`source_type` or `source_name` containing `"transport_leap_export"` also maps to
Researcher-provided regardless of `input_source`.

### Why `"provided"` == default

The interface previously used `"provided"` as its term for all static-bundle values.
The terminology was later changed to `"default"` for clarity. Both are treated
identically in `_module1_source_category()` for backward compatibility with
already-generated CSV files that still carry `"provided"`.

**Do not treat `"provided"` as researcher-provided — it is a default marker.**

### Where the tracking happens (interface side)

- `ROAD_MODULE1_LONG_COLUMNS` in `app.js` includes `'Input Status'`.
- `convertRoadWideUiRowsToLongRows()` emits `'Input Status': row._inputStatus || 'default'`.
- `_inputStatus` is set to `'researcher'` on a row when:
  - A manual UI override is applied (`buildRoadModule1CompletedRowsForCheckpoint`).
  - A CSV import changes the row's value (`previewRoadModule1UploadedRows`).
- Rows loaded from the static bundle with no user edit carry no `_inputStatus`
  and therefore export as `'default'`.

---

## Adding a new scenario

1. Decide if it is a **run scenario** (needs macro data, runs modules 1–6) or a
   **derived scenario** (extracted from an existing run, like Current Accounts).
2. If run: add it to `9th_macro_data.csv` or add it to `MACRO_SCENARIO_FALLBACK`
   with a temporary surrogate.
3. Confirm the LEAP reference export includes the new scenario name, otherwise
   `build_leap_import_tables()` will silently exclude all its rows.
4. Add a row to the scenario table in this file.
5. Update Module 1 generation in `road_model_inputs_interface`:
   - add scenario rows to source data or source-prep outputs;
   - update `road_module1_static_contract.csv` flags if the scenario changes
     which variables must be present;
   - check `TRANSPORT_LEAP_EXPORT_SCENARIO_PRIORITY` if LEAP export overlays are
     used for the new scenario;
   - regenerate `back-end/outputs/road_module1_defaults/` and
     `front-end/road-module1-static/`.
6. Update the browser/API hand-off only if the canonical long CSV contract
   changes. Scenario additions should usually preserve the same columns.
7. Run at least one direct model check and one interface-driven hand-off check:
   `python codebase\road_workflow.py <economy> --scenario <scenario> --no-vis`,
   then run the interface endpoint and confirm the runtime CSV and T11 carry the
   expected scenario labels.
8. Inspect `results/<economy>/module6/` for LEAP import merge warnings,
   scenario row counts, and base-year consistency diagnostics.


## Mermaid diagrams

# Road Module 1 simplified workflow
This diagram is intended for high-level documentation such as the README. It abstracts away the source prep and build steps, showing only the major data handoffs and the final output to Modules 2–7. This is intended for understanding only the Module 1 workflow, not the full model workflow, which is covered in a separate diagram.

C:\Users\Work\github\road_model_inputs_interface\docs\new model\Road Module 1 workflow diagram.png

flowchart LR
  subgraph SRC["Source package<br/>road_model_inputs_interface/back-end/data/road_model"]
    S1["Processed source<br/>processed_source/"]
    S2["Supplemental files<br/>supplemental_source_files/"]
    S3["Manual fills<br/>manually_filled_rows/"]
    S4["Final overrides<br/>final_value_overrides/"]
    S5["Config + contract<br/>static_contract · parameters · priorities"]
  end

  BUILD["Build Module 1 defaults<br/>build_road_model_static_defaults.py"]
  OUT["Versioned Module 1 package<br/>back-end/outputs/road_module1_defaults/VERSION/economy/<br/>road_module1_values_ECONOMY.csv"]
  STATIC["Static browser bundle<br/>front-end/road-module1-static/VERSION/economy.csv<br/>+ index.json"]

  subgraph UI["Browser UI / static site"]
    VIEW["View defaults<br/>filter · inspect sources · validate"]
    EDIT["Researcher overlay<br/>edit Value · Comment · Source only"]
    CSV["Download / reupload<br/>same canonical long CSV"]
  end

  HANDOFF["Model handoff<br/>canonical long CSV package"]
  MODEL["leap_road_model<br/>Modules 2-7"]

  SRC --> BUILD --> OUT --> STATIC --> VIEW --> EDIT --> CSV --> HANDOFF --> MODEL
  OUT -. "optional backend can serve same rows" .-> VIEW
  EDIT -. "Run Model button<br/>optional backend" .-> MODEL

  classDef source fill:#D3455B,color:#ffffff,stroke:#D3455B;
  classDef build fill:#BD34D1,color:#ffffff,stroke:#BD34D1;
  classDef package fill:#2C88D9,color:#ffffff,stroke:#2C88D9;
  classDef ui fill:#F7C325,color:#334155,stroke:#F7C325;
  classDef model fill:#1AAE9F,color:#ffffff,stroke:#1AAE9F;

  class S1,S2,S3,S4,S5 source;
  class BUILD build;
  class OUT,STATIC,HANDOFF package;
  class VIEW,EDIT,CSV ui;
  class MODEL model;

# Road Module 1 defaults build workflow with derivation steps
This diagram expands the source prep and build steps to show the derivation steps that produce the final module1 defaults from the various source folders. 

C:\Users\Work\github\road_model_inputs_interface\docs\new model\Road Module 1-7 simplified interface workflow.png
flowchart TD
  A[Near term LEAP source workbook]
  B[Optional source prep script]
  C[Processed source files]
  D[Supplemental source files]
  E[Manual fill files]
  F[Source priority file]
  G[Final override files]
  H[Default parameters]
  I[Static contract CSV]
  J[Fuel branch exclusion CSV]

  K[Source merge]
  L[Derive base year stock shares]
  M[Apply final overrides]
  N[Build canonical long rows]
  O[Validate against static contract]
  P[Write backend Module 1 package]
  Q[Sync static browser bundle]
  R[Browser fetches index and CSV]
  S[Browser displays editable working copy]
  T[Export canonical long CSV]

  A --> B
  B --> C

  C --> K
  D --> K
  E --> K
  F --> K

  K --> L
  L --> M
  G --> M

  M --> N
  H --> N

  N --> O
  I --> O
  J --> O

  O --> P
  P --> Q
  Q --> R
  R --> S
  S --> T

# Road Module 1 interface to Modules 2-7 workflow

C:\Users\Work\github\leap_road_model\docs\new model\Road transport model — researcher detail.png

This diagram is intended to be used within the leap_road_model repo for modules 2-7 to explain how Module 1 data flows into the rest of the model and produces the LEAP import workbook and dashboard outputs. It is not a full workflow diagram for Modules 2–7, which are covered in a separate diagram.
flowchart LR
  subgraph M1REPO["road_model_inputs_interface"]
    SOURCES["Source/config files<br/>back-end/data/road_model/"]
    BUILDER["Module 1 builder<br/>build_road_model_static_defaults.py"]
    M1PKG["Generated Module 1 package<br/>back-end/outputs/road_module1_defaults/VERSION/economy/<br/>road_module1_values_ECONOMY.csv"]
    STATIC["Static UI bundle<br/>front-end/road-module1-static/VERSION/economy.csv"]
    UI["Browser UI<br/>review · edit · export · optional run"]
  end

  subgraph LRM["leap_road_model"]
    WF["road_workflow.py<br/>loads Module 1 package"]
    LEGACY["legacy input_data/module1_defaults/<br/>wide packages / backfill only"]
    MACRO["Non-Module 1 inputs<br/>population · GDP · ESTO energy · configs"]
    M2["Module 2<br/>T4 base-year branches"]
    M3["Module 3<br/>T5 stock targets"]
    M4["Module 4<br/>T6 sales + turnover<br/>T6v profiles"]
    M5["Module 5<br/>T7/T7f sales shares"]
    M6["Module 6<br/>T8-T12 reconciliation<br/>T11 LEAP-ready table"]
    M7["Module 7<br/>T13 optional QA mirror"]
    XLSX["LEAP import workbook<br/>+ lifecycle profile workbooks / ZIP"]
    DASH["Diagnostics + dashboards<br/>results/economy/module*/"]
  end

  LEAP["LEAP desktop<br/>official projection platform"]
  LEAPOUT["LEAP results export<br/>for QA / dashboard comparison"]

  SOURCES --> BUILDER --> M1PKG --> STATIC --> UI
  M1PKG -->|"preferred sibling-repo package"| WF
  UI -. "optional backend run<br/>same long CSV rows" .-> WF
  LEGACY -. "backward compatibility only" .-> WF
  MACRO --> WF
  WF --> M2 --> M3 --> M4 --> M6 --> XLSX --> LEAP --> LEAPOUT
  M2 --> M5 --> M6
  M1PKG -. "survival · vintage · stock share · sales share · PHEV · reconciliation settings" .-> WF
  M6 --> DASH
  M4 --> XLSX
  LEAPOUT -.-> M7
  M6 -.-> M7
  M7 --> DASH

  classDef repo fill:#788896,color:#ffffff,stroke:#788896;
  classDef module fill:#2C88D9,color:#ffffff,stroke:#2C88D9;
  classDef m6 fill:#1AAE9F,color:#ffffff,stroke:#1AAE9F;
  classDef ui fill:#F7C325,color:#334155,stroke:#F7C325;
  classDef ext fill:#BD34D1,color:#ffffff,stroke:#BD34D1;
  classDef legacy fill:#ffffff,color:#334155,stroke:#788896,stroke-dasharray: 4 4;

  class SOURCES,BUILDER,M1PKG,STATIC,MACRO,XLSX,DASH repo;
  class M2,M3,M4,M5,M7 module;
  class M6 m6;
  class UI ui;
  class LEAP,LEAPOUT ext;
  class LEGACY legacy;

# Road transport model — quick view
This diagram is a high-level overview of the full road transport model workflow, from Module 1 data prep through Modules 2–7, LEAP import, and dashboard outputs. It is intended for quick orientation to the overall workflow and major data handoffs, not for detailed understanding of any particular step. For detailed workflows, see the separate diagrams for Module 1 and for the interface-to-LEAP workflow.

C:\Users\Work\github\leap_road_model\docs\new model\Road transport model — quick view.png
flowchart TB
  subgraph SEQ["1. Main model sequence"]
    direction LR
    M1["Module 1 package<br/>canonical long CSV<br/>from interface repo"]
    M2["M2<br/>Base-year branches<br/>T4"]
    M3["M3<br/>Stock targets<br/>T5"]
    M4["M4<br/>Sales and turnover<br/>T6/T6v"]
    M5["M5<br/>Sales shares<br/>T7/T7f"]
    M6["M6<br/>Reconciliation and LEAP package<br/>T8-T12 and T11"]
    LEAP["LEAP<br/>official projection"]
    M7["M7<br/>optional QA mirror<br/>T13"]

    M1 --> M2 --> M3 --> M4 --> M6 --> LEAP
    M2 --> M5 --> M6
    M6 -. "base-year stock re-anchor<br/>post-reconciliation T5/T6" .-> M3
    LEAP -. "results comparison" .-> M7
    M6 -. "mirror inputs" .-> M7
  end

  subgraph RECON["2. Module 6 reconciliation in one line"]
    direction LR
    RIN["T4, T6, T7/T7f<br/>plus ESTO fuel totals<br/>plus Module 1 settings"]
    INIT["Initial branch energy<br/>stock x mileage / efficiency"]
    ELEC["BEV/PHEV electricity<br/>first"]
    LIQ["PHEV liquid subtraction<br/>then fuel allocation"]
    SCALE["Stock, mileage, efficiency scalars<br/>weighted and bounded"]
    DEVICE["Device Shares"]
    T11["T11 LEAP-ready output"]

    RIN --> INIT --> ELEC --> LIQ --> SCALE --> DEVICE --> T11
  end

  NOTE["T4, T5, T6, T7, and T11 are stable handoff and diagnostic table names"]

  classDef input fill:#788896,color:#ffffff,stroke:#788896;
  classDef module fill:#2C88D9,color:#ffffff,stroke:#2C88D9;
  classDef recon fill:#1AAE9F,color:#ffffff,stroke:#1AAE9F;
  classDef leap fill:#BD34D1,color:#ffffff,stroke:#BD34D1;
  classDef note fill:#F7C325,color:#334155,stroke:#F7C325;

  class M1,RIN input;
  class M2,M3,M4,M5,M7 module;
  class M6,INIT,ELEC,LIQ,SCALE,DEVICE,T11 recon;
  class LEAP leap;
  class NOTE note;

## Road transport model — researcher detail
This diagram is an expanded version of the "quick view" diagram, showing more detail on the data handoffs, outputs, and scripts involved in each step of the workflow. It is intended for researchers who want to understand how the model works in more depth, including where to find outputs and how to run checks. For a high-level overview, see the separate "quick view" diagram.

C:\Users\Work\github\leap_road_model\docs\new model\Road transport model — researcher detail.png
flowchart TD
  A[Module 1 package]
  B[ESTO road fuel totals]
  C[Population and GDP]
  D[Road workflow config]

  E[Module 2 builds base year branch table T4]

  F[Module 3 passenger stock targets]
  G[Module 3 freight stock targets]
  H[Output T5 stock targets]

  I[Module 4 survival and vintage profiles]
  J[Module 4 sales retirements and turnover]
  K[Output T6 sales turnover and T6v profiles]

  L[Module 5 base year sales shares]
  M[Module 5 future sales shares]
  N[Output T7 and T7f sales shares]

  O[Module 6 initial branch energy]
  P[Reconcile BEV and PHEV electricity]
  Q[Subtract PHEV liquid fuel]
  R[Allocate remaining ESTO fuel]
  S[Apply stock mileage and efficiency scalars]
  T[Calculate Device Shares]
  U[Validate fuel totals bounds shares and PHEV split]
  V[Outputs T8 T9 T10 T11 T12 and T12 PHEV]

  W[Optional post reconciliation re anchor]
  X[LEAP import workbook and lifecycle profiles]
  Y[LEAP official projection]
  Z[LEAP results export]
  AA[Module 7 optional QA mirror]
  AB[Dashboards and diagnostics]

  A --> E
  D --> E

  E --> F
  C --> F
  B --> F

  E --> G
  C --> G

  F --> H
  G --> H

  A --> I
  I --> J
  H --> J
  J --> K

  E --> L
  A --> L
  L --> N

  A --> M
  M --> N

  K --> O
  N --> O
  O --> P
  P --> Q
  Q --> R
  B --> R
  R --> S
  A --> S
  S --> T
  T --> U
  U --> V

  V --> W
  W --> J

  V --> X
  K --> X
  X --> Y
  Y --> Z
  Z --> AA

  V --> AA
  V --> AB
  AA --> AB

## One large end-to-end diagram:
flowchart LR
  subgraph A["A. Source preparation<br/>road_model_inputs_interface"]
    A1["Near-term source workbook<br/>leap_transport export"]
    A2["Processed + supplemental + manual + override sources"]
    A3["Contract/config<br/>static_contract · priorities · parameters · exclusions"]
    A4["Build defaults<br/>source merge → stock share derivation → override → contract checks"]
    A5["Versioned Module 1 package<br/>canonical long CSV per economy"]
    A6["Static UI bundle<br/>same long-row format"]
  end

  subgraph B["B. Researcher review interface"]
    B1["Browser loads static CSV"]
    B2["Researcher edits allowed fields<br/>Value · Comment · Source"]
    B3["Upload/download validation<br/>no new keys · no changed key columns"]
    B4["Export/model-run long CSV"]
  end

  subgraph C["C. Python road workflow<br/>leap_road_model"]
    C0["Load Module 1 package<br/>+ population/GDP/ESTO/config"]
    C2["M2 T4<br/>base-year branches"]
    C3["M3 T5<br/>passenger/freight stock targets"]
    C4["M4 T6/T6v<br/>sales · retirements · lifecycle profiles"]
    C5["M5 T7/T7f<br/>sales shares"]
    C6["M6 T8-T12 + T11<br/>fuel allocation · reconciliation · Device Shares · LEAP-ready rows"]
    C7["Post-reconciliation re-anchor<br/>optional T5/T6 pre/post outputs"]
  end

  subgraph D["D. LEAP handoff and official projection"]
    D1["LEAP import workbook<br/>strict row structure + IDs where available"]
    D2["Lifecycle profile workbooks/ZIP"]
    D3["LEAP desktop import"]
    D4["Researchers edit future scenario assumptions in LEAP"]
    D5["LEAP official road results"]
  end

  subgraph E["E. QA and communication outputs"]
    E1["Module CSV diagnostics<br/>results/economy/module*/"]
    E2["Dashboard HTML<br/>pre/post reconciliation views"]
    E3["M7 optional Python mirror<br/>T13 comparison outputs"]
    E4["LEAP results export<br/>comparison input"]
  end

  A1 --> A2
  A2 --> A4
  A3 --> A4
  A4 --> A5 --> A6 --> B1 --> B2 --> B3 --> B4
  A5 --> C0
  B4 -. "optional backend run" .-> C0
  C0 --> C2 --> C3 --> C4 --> C6 --> D1 --> D3 --> D4 --> D5
  C2 --> C5 --> C6
  C6 --> C7
  C7 -. "rerun turnover if enabled" .-> C4
  C4 --> D2 --> D3
  C6 --> E1
  C7 --> E2
  C6 --> E2
  D5 --> E4 --> E3
  C6 --> E3 --> E2

  classDef source fill:#D3455B,color:#ffffff,stroke:#D3455B;
  classDef ui fill:#F7C325,color:#334155,stroke:#F7C325;
  classDef module fill:#2C88D9,color:#ffffff,stroke:#2C88D9;
  classDef recon fill:#1AAE9F,color:#ffffff,stroke:#1AAE9F;
  classDef leap fill:#BD34D1,color:#ffffff,stroke:#BD34D1;
  classDef qa fill:#788896,color:#ffffff,stroke:#788896;

  class A1,A2,A3,A4,A5,A6 source;
  class B1,B2,B3,B4 ui;
  class C0,C2,C3,C4,C5 module;
  class C6,C7 recon;
  class D1,D2,D3,D4,D5 leap;
  class E1,E2,E3,E4 qa;



# NEW END TO END DIAGRAM
https://whimsical.com/aperc/end-to-end-road-model-workflow-compact-rectangular-layout-9eMVA11SFdbjYCzCgW4tzp

C:\Users\Work\github\leap_road_model\docs\new model\End-to-end road model workflow 8062026.png

flowchart TB

  %% ---------- ROW 1 ----------
  subgraph ROW1[" "]
    direction LR

    subgraph A["A. Source preparation<br/>road_model_inputs_interface"]
      direction LR
      A1["Near-term source workbook<br/>leap_transport export"]
      A2["Processed + supplemental + manual + override sources"]
      A3["Contract/config<br/>static_contract · priorities · parameters · exclusions"]
      A4["Build defaults<br/>source merge → stock share derivation → override → contract checks"]
      A5["Versioned Module 1 package<br/>canonical long CSV per economy"]
      A6["Static UI bundle<br/>same long-row format"]

      A1 --> A2
      A2 --> A4
      A3 --> A4
      A4 --> A5
      A5 --> A6
    end

    subgraph B["B. Researcher review interface"]
      direction LR
      B1["Browser loads static CSV"]
      B2["Researcher edits allowed fields<br/>Value · Comment · Source"]
      B3["Upload/download validation<br/>no new keys · no changed key columns"]
      B4["Export/model-run long CSV"]

      B1 --> B2 --> B3 --> B4
    end
  end

  %% ---------- ROW 2 ----------
  subgraph ROW2[" "]
    direction LR

    subgraph C["C. Python road workflow<br/>leap_road_model"]
      direction LR
      C0["Load Module 1 package<br/>+ population/GDP/ESTO/config"]
      C2["M2 T4<br/>base-year branches"]
      C3["M3 T5<br/>passenger/freight stock targets"]
      C4["M4 T6/T6v<br/>sales · retirements · lifecycle profiles"]
      C5["M5 T7/T7f<br/>sales shares"]
      C6["M6 T8-T12 + T11<br/>fuel allocation · reconciliation · Device Shares · LEAP-ready rows"]
      C7["Post-reconciliation re-anchor<br/>optional T5/T6 pre/post outputs"]

      C0 --> C2
      C2 --> C3
      C3 --> C4
      C4 --> C6
      C2 --> C5
      C5 --> C6
      C6 --> C7
      C7 -. "rerun turnover if enabled" .-> C4
    end

    subgraph D["D. LEAP handoff and official projection"]
      direction LR
      D1["LEAP import workbook<br/>strict row structure + IDs where available"]
      D2["Lifecycle profile workbooks/ZIP"]
      D3["LEAP desktop import"]
      D4["Researchers edit future scenario assumptions in LEAP"]
      D5["LEAP official road results"]

      D1 --> D3
      D2 --> D3
      D3 --> D4 --> D5
    end
  end

  %% ---------- ROW 3 ----------
  subgraph E["E. QA and communication outputs"]
    direction LR
    E1["Module CSV diagnostics<br/>results/economy/module*/"]
    E2["Dashboard HTML<br/>pre/post reconciliation views"]
    E3["M7 optional Python mirror<br/>T13 comparison outputs"]
    E4["LEAP results export<br/>comparison input"]

    E4 --> E3 --> E2
  end

  %% ---------- CROSS-SECTION LINKS ----------
  A6 --> B1
  A5 --> C0
  B4 -. "optional backend run" .-> C0

  C6 --> D1
  C4 --> D2

  C6 --> E1
  C6 --> E2
  C7 --> E2
  C6 --> E3
  D5 --> E4

  %% ---------- STYLES ----------
  classDef source fill:#D3455B,color:#ffffff,stroke:#D3455B;
  classDef ui fill:#F7C325,color:#334155,stroke:#F7C325;
  classDef module fill:#2C88D9,color:#ffffff,stroke:#2C88D9;
  classDef recon fill:#1AAE9F,color:#ffffff,stroke:#1AAE9F;
  classDef leap fill:#BD34D1,color:#ffffff,stroke:#BD34D1;
  classDef qa fill:#788896,color:#ffffff,stroke:#788896;
  classDef row fill:transparent,stroke:transparent,color:transparent;

  class A1,A2,A3,A4,A5,A6 source;
  class B1,B2,B3,B4 ui;
  class C0,C2,C3,C4,C5 module;
  class C6,C7 recon;
  class D1,D2,D3,D4,D5 leap;
  class E1,E2,E3,E4 qa;
  class ROW1,ROW2 row;
