# Transport assumptions dashboard input snapshot

This archive preserves the task-local input files used to build the original
transport assumptions dashboards on 12 August 2026. The original task was
`Transport dashboards · extraction fixed` (`019ff3d4-7e17-7510-a8c9-95b8be59cebf`).

The retained snapshot is beside the dashboard package on Google Drive:
[transport dashboard inputs, 12 August 2026](https://drive.google.com/file/d/15ROt5VPkvaTAdVjmwGwWvNGSiG9l2YN-/view?usp=drivesdk).
Extract it outside this repository and pass its `data/` folder to the dashboard
entry point as `--data-dir`. It is deliberately not committed here.

## Included

The `data/` directory is copied from:

`C:\Users\Work\Documents\Codex\2026-08-12\wiht\work\non_road_assumptions_dashboard\data`

It contains the per-economy domestic non-road detailed model outputs, final-fuel
energy outputs, user inputs and growth rates, and the fuel-mixing assumptions
workbook used by the original dashboard workflow.

## Referenced but not duplicated

The original workflows also referenced these external sources:

- 9th-edition model code and configuration extracted under the original task's
  `work/transport_model_9th_edition_code/` directory;
- `C:\Users\Work\github\leap_transport\data\archive\international_bunker_outputs_20250421 - POSTHOC CHANGES MADE.csv`;
- road-model chart and fleet-result files selected by
  `prc_road_dashboard_workflow.py`; and
- the economy concordance and YAML configuration contained in the extracted
  9th-edition model code.

These larger or separately maintained sources are not duplicated in this input
archive. `build_transport_assumptions_dashboard.py` records and validates their
supplied paths in `dashboard_build_manifest.json` for each build.

## Related artifacts

- Original generated bundle: `transport_dashboards.zip`
- Updated road comparison bundle: `9th_transport_model_dashboards_road_updated.zip`
- Original creation date: 12 August 2026
