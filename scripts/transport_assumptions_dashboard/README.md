# Transport assumptions dashboard mini-system

This directory makes the original three-part transport assumptions dashboard
reproducible from `leap_road_model` without committing its roughly 245 MB raw
input snapshot. It is a review and communication product, not an input to the
road-model calculation.

The one supported entry point is:

```powershell
cd C:\Users\Work\github\leap_road_model
python scripts\transport_assumptions_dashboard\build_transport_assumptions_dashboard.py --help
```

## What it builds

The distributable `transport_dashboards` folder contains:

| Section | Purpose | Main page |
| --- | --- | --- |
| Domestic non-road (`nr`) | Air, rail and domestic navigation assumptions, intensity, activity and final fuels. | `nr\index.html` |
| International (`intl`) | International aviation and shipping outputs and the assumptions/exception registry. | `intl\index.html` |
| Road (`road`) | The original 9th-edition road outcomes, fleet transition diagnostics and explanatory assumptions for each economy. | `road\index.html` |

`open.html` opens the domestic non-road page first. Each dashboard is a
self-contained HTML page and the package retains its supporting CSV/JSON files
under `data\` for audit and reuse.

The current-road-model comparison is deliberately a separate build. It uses
`scripts\build_9th_dashboard_with_new_model.py` through this entry point to
append dashed, current-road-model lines to a copy of the preserved 9th road
pages. It does not alter the original three-part dashboard package.

## Inputs and provenance

The preserved input archive is documented in [input_manifest.md](input_manifest.md).
Download and extract it outside this repository, then point `--data-dir` at its
`data` directory. It contains domestic non-road source files only; it does not
contain the separately maintained 9th-edition code/configuration, international
bunker output, or road chart/fleet diagnostics.

The modules under `legacy/` are source-preserving copies of the original task
`Transport dashboards · extraction fixed`
(`019ff3d4-7e17-7510-a8c9-95b8be59cebf`, 12 August 2026). The only migration
changes to their execution are package-relative imports and disabling their old
import-time notebook run blocks. The entry point also accepts the snapshot's
`data` root, resolves its `raw_all` input folder, and retains the original
economy-exceptions guidance during packaging. Do not run the modules directly;
the entry point performs input checks and controlled packaging.

## Full original-package build

Supply paths to the maintained copies of each input. These example paths are
intentional placeholders: choose the current local locations rather than
recreating the old task-folder layout.

```powershell
python scripts\transport_assumptions_dashboard\build_transport_assumptions_dashboard.py `
  --build all `
  --output results\transport_assumptions_dashboard `
  --data-dir D:\transport_dashboard_inputs\data `
  --code-root D:\transport_model_9th_edition `
  --international-source D:\transport\international_bunker_outputs.csv `
  --road-chart-dir D:\transport\road_charts `
  --road-stock-dir D:\transport\road_fleet_diagnostics
```

The command writes intermediate generator outputs to
`results\transport_assumptions_dashboard\generated`, the short-path package to
`results\transport_assumptions_dashboard\transport_dashboards`, a ZIP beside
it, and `dashboard_build_manifest.json` describing the supplied sources and
stages. Existing generated package paths are protected; add `--replace` only
when intentionally refreshing that exact output root. Use `--no-zip` when a
folder is sufficient.

Build individual sections with `--build domestic-non-road`, `international`,
or `road`. After all three have been generated, use `--build package` to
repackage them, and `--build validate` to validate the saved package structure.

### Locally verified reproduction

The following is the exact 8 September 2026 clean-build command. The input ZIP
must first be extracted so that `input_snapshot\data\raw_all` exists; pass the
`data` parent, not `raw_all`, because the entry point resolves the snapshot
layout itself. The 9th-edition code copy is retained in the original task
workspace, while the other external inputs are maintained in `leap_transport`.

```powershell
python scripts\transport_assumptions_dashboard\build_transport_assumptions_dashboard.py `
  --build all `
  --replace `
  --output C:\Users\Work\github\leap_road_model\outputs\transport_dashboard_repro_2026-09-08\build `
  --data-dir C:\Users\Work\github\leap_road_model\outputs\transport_dashboard_repro_2026-09-08\input_snapshot\data `
  --code-root C:\Users\Work\Documents\Codex\2026-08-12\wiht\work\transport_model_9th_edition_code\transport_model_9th_edition `
  --international-source 'C:\Users\Work\github\leap_transport\data\archive\international_bunker_outputs_20250421 - POSTHOC CHANGES MADE.csv' `
  --road-chart-dir C:\Users\Work\github\leap_transport\results\diagnostics\transport_results_series_comparison\charts `
  --road-stock-dir C:\Users\Work\github\leap_transport\results\diagnostics\stock_projection_exploration
```

It generated all 21 road economy pages and the required `open.html`, domestic
non-road, international, and road landing pages. The rebuilt package had the
same 124 files and the same section/data counts as the preserved August bundle:
21 road economy pages, 85 road data files, 8 domestic non-road data files, and
5 international data files. The ZIP's structural validation also passed.

This is a reproduction of the original review package, not a recalculated LEAP
run. The external 9th-edition code copy is still a required input and should be
relocated to a maintained shared source before the original task workspace is
archived or removed.

The validated release artifact from that run is
`outputs\transport_assumptions_dashboards_repro_2026-09-08.zip` (32,116,046
bytes). Its sidecar build manifest is
`outputs\transport_assumptions_dashboards_repro_2026-09-08_manifest.json`.

## 9th-versus-current road comparison

Build this separately once current road-model comparison results are available:

```powershell
python scripts\transport_assumptions_dashboard\build_transport_assumptions_dashboard.py `
  --build road-comparison `
  --output results\transport_assumptions_dashboard `
  --comparison-source C:\path\to\transport_dashboards `
  --model-root results\qa_9th_comparison\new_model_all_scenarios `
  --merged-energy C:\path\to\merged_file_energy_ALL.csv
```

Its output is a separate `road_comparison` directory by default. See
[`docs/new model/reviewing_road_results_against_9th_edition.md`](../../docs/new%20model/reviewing_road_results_against_9th_edition.md)
for the review sequence, known drivers of differences, and escalation criteria.

## How to use the dashboards

Start at `open.html`, select an economy/scenario/transport type, then narrow
to vehicle, drive, fuel, or measure only after finding the first year where a
trajectory diverges. Read the assumption/exception text alongside the chart:
it tells the reviewer what was configured, not whether it is appropriate for a
new economy-specific projection.

For road review, first check base-year reconciliation and the passenger/freight
split. Then trace a difference through stock, survival/turnover, sales shares,
mileage, efficiency and fuel allocation. A final-year difference by itself is
not diagnostic. Investigate discontinuities, invalid fuel/technology pairs,
unreconciled ESTO totals, or differences that cannot be explained by a
documented assumption or structural change.

The new-model series are a **Python mirror** of the current default road-model
inputs. They are useful for checking mappings and expected directions, but
they are not calculated LEAP results. Treat an exported/imported/recalculated
LEAP result as authoritative only after the LEAP calculation has completed and
been reviewed against its result export. In particular, the dashboard does not
prove LEAP-side correction-factor behaviour.

## Maintenance boundary

Keep raw dashboard inputs in the shared dashboard location, not in Git. Update
[input_manifest.md](input_manifest.md) when the retained snapshot or external
source locations change. Make a fresh build, inspect the manifest and package
validation result, and share the new ZIP/folder as a versioned dashboard
artifact. Do not hand-edit `generated/`, `transport_dashboards/`, or the ZIP.
