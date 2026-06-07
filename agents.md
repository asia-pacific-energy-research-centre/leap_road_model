# AGENTS.md - Road Model and Interface Guide for AI Assistants

This file documents the system from an agentic perspective: invariants, non-obvious
design decisions, deprecated patterns, and data flow. Read this before touching
scenarios, LEAP import logic, Module 1 defaults, or the interface hand-off.

---

## Related docs to read

Read these when the task touches the relevant area:

| Area | Doc |
|------|-----|
| Road model design | `docs/new model/road_transport_model_detailed.md` |
| Simplified road model overview | `docs/new model/road_transport_model_simplified.md` |
| Interface/Module 1 contract | `../road_model_inputs_interface/docs/new model/multinode_road_module1_repo_guide.md` |
| Interface source update method | `../road_model_inputs_interface/back-end/data/road_model/UPDATE_METHOD.md` |
| LEAP export file format | `C:\Users\Work\.codex\AGENTS_LEAP_EXPORT.md` |
| Balance table conventions | `C:\Users\Work\.codex\AGENTS_BALANCE_TABLES.md` |

---

## Repos and their roles

| Repo | Role |
|------|------|
| `leap_road_model` | Model engine. Runs modules 1-6, produces T11 (LEAP-ready table), writes the LEAP import workbook. |
| `road_model_inputs_interface` | React front-end + FastAPI back-end. Researchers edit module 1 assumptions here. Writes the module1 CSV and launches `road_workflow.py` as a subprocess. |
| `leap_transport` | Upstream source data - `9th_macro_data.csv`, ESTO energy CSVs. Treated as read-only by the model. |
| `leap_utilities` | Miscellaneous LEAP tooling. Occasionally provides a fallback reference export. |

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
| Interface default workflow | `../road_model_inputs_interface/back-end/road_module1_defaults_workflow.py` |
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

Core canonical hand-off columns:

```text
Economy, Scenario, Branch Path, Variable, Year, Value, Units, Source, Comment
```

Browser/model-run exports add provenance/status columns such as `Input Status`.
The `leap_road_model` adapter accepts both shapes: if `Input Status` is absent,
it treats the row as `provided`; if present, it maps it to `input_source`.
Preserve these optional columns unless there is a specific reason to drop them;
the dashboard uses that metadata to classify values.

### Generated versus source files

Do not treat these as equivalent:

| Type | Path | Edit directly? |
|------|------|----------------|
| Source/default method files | `road_model_inputs_interface/back-end/data/road_model/` | Yes, when changing default data logic or inputs. |
| Interface generated backend outputs | `road_model_inputs_interface/back-end/outputs/road_module1_defaults/` | Usually no; regenerate from source. |
| Interface static bundle | `road_model_inputs_interface/front-end/road-module1-static/` | Usually no; regenerate from source. |
| Model runtime Module 1 CSV | `leap_road_model/input_data/module1_defaults/` | Sometimes; the interface writes here during local model runs. |
| Model results | `leap_road_model/results/` | No; these are run outputs. |

---

## Routine workflows

### Run the model directly

Use this when checking model behavior independently of the browser UI:

```powershell
cd C:\Users\Work\github\leap_road_model
python codebase\road_workflow.py 20_USA --scenario Target --vis
```

Expected outputs:

- `results/20_USA/module6/T11_leap_ready.csv`
- `results/20_USA/module6/20_USA_leap_import.xlsx`
- `results/20_USA/diagnostics/dashboard/index.html` when visualisations are enabled

Do not run `--scenario "Current Accounts"`; Current Accounts is derived after
Target runs.

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

### Regenerate Module 1 defaults/static bundle

Use this when source files in the interface have changed:

```powershell
cd C:\Users\Work\github\road_model_inputs_interface
python back-end\road_module1_defaults_workflow.py
```

Then inspect:

- `back-end/outputs/road_module1_defaults/`
- `front-end/road-module1-static/`
- `front-end/road-module1-static/index.json`

