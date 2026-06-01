# leap_road_model

Python preparation system for the APERC road transport model in LEAP.

This repo prepares the calibrated base-year road transport assumptions that LEAP needs,
then hands them off as a LEAP-ready input package. LEAP remains the official projection platform.

## Design source of truth

`leap_transport/docs/new model/road_transport_model_workflow_guide md version.md`

All modelling decisions should be traced back to that document.

## Reference files

See `leap_transport/docs/new model/transition_audit_report.md` for the full audit of
what existing code and data can support this system.

## Modules

| Module | Status | Responsibility |
|--------|--------|----------------|
| Module 1 | Stub | Road input data and defaults |
| Module 2 | Stub | Base-year road structure and calibration preparation |
| Module 3 | **Implemented** | Stock target projection (passenger S-curve + freight elasticity) |
| Module 4 | **Implemented** | Sales, survival, vintage, and turnover policy |
| Module 5 | Stub | Vehicle sales share preparation |
| Module 6 | **Implemented** | LEAP handoff, fuel allocation, iterative bounded reconciliation, Device Shares |
| Module 7 | Stub | Optional Python mirror and post-LEAP validation |

## Adapters

| Adapter | File | Purpose |
|---------|------|---------|
| A1, A2 | `adapters/combined_exports.py` | Load benchmark combined exports |
| A3, A9 | `adapters/leap_workbook.py` | Read/write LEAP import workbook |
| A4, A5 | `adapters/ninth_edition.py` | Load 9th edition reference outputs |
| A8 | `adapters/leap_expressions.py` | Convert tidy series ↔ Data() expressions |

## Data contracts

T1–T13 schemas are defined in `schemas/tables.py`.
Validation helpers are in `schemas/validation.py`.

## Config

All assumptions live in `config/`:

| File | Content |
|------|---------|
| `economies.yaml` | APEC economy codes and metadata |
| `scenarios.yaml` | Scenario labels and LEAP IDs |
| `vehicle_mappings.yaml` | Source vehicle type → model bucket; drive mappings; vehicle-equivalent weights |
| `fuel_mappings.yaml` | APEC fuel codes → LEAP fuel names; drive-fuel eligibility |
| `model_defaults.yaml` | k bounds, COVID exclusion years, reconciliation weights, default mileage/efficiency |

## Running tests

```bash
pip install -r requirements.txt
pytest tests/ -v
```

Module 3 tests and adapter expression tests will pass immediately.
Module 4–7 tests will raise `NotImplementedError` until ported.

Module 6 reconciliation now iteratively reapplies bounded stock/mileage/efficiency scalars until the branch fuel target is reached, progress stalls, or the iteration cap is hit.

## Single workflow entrypoint

`codebase/road_workflow.py` now provides a single orchestrator-style entrypoint:

- `RoadWorkflowConfig`: one place for economy/scenario/time settings and output paths.
- `RoadWorkflowInputs`: one container for preloaded input DataFrames/Series.
- `run_with_config(config, inputs)`: executes Modules 2–6 in sequence and can save
  intermediate outputs plus diagnostics PNG suites.

Notes:

- Module 1 is still not orchestrated because its merge logic is not fully implemented.
- Module 7 is still not orchestrated because the mirror module is not implemented.

## Implementation order

See `transition_audit_report.md` Section 9 for the recommended phase-by-phase order.

**Next step:** Answer the human review questions in Section 10 of the audit report,
then port the Module 4 core functions from `leap_transport/codebase/sales_workflow.py`.
