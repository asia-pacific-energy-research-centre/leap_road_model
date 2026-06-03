# Road transport model transition audit report

**Date:** 2026-05-25
**Status:** Historical migration reference. Do not treat this file as the current implementation source of truth.

Use `road_transport_model_workflow_guide.md` for the current module workflow and `road_transport_model_detailed_description.md` for the conceptual summary.

## 1. What This Audit Was For

This audit captured useful migration context while the road model was being split out from older transport workflows. It identified source files, reusable code patterns, LEAP workbook constraints, and proposed table contracts.

Some recommendations in the original audit were pre-implementation notes. The current codebase has since implemented Modules 2 to 7 around a generated Module 1 defaults package, so outdated sequencing notes and speculative table-design text have been removed from this document.

## 2. Useful Legacy Sources

### Existing LEAP transport outputs

Source location:

```text
C:\Users\Work\github\leap_transport\results\combined_exports
```

These workbooks are useful as benchmark and naming references. They contain a machine-readable `LEAP` sheet and a human-readable `FOR_VIEWING` sheet.

Key LEAP columns:

- `BranchID`, `VariableID`, `ScenarioID`, `RegionID`
- `Branch Path`
- `Variable`
- `Scenario`
- `Region`
- `Scale`
- `Units`
- `Per...`
- `Expression`
- `Level 1` to `Level 8`

### LEAP import workbook structure

The LEAP handoff should preserve the standard LEAP export/import shape described in `C:\Users\Work\.codex\AGENTS_LEAP_EXPORT.md`:

- metadata rows before the header;
- header row at index 2 when read with pandas;
- ID columns preserved from templates where available;
- `(Branch Path, Variable, Scenario, Region)` as the logical row key;
- `Expression` as the main import value field.

### 9th edition transport outputs

The 9th edition outputs remain useful for comparison and for seeding future sales-share trajectories. They should be treated as reference or bridge data, not as a reason to override the new Module 1 base-year contract.

### Old transport code

Older transport code remains useful for:

- economy and scenario naming conventions;
- lifecycle profile handling;
- sales-curve examples;
- LEAP expression parsing and writing patterns;
- benchmark output comparisons.

Old code should not be copied wholesale into the current workflow when a module already exists in `codebase/modules/`.

## 3. Current Module Mapping

The current implementation maps the audit concepts as follows:

| Current module | Main role |
|---|---|
| Module 1 defaults package | Generated upstream input contract loaded from `input_data/module1_defaults/` |
| Module 2 | Base-year road branch parsing and calibration preparation |
| Module 3 | Passenger and freight stock target projection |
| Module 4 | Sales, survival, vintage, and turnover policy |
| Module 5 | Base-year sales shares and seeded future sales shares |
| Module 6 | LEAP handoff, fuel allocation, ESTO reconciliation, and Device Shares |
| Module 7 | Optional Python mirror and post-LEAP validation |

## 4. Current Data Contract Summary

The current workflow uses these practical table concepts:

| Table | Source module | Purpose |
|---|---|---|
| `T4_base_year_branches` | Module 2 | Tidy base-year road branch inputs |
| Module 3 stock outputs | Module 3 | Passenger and freight target stocks plus diagnostics |
| `T6_sales_turnover` | Module 4 | Sales, survival, vintage, and stock accounting |
| `T7_sales_shares` | Module 5 | Base-year sales shares |
| `T7f_future_shares` | Module 5 | Optional seeded future sales-share trajectories |
| `T8` | Module 6 | Fuel allocation |
| `T9` | Module 6 | Reconciled branch values and scalar records |
| `T10` | Module 6 | Device Shares |
| `T11` | Module 6 | LEAP-ready output table |
| `T12` | Module 6 | Reconciliation diagnostics |
| `T12_phev` | Module 6 | PHEV utilisation diagnostics |
| `T13_mirror_output` | Module 7 | Optional Python mirror and LEAP comparison output |

The older audit proposed more tables than the current implementation needs. The workflow guide is the source of truth when table names differ.

## 5. Adapter Functions Still Worth Keeping in Mind

Useful adapter patterns from the audit:

- parse LEAP `Data(...)` and `Interp(...)` expressions into tidy year/value rows;
- load combined LEAP exports as benchmarks;
- load LEAP import workbooks as templates while preserving IDs and metadata;
- convert tidy rows back to LEAP expressions;
- write LEAP import workbooks with the required metadata/header rows.

These are implementation patterns, not mandatory function names.

## 6. Open Review Areas

The main areas that still benefit from human review are:

- economy-specific passenger saturation assumptions;
- freight elasticity choices where historical data are weak;
- vehicle-equivalent weights for non-LPV passenger modes;
- base-year EV sales shares where observed data are incomplete;
- PHEV electric utilisation rates;
- large reconciliation scalars for stock, mileage, or fuel economy;
- any emerging-fuel allocation rule added to road.

## 7. Files to Use Now

Current implementation files:

- `codebase/road_workflow.py`
- `codebase/adapters/road_module1_defaults.py`
- `codebase/modules/module2_base_year.py`
- `codebase/modules/module3_stock_targets.py`
- `codebase/modules/module4_sales_turnover.py`
- `codebase/modules/module5_sales_shares.py`
- `codebase/modules/module6_leap_handoff.py`
- `codebase/modules/module7_mirror.py`

Current documentation files:

- `docs/new model/road_transport_model_workflow_guide.md`
- `docs/new model/road_transport_model_detailed_description.md`
- `docs/new model/transition_audit_report.md`