The static bundle is generated UI data, not the source of truth. Source methods
belong in `back-end/data/road_model/UPDATE_METHOD.md`.

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
| 2 | Source loader/normalizer | `back-end/core/road_module1_defaults.py` | Read source rows, normalize labels, pick priority-ranked values, and convert to the internal wide schema. |
| 3 | Source overlays | `overlay_*` functions in `road_module1_defaults.py` | Add or replace specific measures from supplemental sources with explicit provenance. |
| 4 | Generated default package | `back-end/outputs/road_module1_defaults/<version>/<economy>/` | Per-economy generated Module 1 package. This is a build output, not hand-authored source. |
| 5 | Frontend static bundle | `front-end/road-module1-static/<version>/<economy>.csv` | Filter to frontend-visible variables and write the canonical long CSV used by the browser. |
| 6 | Browser load/view model | `front-end/app.js` | Fetch `index.json` and CSV, parse long rows, convert to UI-wide rows for editing only. |
| 7 | Researcher overlay | `front-end/app.js` state maps and upload preview | Manual edits/uploads change values on existing row keys and mark `Input Status = researcher`. |
| 8 | Export/model handoff | `convertRoadWideUiRowsToLongRows()` and `run_model_router.py` | Convert UI rows back to canonical long CSV and write to `leap_road_model/input_data/module1_defaults/`. |

### The simple explanation

The interface has one real row format at its boundary: the canonical long Module
1 CSV. Everything else is either source material used to generate that CSV, or a
temporary view model used so the browser can present the rows ergonomically.

