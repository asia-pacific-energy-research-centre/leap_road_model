# Pending changes

A running list of documented changes and improvements to make across both repos.

---

## leap_road_model

### LEAP import workbook writer (new file: `codebase/adapters/leap_import_writer.py`)

The road model's final product is a LEAP import workbook — an Excel file that can be loaded directly into LEAP to populate all road branch values. LEAP's import format is strict: if the file is not structured exactly right, LEAP will silently import nothing or import the wrong rows. The current workbook writer in `codebase/adapters/leap_workbook.py` has several structural problems that would cause this, and the merging process that attaches LEAP's internal ID columns is defined but never called.

This should be a new, self-contained file (`codebase/adapters/leap_import_writer.py`) so it is easy to understand and test as its own process, separate from Module 6's reconciliation logic.

#### What LEAP's import format requires

The reference for this is `C:\Users\Work\github\leap_utilities\data\full model export.xlsx`. Reading that file with `header=2` (i.e. the header is on row 3 in Excel) gives:

- **Two metadata rows before the header** — row 0 is blank except for an "Area:" label and the area name; row 1 is blank. These must be written first or LEAP will misread the header position.
- **Exact column order** — LEAP reads columns positionally. The required order is:
  `BranchID, VariableID, ScenarioID, RegionID, Branch Path, Variable, Scenario, Region, Scale, Units, Per..., Expression`
  followed by optional `Level 1` ... `Level 8` columns.
- **ID columns are mandatory** — BranchID, VariableID, ScenarioID, and RegionID must be populated with the integer IDs from the LEAP area file. LEAP uses these to match rows, not just Branch Path + Variable. If they are missing or wrong, the import fails silently.
- **Expression format** — Values go in the `Expression` column as `Data(year, value, year, value, ...)` strings. The `build_data_expression` function in `codebase/adapters/leap_expressions.py` already does this correctly.
- **Two sheets** — the workbook needs a `LEAP` sheet (compact, with Expression column) and a `FOR_VIEWING` sheet (same rows, pivoted to year columns for human reading).

#### The current problems in `leap_workbook.py`

1. **Wrong branch path prefixes** — `_ROAD_BRANCH_PREFIXES` includes `Demand\Transport passenger road` which does not exist in the actual LEAP area. The correct prefixes are `Demand\Passenger road` and `Demand\Freight road`. This means `load_leap_id_lookup` is filtering out all road rows.
2. **Metadata rows not written** — `write_leap_import_workbook` writes the header directly at row 0. LEAP expects it at row 2 (0-indexed), with metadata rows at rows 0–1.
3. **ID columns not in output** — `_build_leap_sheet` builds rows with Branch Path, Variable, Scenario, ScenarioID, Region, Units, Expression — but not BranchID, VariableID, or RegionID. These are required.
4. **ID merge never called from the writer** — `validate_coverage_against_leap_ids` exists but is a standalone function. The writer never calls it or uses the IDs from the reference export.
5. **Column order not enforced** — The LEAP sheet columns are assembled in arbitrary order; LEAP needs them in the fixed sequence above.

#### How the new writer should work

**Reference file:** For now copy a version of `C:\Users\Work\github\leap_utilities\data\full model export.xlsx` over to this repo, filtering to rows whose Branch Path starts with `Demand\Passenger road` or `Demand\Freight road`. This is a USA-only export but the BranchID/VariableID/ScenarioID values are what matter — RegionID is economy-specific but will always be 1 anyway. Just amke sure the Region column that is recorded has the right region written into it.

**Step 1 — Load the reference ID table** from the full model export. The join key is `(Branch Path, Variable, Scenario)`. Store: BranchID, VariableID, ScenarioID, Scale, Units, Per... alongside it. This is the lookup that tells us what ID to assign each row.

**Step 2 — Take T11_leap_ready** tidy DataFrame (economy × scenario × year × branch_path × variable × value). Convert it from long format to wide Data() expressions: one row per `(Branch Path, Variable, Scenario)` with an `Expression` column.

**Step 3 — Left-join the model output against the reference ID table** on `(Branch Path, Variable, Scenario)`. Rows in the model output that have no match in the reference are flagged as **warnings** ("model produced a row LEAP does not recognise — will be excluded from import"). Rows in the reference that have no match in the model output are also flagged as **warnings** ("LEAP expects this branch but the model has not produced a value for it — it will be blank in LEAP").

These warnings should be returned as a structured list so the website can show them to the user — not just logged.

**Step 4 — Write the Excel file** with the correct structure:

