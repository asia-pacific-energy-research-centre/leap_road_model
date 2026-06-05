# Pending changes

A running list of documented changes and improvements to make across both repos.

---

## 2026-06-04 implementation note

The following items from this file have been implemented in code and tests:

- `codebase/adapters/leap_import_writer.py` now writes a strict LEAP import workbook with ID-column merge, metadata rows, fixed LEAP column order, `LEAP` and `FOR_VIEWING` sheets, and structured warnings.
- `codebase/adapters/leap_workbook.py` road branch prefixes were corrected to `Demand\Passenger road` and `Demand\Freight road`.
- `build_leap_ready_table` no longer writes `Activity Level`; writes `Stock` at transport and vehicle level; writes `Sales` at transport level; writes `Mileage` at fuel level; adds vehicle-level `Sales Share`; and adds base-year `Stock Share` from reconciled stock counts.
- `estimate_freight_elasticity`, `project_freight_stocks`, and `run_module3` now pass freight elasticity diagnostics through T5.
- Module 4 now records `stock_above_target` and `scale_factor_applied` in T6 and the schema.
- `road_model_inputs_interface` processed-source generation now uses the all-economies LEAP workbook under `back-end\data\road_model\leap_import_workbooks`, writes 21 processed-source CSVs, and keeps the five canonical vehicle-type `Stock Share` rows.

Known remaining issues:

- The strict writer uses the `RegionID` from the reference LEAP export. The reference export is USA-specific, so for other economies the RegionID will be wrong (each LEAP area file assigns its own integer IDs). The writer returns a warning for this. Resolution requires the LEAP area file for each economy — for now the placeholder is acceptable and the warning serves as a reminder.
- A `20_USA` smoke run through Module 6 completed after path and saturation fixes — see [`results/codex_smoke_20_USA/module6/T11_leap_ready.csv`](../results/codex_smoke_20_USA/module6/T11_leap_ready.csv). The strict writer warning file filters out LEAP-derived/unmodelled measures, unsupported vehicle/drive/size/fuel combinations, and scenario-only mismatches. Remaining warnings are active-scope reference rows where T11 branch paths don't yet fully cover all LEAP reference rows (`Mileage`, `Fuel Economy`, `Sales Share`, `Stock Share`). These need reviewed row-by-row before treating the Excel workbook as LEAP-import complete.

LEAP variables intentionally not produced by this model (LEAP calculates or manages them independently):

- `First Sales Year` — LEAP default; no researcher input needed from this model.
- `Scrappage`, `Fraction of Scrapped Replaced`, `Max Scrappage Fraction` — LEAP default scrappage assumptions are used; Module 4 does not write these.
- `Average Mileage`, `Final On-Road Mileage`, `Mileage Correction Factor`, `Final On-Road Fuel Economy`, `Fuel Economy Correction Factor` — LEAP-derived from `Mileage` and `Fuel Economy` inputs.
- `Demand Cost` — LEAP-calculated from energy prices.
- `Activity Level` — not a road input variable in LEAP.

## leap_road_model

### T11 branch-path coverage gaps

T11 produces `Mileage`, `Fuel Economy`, `Sales Share`, and `Stock Share` but the strict writer still warns that some active-scope LEAP reference rows are unmatched. This means the branch paths or variable/scenario combinations in T11 don't cover every row in the USA reference export. Review the warning file at `results/<ECONOMY>/module6/` row-by-row to identify which specific paths are missing before treating the workbook as LEAP-import complete.

---

## road_model_inputs_interface

### CSV reupload validation in the researcher UI

**Implemented.** The upload flow now has two phases:

1. **Preview** — `previewRoadModule1UploadedRows()` validates key-column presence, rejects duplicate or unmatched keys, validates values, and computes a full diff (`changedCells`) without touching state.
2. **Confirm** — the upload summary modal shows the diff in confirm-mode (Cancel / Apply Changes buttons). Clicking Apply calls `commitRoadModule1UploadPreview()` to write the computed rows to state. Cancelling discards the preview.