```text
source files
  -> normalized internal wide rows
  -> generated per-economy long CSV package
  -> static bundle long CSV
  -> browser UI-wide working copy
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
2. `road_module1_defaults.py` owns source loading, normalization, source
   priority, overlays, provenance, and package generation.
3. `build_road_model_static_defaults.py` owns the frontend-visible measure
   contract (`FRONTEND_MEASURES`) and hard completeness checks.
4. `road_module1_defaults_workflow.py::write_frontend_static_bundle()` owns
   conversion from generated backend outputs to static frontend CSVs.
5. `front-end/app.js` owns only UI loading, display, upload/download, edit
   tracking, and model-run API calls.
6. `run_model_router.py` is a bridge. It writes the browser's completed long
   rows into `leap_road_model`; it should not reinterpret the values.
7. `leap_road_model` owns all downstream modeling behavior after the Module 1
   CSV is written.

### Canonical versus internal formats

| Format | Where used | Purpose |
|--------|------------|---------|
| Source-specific CSV/XLSX | `back-end/data/road_model/` | Raw documented inputs. Shape can vary by source. |
| Internal wide schema | `MODULE1_INPUT_COLUMNS` in `road_module1_defaults.py` | Convenient Python processing shape with one column per model year. |
| Core canonical long CSV | `MODULE1_LONG_COLUMNS` | Stable 9-column boundary format for generated static defaults. |
| Long CSV with provenance | `ROAD_MODULE1_LONG_COLUMNS` | Browser export/model-run format; extends the core long CSV with `Input Status`. |
| UI-wide rows | `normalizeRoadModule1RowsForUi()` in `app.js` | Browser-only editing shape. Do not persist as the formal package. |

When confused, prefer the core long CSV plus optional provenance columns as the
explanation and contract. The internal wide schema exists because it is
convenient for Python and UI editing, not because it is the conceptual model.

### Validation gates

Changes to loading/processing should preserve these gates:

- Required source files exist before generation starts.
- Required source files have expected columns.
- Source priority conflicts at the same row/year are detected before output.
- Placeholder defaults are rejected when strict source-backed generation is on.
- Frontend output only includes variables in `FRONTEND_MEASURES`.
- Every economy includes all fixed required `(Branch Path, Variable)` pairs from
  `road_module1_required_rows.csv`.
- Every fuel-level branch exposed to the frontend has both `Mileage` and
  `Fuel Economy`.
- Uploaded researcher CSVs cannot introduce new row keys.

### Good change patterns

- Adding a new source-backed measure:
  update source files, add/adjust loader or overlay logic, add it to
  `FRONTEND_MEASURES` if researchers should see it, update required rows if it
  is structurally required, regenerate, then test one economy through the model.
- Changing source priority:
  update `road_module1_source_priorities.csv` or the relevant priority logic,
  regenerate, and inspect the generated source/provenance fields.
- Changing browser presentation:
  keep the long CSV unchanged unless the actual handoff contract changed.
  Convert to/from the UI-wide view model at the edge.
- Changing the handoff contract:
  decide whether the field is part of the core schema or an optional provenance
  extension. Then update Python `MODULE1_LONG_COLUMNS`, JS
  `ROAD_MODULE1_LONG_COLUMNS`, upload validation, and the `leap_road_model`
  adapter as needed, followed by a direct model check.

### Anti-patterns

- Do not load raw source workbooks directly in the browser.
- Do not make the backend generate defaults on each normal page load.
- Do not hand-edit `front-end/road-module1-static/` as if it were source data.
- Do not let uploads add rows; uploads fill existing template keys.
- Do not add a second JSON package format for the same data unless there is a
  concrete performance or deployment reason.
- Do not hide source priority or value replacement inside generic helper names;
  loader/overlay functions should make the source and precedence obvious.

---

## Module pipeline

<!-- TODO: translate the PNG flow diagrams here. One sentence per module:
     what goes in, what comes out, what can go wrong.
     Diagrams are in: [add path to diagrams folder]
-->

Brief summary of each module's role:

- **Module 1** — Loads base-year road assumptions (stock, mileage, efficiency, survival curves, PHEV utilisation rate, reconciliation bounds). Source: module1 CSV written by the interface.
- **Module 2** — Builds the base-year branch table by cross-joining vehicle taxonomy with module 1 data. Produces T4.
- **Module 3** — Projects stock targets to the final year using population/GDP saturation curves. Produces T3.
- **Module 4** — Derives sales, retirements, and vintage distributions from stock targets. Produces T6.
- **Module 5** — Prepares vehicle sales shares (drive-type mix over time). Uses future sales share inputs if provided; otherwise falls back to a flat projection from base-year shares.
- **Module 6** — Reconciles fuel energy against ESTO observed totals (base year only), computes device shares, and assembles T11 (the LEAP-ready table). See *Module 6 reconciliation* below.

---

## Scenarios

This is the most error-prone area. Read carefully.

### Which scenarios exist

| Label | Meaning | Run or derived? |
|-------|---------|-----------------|
| `Target` | Full projection 2022–2060 under policy assumptions. The primary model scenario. | **Run** |
| `Current Accounts` | Base-year (2022) stock/sales values only. Scalar LEAP expressions. | **Derived** from Target — never run separately. |
| `Reference` | Deprecated APEC 9th-edition macro scenario label. Still present in `9th_macro_data.csv` and old module1 CSVs. Not a LEAP scenario in the current model. | Dead — do not add back. |

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

### Interface scenario priority

`TRANSPORT_LEAP_EXPORT_SCENARIO_PRIORITY` in
`road_model_inputs_interface/back-end/core/road_module1_defaults.py`
controls which scenario the interface prefers when overlaying LEAP transport
export values into the module1 defaults. Currently `["Current Accounts", "Target"]`.
The new LEAP export files do not have a `Reference` scenario, so `Reference`
must not appear in this list.

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

- **Adding "Reference" back as a LEAP scenario.** It is a legacy APEC macro label.
  The LEAP model uses `Current Accounts` and `Target`. The road model runs for
  `Target`; CA is derived.

- **Running the model with `--scenario "Current Accounts"`.** CA is a post-processing
  step, not a model run. Running it as a scenario produces a full projection under CA
  which then writes `Data(...)` expressions instead of scalars into the LEAP import.

- **Changing `to_leap_expression()` to always return `Data(...)`.** Single-point
  series must return a bare scalar for CA rows to match LEAP's expected format.

- **Removing the module1 scenario replication logic** (road_workflow.py ~line 532).
  Old module1 CSVs with `Reference` rows rely on it. Without it, Target scenarios
  get no base-year data.

- **Changing `TRANSPORT_LEAP_EXPORT_SCENARIO_PRIORITY` to include `"Reference"`.** The
  current LEAP export files do not have a Reference scenario. The lookup would silently
  find nothing and fall through to Target anyway, but it signals wrong intent.

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