```text
Row 0:  [blank, blank, blank, blank, "Area:", <area_name>, "Ver:", <version>, ...]
Row 1:  [blank, ...]
Row 2:  BranchID  VariableID  ScenarioID  RegionID  Branch Path  Variable  Scenario  Region  Scale  Units  Per...  Expression
Row 3+: data rows
```

Set RegionID from a per-economy lookup (the RegionID in the reference export is USA-specific; each economy in the APEC model has its own RegionID which will need to be resolved separately — for now use the reference value as a placeholder and flag it).

The `LEAP` sheet gets the Expression column. The `FOR_VIEWING` sheet pivots to year columns. Both sheets share the same metadata rows and column structure.

#### What to copy from existing code

- `build_data_expression` from `codebase/adapters/leap_expressions.py` — already correct.
- `_convert_units_for_leap` from `leap_workbook.py` — the km/GJ → MJ/100km conversion is correct.
- The `load_leap_id_lookup` function concept from `leap_workbook.py` — but fix the branch path prefixes before using it.
- The `scale_expression` and `expression_to_series` utilities from `leap_expressions.py` for any expression manipulation needed.

#### What to leave in `leap_workbook.py`

Keep `load_leap_import_workbook_as_template` and `load_leap_id_lookup` as utilities — they are useful for validation. Fix the `_ROAD_BRANCH_PREFIXES` constant (remove `Demand\Transport passenger road`, keep `Demand\Passenger road` and `Demand\Freight road`). The `write_leap_import_workbook` function can remain as a stub or be removed once the new writer is in place.

### Freight stock diagnostics (dashboard)

The freight stock section is meant to be "highly diagnostic" — reviewers need to see what data and assumptions drove each economy's elasticity, not just the final stock projection. Currently this information only appears in logs.

The goal is a dedicated freight diagnostics view in the dashboard. The code changes (structured return from `estimate_freight_elasticity`, diagnostic columns in the Module 3 output dataframe) are minimal plumbing to get the data to the dashboard — the real work is the dashboard itself.

**Dashboard view — what the reviewer should see per economy:**

- A plain-English flag note: e.g. "Elasticity clamped from 2.1 to 1.5 — review" or "Insufficient data — default elasticity used."
- A summary table showing: economy, raw elasticity, final (clamped) elasticity, energy growth rate, GDP growth rate, and data quality status.
- A line chart of historical freight road energy and GDP over the lookback window, with annotated growth rates and the resulting elasticity — so the reviewer can see the trend that produced the estimate.
- A line chart of projected freight stock under the current elasticity, with sensitivity bands showing how the projection shifts if the elasticity is adjusted up or down (e.g. ±0.3), and a comparison to the 9th edition projection and historical freight stock where available.

**Minimum code changes to support this:**

1. `estimate_freight_elasticity` returns a dict (elasticity, raw_elasticity, elasticity_clamped, energy_growth_rate, gdp_growth_rate, data_source) instead of a float.
2. `project_freight_stocks` passes those diagnostics through in its return dict.
3. `run_module3` writes the diagnostic fields as columns on the output dataframe so they travel to the dashboard preprocessing step.

Once the diagnostics are visible in the dashboard and we understand what patterns are common, we can decide whether to add elasticity adjustment inputs to Module 1.

### Module 4: stock-falling-faster-than-target not recorded (Module 4 + dashboard)

The stock projection works by calculating how many new vehicle sales are needed each year to hit the target stock level. To do that, it first counts how many vehicles from previous years are still on the road (they age out gradually over time based on survival curves). If the number of vehicles still on the road already exceeds the target — because the target is falling, or because retirements were slower than expected in previous years — then no new sales are needed and the existing fleet is quietly scaled down to match the target.

This scaling is a meaningful event: it means the fleet is shrinking naturally without needing new sales, which is a useful signal for understanding how fast vehicles are turning over in that economy. Currently it is never recorded anywhere — there is no flag in the output and no note in the logs.

**Changes needed:**

1. **Record it in the Module 4 output table** — add a `stock_above_target` flag (true/false) and a `scale_factor_applied` column (the ratio used to bring the existing fleet down to the target). Update the schema in `codebase/schemas/tables.py`.

2. **Set the flag in the code** — in `project_cohort_stock` in `module4_sales_turnover.py`, write the flag and scale factor when the existing fleet exceeds the target for a given year.

3. **Surface in the dashboard** — include these events in the validation flags table so a reviewer can see at a glance which economies and years had a naturally shrinking fleet, and by how much.

---

## road_model_inputs_interface

### CSV reupload validation in the researcher UI

The module1 guide (section 7) specifies that reupload should be strict:

