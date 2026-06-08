# leap_road_model

Python preparation system for the APERC road transport model in LEAP.

This repo consumes Road Module 1 inputs from `road_model_inputs_interface`,
builds the downstream Modules 2-7 tables, reconciles base-year road energy to
ESTO, and writes LEAP-ready import outputs and diagnostics. LEAP remains the
official projection platform.

## Repo setup — both repos must be siblings

Both repos must be cloned into the **same parent folder**:

```text
parent_folder/
    leap_road_model/              ← this repo
    road_model_inputs_interface/  ← sibling repo
```

Modules 2-7 read their Module 1 inputs from
`../road_model_inputs_interface/back-end/outputs/road_module1_defaults/`.
If the sibling repo is absent, the workflow falls back to legacy inputs in
`input_data/module1_defaults/`.

Keep both repos open together in one VS Code multi-root workspace
(`File → Add Folder to Workspace`). Both use the `.venv` in their own folder.

## Overview diagrams

![Road transport model — quick view](docs/new%20model/Road%20transport%20model%20%E2%80%94%20quick%20view.png)

![Road model interface and LEAP pipeline workflow](docs/new%20model/Road%20model%20interface%20and%20LEAP%20pipeline%20workflow.png)

![Road transport model — researcher detail](docs/new%20model/Road%20transport%20model%20%E2%80%94%20researcher%20detail.png)

## Design source of truth

Use these docs first:

- `docs/new model/road_transport_model_detailed.md`
- `docs/new model/road_transport_model_simplified.md`
- `../road_model_inputs_interface/docs/new model/multinode_road_module1_repo_guide.md`

`transition_audit_report.md` is historical migration context only.

## Module 1 contract

Module 1 is owned by `road_model_inputs_interface`. The target handoff is one
long CSV per economy, using canonical underscore economy codes:

```text
road_module1_values_<ECONOMY>.csv
road_module1_values_20_USA.csv
```

Core columns are:

```text
Economy, Scenario, Branch Path, Variable, Year, Value, Units, Source, Comment
```

Vehicle-type stock split inputs use LEAP `Stock Share` rows at the vehicle-type
branch level:

```text
Demand\Passenger road\LPVs
Demand\Passenger road\Motorcycles
Demand\Passenger road\Buses
Demand\Freight road\Trucks
Demand\Freight road\LCVs
```

Module 3 treats these as physical stock shares. Passenger shares are converted
internally to LPV-equivalent capacity shares before the motorisation envelope is
allocated; freight projects total freight stock first and then splits it into
Trucks and LCVs.

## Modules

| Module | Status | Responsibility |
|---|---|---|
| Module 1 | External package | Road input data and defaults from `road_model_inputs_interface` |
| Module 2 | Implemented | Base-year road structure and calibration preparation |
| Module 3 | Implemented | Stock target projection |
| Module 4 | Implemented | Sales, survival, vintage, and turnover policy |
| Module 5 | Implemented | Base-year and seeded future vehicle sales shares |
| Module 6 | Implemented | LEAP handoff, fuel allocation, bounded reconciliation, Device Shares |
| Module 7 | Optional QA | Python mirror and post-LEAP validation |

Module 6 writes T11 at LEAP branch levels: `Stock` at transport and
vehicle-type level, `Sales` at transport level, `Mileage`, `Fuel Economy`, and
`Device Share` at fuel level, and `Stock Share`/`Sales Share` at share-control
levels. It does not emit `Activity Level`.

## Key runtime files

| Area | File |
|---|---|
| Orchestrator | `codebase/road_workflow.py` |
| Module 1 adapter | `codebase/adapters/road_module1_defaults.py` |
| Modules 2-7 | `codebase/modules/` |
| Schemas and validation | `codebase/schemas/` |
| Configuration | `codebase/config/` |
| Module 1 package generator | `scripts/generate_module1_defaults.py` |
| Strict LEAP import writer | `codebase/adapters/leap_import_writer.py` |
| Lifecycle profile exporter | `codebase/adapters/lifecycle_profile_exporter.py` |

When a LEAP reference export is available, the workflow writes a strict import
workbook with LEAP ID columns, metadata rows, and both `LEAP` and `FOR_VIEWING`
sheets. Any unmatched model/reference rows are returned in
`outputs["leap_import_warnings"]` and written beside the workbook.

The workflow also exports Module 4 survival and vintage profiles as LEAP
lifecycle profile workbooks under
`results/<economy>/lifecycle_profiles/`. The folder contains one workbook per
vehicle/profile type, `lifecycle_profile_manifest.csv`, and
`<economy>_lifecycle_profiles.zip` for interface download after a successful
model run.