Key columns (`Economy`, `Scenario`, `Branch Path`, `Variable`, `Year`) are not editable in the UI table (they appear only as group headers), so no additional read-only enforcement was needed.

---

### Vehicle-type stock split inputs (Module 1 + Module 3)

**What is implemented:**

- `_ensure_vehicle_type_stock_share_rows()` in `road_model_inputs_interface` auto-derives base-year stock shares from base-year Stock rows and seeds 2040 and 2060 `Stock Share` values to the same base-year level as defaults. Existing researcher-edited values are never overwritten.
- `road_workflow.py` interpolates annual shares between the base year and supplied target years and holds the last target constant. The LPV-equivalent conversion (using Module 1 vehicle-equivalent weights) is applied to passenger shares before Module 3.

**Passenger `Stock Share`** (LPVs, Motorcycles, Buses) — researcher-adjustable. Researchers can edit 2040/2060 anchor values to define a trajectory for the vehicle mix within the passenger motorisation envelope.

**Freight `Stock Share`** (Trucks, LCVs) — **not researcher-adjustable. Held flat at base-year proportions.** The truck/LCV split shows no strong projected trend and is not a meaningful lever for researchers to change. The 2040/2060 values are seeded equal to the base year and should be left unchanged.

**Potential future design — freight vehicle-equivalent index:**

The current approach applies a single GDP elasticity to each freight vehicle type independently. An alternative that mirrors the passenger approach would be:

1. Compute a weighted total freight stock: `total_weighted = Trucks × w_T + LCVs × w_LCV` using the existing vehicle-equivalent weights (Trucks=5.0, LCVs=1.5, already in `apec_vehicle_equivalent_weights.csv` and `model_defaults.yaml`).
2. Apply GDP elasticity to this weighted total: `total_weighted(year) = total_weighted_base × (GDP/GDP_base)^e`.
3. Back-calculate physical counts using fixed base-year shares and weights.
4. Add a diagnostic `freight_stock_index = total_weighted(year) / total_weighted_base` to T5.

With fixed shares this is mathematically equivalent to the current per-type projection, so it would not change results — only architecture and diagnostics. The implementation path is well-scaffolded (see difficulty note below); it is deferred until there is a concrete reason to need the index diagnostic.

**Implementation difficulty:** Moderate. `project_freight_stocks` already receives base stocks and shares; adding `vehicle_equivalent_weights` as a parameter and switching to weighted-total arithmetic is contained to that function. The weights are already loaded for all five vehicle types. The passenger code in `project_passenger_stocks` is the direct blueprint. Estimated scope: one function change plus a T5 schema addition.

---

### Interface source pipeline — remaining cleanup

Phase 3 is complete. Seed CSVs are archived, `prepare_road_source.py` exists, the pipeline reads from `processed_source/`, Bus/Motorcycle PHEV rows are filtered at source-load time (not deleted from files), and `UPDATE_METHOD.md` has the entry.

---

## Documentation updates

Every change actioned from this list needs a corresponding documentation update before it is considered complete. The relevant files are:

- `docs/new model/road_transport_model_simplified.md` — update if the conceptual model changes (new variables produced, new methods, new diagnostic outputs).
- `docs/new model/road_transport_model_detailed.md` — update if module responsibilities, outputs, or the module sequence changes. This is the main implementation reference so it should always reflect how the code actually works.
- `docs/new model/transition_audit_report.md` — this is a historical reference and should not need updating, but remove any section that would actively mislead if it contradicts new behaviour.
- `road_model_inputs_interface/docs/new model/multinode_road_module1_repo_guide.md` — update if the Module 1 input contract, file format, source policy, or pipeline structure changes.
- `road_model_inputs_interface/back-end/data/road_model/UPDATE_METHOD.md` — update whenever source data or the processing script changes.

When actioning a change, update the relevant doc in the same commit or PR as the code change — not as a follow-up. A change is not done until the documentation matches the code.