- match uploaded rows to existing rows by key;
- apply changes only to editable value/comment/source columns;
- raise an error for new keys or modified key columns;
- keep a summary of changed values for review;
- partial uploads allowed only when they contain a clear subset of existing keys.

The current static-bundle UI has no reupload validation logic — it serves the CSV but does not enforce these rules when a researcher reuploads a filled template.

**Changes needed:**

1. **Add client-side reupload validation** — on CSV upload, parse and check that all key columns (`Economy`, `Scenario`, `Branch Path`, `Variable`, `Year`) are present and match existing rows. Reject uploads that add new keys or mutate key columns.
2. **Show a diff summary before accepting** — highlight changed `Value`, `Comment`, and `Source` cells so the researcher can review before confirming.
3. **Block key-column edits** — make key columns read-only in the UI table (already implied by "prevent key columns from being edited" in the guide).

---

### Vehicle-type stock split inputs (Module 1 + Module 3)

**Why this matters:** The passenger motorisation envelope depends on the mix of LPVs, buses, and motorcycles because buses and motorcycles are converted to LPV-equivalents before the envelope is calculated. If a researcher only sets total passenger stock and leaves the vehicle-type split to be decided later inside LEAP, the LPV-equivalent assumptions have already locked in a structure that LEAP cannot undo. The same logic applies to freight: the truck/LCV split shapes the stock projection. Both splits need to be decided upfront, not during LEAP modelling.

**What the researcher provides:** The stock split expressed as fractions of the total physical vehicle count. If base-year stocks are LPVs = 6,000 / Buses = 1,000 / Motorcycles = 3,000, the split is 60% / 10% / 30%. These are real stock proportions — one can always be derived from the other. The researcher never deals with LPV-equivalents or any weighted version; that conversion is an internal step in `leap_road_model` that the researcher does not see.

**Proposed input approach:**

- Show the researcher a table with rows for each vehicle type and columns for the base year and two target years (defaulting to 2040 and 2060, but editable). The base-year column is read-only and auto-calculated from the base-year stock counts already entered — it updates automatically if those stock counts change. The target-year columns are editable.
- Linearly interpolate between the base-year split and each target-year split to produce annual ratios. For years beyond the last target, hold the final target ratio constant.
- The table should show the ratios summing to 1 within each group (passenger: LPV + bus + moto = 1; freight: truck + LCV = 1) and flag if they do not.

**Changes needed in `road_model_inputs_interface`:**

1. **Design the input UI** — a table showing base year (read-only, auto-derived from stock counts) and two editable target years, with rows for each vehicle type within a transport type. Placed near the stock count inputs so the connection is obvious.

2. **Add to the Module 1 CSV contract** — the target-year ratios appear as rows in the long-column output (Variable = something like `passenger_type_share_LPVs`, Year = target year, Value = ratio). The base-year ratio is implicit in the stock counts already exported and does not need a separate row.

**Changes needed in `leap_road_model`** (direct downstream consequence of the above):

1. **Passenger — interpolate annual ratios from base year to target years in `road_workflow.py`.**
   Module 1 supplies sparse target-year ratios. The workflow derives the base-year ratio from base-year stock counts, then linearly interpolates to each target year and holds the last target ratio constant beyond that. This produces a full annual `pd.Series` per vehicle type which is passed to `run_module3` via the `vehicle_type_shares` parameter.

2. **Passenger — convert the physical stock ratios to LPV-equivalent capacity shares before passing to Module 3.**
   Module 3's `vehicle_type_shares` parameter works in LPV-equivalents, not physical vehicle counts, because the motorisation envelope is calculated in LPV-equivalents. A stock ratio of "30% motorcycles" does not mean 30% of LPV-equivalents — motorcycles weigh ~0.8 LPV-equiv each, so their weighted share is lower. The conversion is:

   ```text
   capacity_share[vt] = physical_ratio[vt] × weight[vt] / Σ(physical_ratio[i] × weight[i])
   ```

   This conversion happens in `road_workflow.py` after the interpolation step and before `run_module3` is called. The researcher always works in physical stock ratios; this conversion is internal.

3. **Freight — restructure `project_freight_stocks` to support an explicit truck/LCV split.**
   Currently trucks and LCVs are projected independently using the same GDP elasticity applied to their individual base stocks. There is no mechanism for a user-specified truck/LCV ratio. To support it, restructure the function: project a single total freight stock first (GDP-elasticity on the aggregate), then split by user-supplied ratios interpolated the same way as passenger. This is a meaningful refactor of the freight projection logic.

---