## Configuration

Key configuration files live in `codebase/config/`:

| File | Content |
|---|---|
| `economies.yaml` | APEC economy codes and metadata |
| `scenarios.yaml` | Scenario labels and LEAP IDs |
| `vehicle_mappings.yaml` | Vehicle buckets, drive mappings, and vehicle-equivalent weights |
| `fuel_mappings.yaml` | Fuel names and drive/fuel eligibility |
| `model_defaults.yaml` | Guidance-only calibration reference; do not use as runtime fallback input |

## Running without the website

Modules 2-7 do not require the `road_model_inputs_interface` website to be
running. They only need the pre-generated Module 1 static outputs that the
sibling repo already contains under:

```text
../road_model_inputs_interface/back-end/outputs/road_module1_defaults/
```

**Quickest offline run — edit and execute `scripts/offline_workflow.py`:**

```python
# Set these constants near the bottom of scripts/offline_workflow.py
ECONOMY = "01_AUS"
SCENARIO = "Target"
BUILD_DASHBOARDS = True

# then run:
python scripts/offline_workflow.py
```

The script discovers the sibling repo's outputs automatically and falls back
to `input_data/module1_defaults/` if the sibling repo is not present. Set
`RUN_ALL = True` to run all economies in sequence.

**CLI equivalent:**

```powershell
python codebase\road_workflow.py 01_AUS --module1-defaults-dir ..\road_model_inputs_interface\back-end\outputs\road_module1_defaults
```

## Running tests

```bash
pip install -r requirements.txt
pytest tests/ -v
```

## Workflow entrypoint

`codebase/road_workflow.py` provides the orchestrator entrypoint:

- `RoadWorkflowConfig`: economy, scenario, year, input, and output settings.
- `RoadWorkflowInputs`: preloaded input tables when callers do not want file IO.
- `run_with_config(config, inputs)`: loads Module 1 defaults and runs Modules
  2-6, with optional diagnostics and output writes.

Module 7 is a QA mirror and can be run separately when LEAP comparison outputs
are available.

### Usage examples

#### 1. Minimal — one-liner via `run_for_economy`

Only an economy code is required. ESTO inputs are auto-resolved and future sales shares are auto-discovered.

```python
from codebase.road_workflow import run_for_economy

outputs = run_for_economy("12_NZ", scenario="Target")
t11 = outputs["T11"]  # LEAP-ready fuel/share table
```

#### 2. CLI — run from the terminal

```bash
cd codebase
python road_workflow.py 12_NZ --scenario Target
python road_workflow.py 20_USA --no-vis --output results/test
```

#### 3. Explicit — `RoadWorkflowConfig` + `RoadWorkflowInputs` + `run_with_config`

Use this when you want to supply your own DataFrames instead of relying on file auto-discovery.

```python
import pandas as pd
from codebase.road_workflow import RoadWorkflowConfig, RoadWorkflowInputs, run_with_config

config = RoadWorkflowConfig(
    economy="12_NZ",
    scenarios=["Reference", "Target"],
    base_year=2022,
    final_year=2060,
    module1_defaults_dir="input_data/module1_defaults",
    output_root="results/12_NZ",
    enable_visualisations=False,
)

inputs = RoadWorkflowInputs(
    population=pd.Series(..., index=range(2022, 2061)),  # indexed by year
    gdp=pd.Series(..., index=range(2022, 2061)),
    esto_road_energy_pj=pd.DataFrame(...),   # columns: economy, year, vehicle_type, energy_pj
    esto_fuel_totals=pd.DataFrame(...),      # columns: economy, year, fuel, energy_pj
    future_sales_shares=pd.read_csv("input_data/future_sales_shares/12_NZ.csv"),  # LEAP format
)

outputs = run_with_config(config, inputs)

# Key outputs
t4  = outputs["T4"]   # base-year branch table (Module 2)
t5  = outputs["T5"]   # stock targets (Module 3)
t6  = outputs["T6"]   # sales & turnover (Module 4)
t6v = outputs["T6v"]  # Module 4 age profiles used for lifecycle export
t7f = outputs["T7f"]  # future sales shares (Module 5)
t11 = outputs["T11"]  # LEAP-ready rows (Module 6)
```

The `future_sales_shares` DataFrame should follow the LEAP workbook column format: `Branch Path`, `Variable`, `Scenario`, `Region`, plus integer year columns (e.g. `2022`, `2030`, `2040`).