### Phase 3: replace seed CSV defaults with direct LEAP export processing (`back-end/core/road_module1_defaults.py`)

The current pipeline builds a skeleton of rows from seed CSVs (containing hardcoded literal defaults) and overlays LEAP transport export values on top where branch paths match. This means any row whose branch path doesn't match in the LEAP export silently stays on a hardcoded default — there is no visible flag and no easy way to update those values without editing code.

**The goal of Phase 3 is to remove the hardcoded seed CSV defaults entirely and replace them with a two-step pipeline:**

```text
LEAP transport export (or any future source)
  → preprocessing script → road_module1_source_<ECONOMY>.csv  (intermediate)
  → main pipeline        → Module 1 long-row output
```

**Step 1 — Preprocessing script** creates a clean intermediate file per economy, stored in a new folder such as `back-end/data/road_model/processed_source/`. The script reads the raw LEAP transport export, strips out all rows and columns not relevant to road Module 1 (non-road branches, unused variables, unnecessary metadata columns), remaps branch paths and variable names to the road model structure where needed, and writes a simple CSV with only the columns the pipeline needs: `Branch Path, Variable, Scenario, Year, Value, Units`. This intermediate file is the stable contract between the data source and the pipeline. If a new LEAP export is available, re-run the script and the intermediate file is updated — nothing in the main pipeline needs to change. This will also make it easier to replace the LEAP export with a different source in future if needed — just update the preprocessing script to produce the same intermediate format.

**Step 2 — Main pipeline** reads the intermediate file directly and converts its rows into Module 1 long-row format. No skeleton-building, no overlay, no hardcoded defaults. Supplemental files (PHEV utilisation rates, saturation, reconciliation factors, survival profiles, vehicle equivalent weights) are merged on top as they are now — those are already well-structured and can stay as-is.

The intermediate file format is also easier to replace from a different source in future. If the LEAP transport export is eventually superseded by a different data system, that system just needs to produce a CSV with the same simple columns — the main pipeline is unchanged.

**Changes needed:**

1. **Archive the seed CSVs** — move `road_module1_default_*.csv` from `back-end/data/road_model/` to `back-end/data/road_model/archive/seed_csv_defaults/`. Remove all code that reads them.

2. **Write the preprocessing script** — a standalone script (e.g. `back-end/scripts/prepare_road_source.py`) that reads the LEAP transport export for each economy, filters to road branches only, remaps branch paths and variable names to the road model structure, and writes the intermediate CSV to `back-end/data/road_model/processed_source/road_module1_source_<ECONOMY>.csv`.

3. **Rewrite the pipeline entry point in `road_module1_defaults.py`** — read the intermediate CSV instead of building from seed CSVs. The main pipeline only needs to handle one clean structure.

4. **Fix the vehicle equivalent weight branch paths** — `overlay_model_factor_sources()` currently writes weights to `Demand\Passenger road\LPVs\Passenger cars` and `Demand\Passenger road\LPVs\SUV and light trucks`, which do not exist in the road model branch structure. The correct branch is `Demand\Passenger road\LPVs`. Fix `VEHICLE_TYPE_DETAIL_BRANCH` and the path mapping in that function.

5. **Remove the missing fallback file reference** — the code references `transport_leap_export_combined_00_APEC_domestic_international_Target_20260514.xlsx` as a last-resort fallback but this file no longer exists. Remove the reference.

6. **Document in `UPDATE_METHOD.md`** — record which export file was used as the source, what branch path and variable name remappings the preprocessing script applies, and what checks confirmed the output was correct.

---

### Module 1 output format and cleanup

After the input-data code is written, the following changes still need to happen:

1. **Switch the writer, static bundle, and run-model endpoint from wide rows to long columns.**
   The canonical CSV contract (documented in `multinode_road_module1_repo_guide.md`) requires columns:
   `Economy, Scenario, Branch Path, Variable, Year, Value, Units, Source, Comment`
   The current writer still produces the legacy wide-row format.

2. **Write stable, versioned filenames.**
   Output files should follow a pattern like `road_module1_values_20_USA.csv` (economy code included, no timestamps that change on every run).

3. **Update `run_model_router.py`.**
   It still writes `road_module1_default_filled_inputs_<ECONOMY>.csv` — this needs to be updated to match the new filename convention and long-column format.

4. **Clean up source validity CSVs.**
   Current source data includes Bus and Motorcycle PHEV rows. The interface guide says PHEV applies only to LPVs and LCVs. Once the guide is confirmed as final, remove or invalidate the Bus/Motorcycle PHEV entries from the source files.
