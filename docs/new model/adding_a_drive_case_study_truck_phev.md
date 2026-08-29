# Adding a road drive type: truck PHEV case study

## Purpose and result

This case study records how to add an existing model drive type to a new vehicle
type. The example is adding `PHEV` to `Trucks`, which already have `medium` and
`heavy` size branches.

The investigation on 29 August 2026 reached two different conclusions:

1. **The software structure can represent a sized truck PHEV.** An executable
   proof adds `PHEV` to a copy of the truck drive matrix, generates the expected
   medium/heavy fuel branches, calculates electric and liquid Device Shares, and
   carries the branches into T11.
2. **Truck PHEVs are not ready to switch on in the production model.** The
   current PHEV implementation assumes gasoline-family liquid fuels, the
   freight utilisation input is an LCV proxy, the current static contract omits
   truck-PHEV rows, and the LEAP reference workbook has no truck-PHEV branches.

This distinction matters. A branch appearing in Python proves structural
feasibility; it does not prove that the assumptions, energy reconciliation, or
LEAP import are valid.

The proof is
`codebase/tests/test_config_contract.py::test_truck_phev_case_study_proves_configured_branches_reach_t11`.
It deliberately changes an in-memory copy of the configuration and does not
enable the feature in production.

## Why PHEV is a useful case study

Adding a single-fuel drive such as BEV to a new vehicle type mainly requires a
new branch, inputs, sales shares, and a matching LEAP branch. PHEV exercises
more of the system because one technology has two operating modes:

- electricity for electric-mode travel;
- a combustion fuel for the remaining travel;
- different efficiency for each mode;
- an electric-driving-share assumption; and
- reconciliation against two or more ESTO fuel totals.

It therefore exposes the decisions that can be hidden by a simple branch-list
change.

## Current state of the truck-PHEV path

| Layer | Current evidence | Status before activation |
|---|---|---|
| Interface source prep | `prepare_road_source.py` excludes PHEV buses and motorcycles, but not trucks. | Partly prepared |
| Interface source pool | `manually_entered_missing_rows.csv` contains proxy mileage and fuel-economy rows for `PHEV medium` and `PHEV heavy`. | Experimental inputs exist; provenance and values need review |
| Interface derivation helper | `_PROXY_DRIVES` in `derive_missing_module1_rows.py` maps truck PHEV fossil mode to truck ICE and electric mode to truck BEV. | Mechanism exists |
| Current static contract | `road_module1_static_contract.csv` has LCV PHEV rows but no truck PHEV rows. | Disabled |
| Current static bundle | The configured `v2026_06_05_road_module1_sources` bundle has no truck PHEV rows. An older best-guess bundle contains some, but generated history is not an active contract. | Disabled |
| Model input adapter | `_VALID_BASE_DRIVES_BY_VEHICLE_TYPE` drops truck PHEV rows as out of scope. | Disabled |
| Module 2 skeleton | `vehicle_mappings.yaml` allows truck `ICE`, `BEV`, and `FCEV`, not `PHEV`. | Disabled |
| Modules 4 and 5 | Turnover and sales-share logic operate on drive labels generically. Module 5 aggregates size-level input shares to vehicle-type/drive shares. | Structurally compatible |
| Module 6 | PHEV/EREV electric-mode splitting, electricity reconciliation, liquid subtraction, Device Shares, and diagnostics are generic across passenger/freight and size. | Structurally compatible, but current liquid-fuel rule is not suitable for truck activation without review |
| LEAP reference workbook | `config/road model leap export.xlsx` contains LCV PHEV branches but no `Demand\Freight road\Trucks\PHEV ...` branches. | Blocking |

## The proposed branch shape

The existing generic PHEV rule would generate this structure after adding
`PHEV` to the truck drive matrix:

```text
Demand\Freight road\Trucks
  PHEV medium
    Electricity
    Motor gasoline
    Biogasoline
    Efuel
  PHEV heavy
    Electricity
    Motor gasoline
    Biogasoline
    Efuel
```

That is what the structural proof verifies. It is not yet the recommended
production fuel tree.

Real truck examples show why the combustion fuel needs an explicit decision.
Scania describes plug-in hybrid trucks paired with diesel engines and operation
on diesel, HVO, or biodiesel. A US Department of Energy medium-duty PHEV work
truck demonstration also used a diesel engine. These are evidence that simply
inheriting the passenger/LCV gasoline-family rule would be a modelling
assumption, not a neutral implementation detail:

- [Scania plug-in hybrid truck product information](https://www.scania.com/es/es/rpeinado/products/trucks/plug-in-hybrid-truck.html)
- [Scania PHEV and HEV truck description](https://www.scania.com/group/en/home/newsroom/news/2019/news-article-template.html)
- [US DOE medium-duty PHEV work-truck demonstration](https://www.energy.gov/sites/prod/files/2014/03/f12/vssarravt068_miyasato_2010_p.pdf)

Before activation, choose and document one of these approaches:

1. diesel-family truck PHEV (`Electricity`, `Gas and diesel oil`, and reviewed
   renewable diesel substitutes);
2. gasoline-family truck PHEV, if an APEC source supports that scope; or
3. two explicit truck plug-in-hybrid drive variants if both powertrains need to
   coexist and cannot be represented safely by Device Shares.

The recommended implementation is vehicle-specific fuel eligibility. Do not
add diesel to the global `PHEV` fuel list, because that would also add diesel
branches to LPVs and LCVs. Do not keep the global gasoline-only liquid
distribution rule for trucks if the approved truck definition is diesel-based.

## Full implementation process

### 1. Write the modelling decision first

Record the following before changing code or data:

- technology definition and LEAP label;
- eligible vehicle types and sizes;
- electric and combustion fuels;
- whether biofuel/e-fuel branches are physical powertrain options or fuel blends;
- electric-driving-share definition and units;
- base-year treatment when observed stock is zero;
- projected sales-share source and scenario behavior; and
- whether existing LEAP areas already contain the required branches.

For this case, the label is `PHEV`, the vehicle type is `Trucks`, and sizes are
`medium` and `heavy`. The combustion-fuel decision remains open.

### 2. Add or review source data in the interface repository

Owner: `road_model_inputs_interface`.

Prepare source-backed rows for both truck sizes:

- `Mileage` and `Fuel Economy` at each fuel branch;
- base-year `Stock Share` at `PHEV medium` and `PHEV heavy`;
- base-year and projected `Sales Share` at the technology/size branch; and
- PHEV electric driving share at a granularity the model can preserve.

The existing proxy method is reasonable for a feasibility test:

- electric mode from the corresponding truck BEV size;
- combustion mode from the corresponding truck ICE size.

It is not automatically a production source. Review the values, units, source
year, uncertainty, and provenance. Do not promote rows merely because they are
already present in `manually_entered_missing_rows.csv`.

The current supplemental utilisation file has only LPV and LCV rows. Its
freight road output is explicitly derived from the LCV rate. A truck PHEV
therefore needs either:

- reviewed truck-specific utilisation rows and a model interface that preserves
  vehicle type; or
- a documented freight-wide aggregation method that combines truck and LCV
  PHEV activity.

The second option is simpler but cannot represent different truck and LCV duty
cycles. Medium- and heavy-truck utilisation may also need separate assumptions
if their routes and charging opportunities differ materially.

### 3. Extend the static hand-off contract

Owner: `road_model_inputs_interface/back-end/data/road_model/config/road_module1_static_contract.csv`.

Add contract rows for each approved technology and fuel branch. At minimum:

- `Sales Share` and `Stock Share` for `PHEV medium` and `PHEV heavy`;
- `Mileage` and `Fuel Economy` for every eligible fuel leaf; and
- the utilisation row if its branch or granularity changes.

Set Current Accounts, projected-scenario, visibility, units, and notes
deliberately. The contract is not just a display list; it is the gate that
decides which generated rows reach the browser and model.

Review `road_module1_static_fuel_branch_exclusions.csv` after adding branches.
An exclusion is valid only under the existing ESTO-zero rule. A zero historical
truck-PHEV stock is not, by itself, a reason to omit a fuel branch required for
future sales.

### 4. Regenerate and inspect the Module 1 package

Run from `road_model_inputs_interface`:

```powershell
python back-end\build_road_model_static_defaults.py
```

Then verify at least one economy in all three places:

```text
back-end/outputs/road_module1_defaults/<version>/<economy>/
front-end/road-module1-static/<version>/<economy>.csv
front-end/road-module1-static/index.json
```

Check exact row keys, values, units, scales, provenance, scenario coverage, and
`Shown In Interface`. Do not hand-edit the generated static CSV.

### 5. Extend the model vehicle/drive scope

Owner: `leap_road_model`.

Two current scope gates must remain synchronized:

1. add `PHEV` to `Trucks` in
   `codebase/config/vehicle_mappings.yaml::valid_drive_types_by_vehicle_type`;
2. add `PHEV` to `Trucks` in
   `codebase/adapters/road_module1_defaults.py::_VALID_BASE_DRIVES_BY_VEHICLE_TYPE`.

Also update the guidance-only truck entries in
`codebase/config/model_defaults.yaml` so the configuration contract test remains
consistent. Those values are review guidance, not runtime fallbacks.

The duplicated scope gate is a maintenance risk. A future cleanup could load
the adapter scope from `vehicle_mappings.yaml`, but that refactor should be
separate from the first production activation unless needed to prevent a real
mismatch.

### 6. Implement vehicle-specific fuel eligibility

Owner: `codebase/config/fuel_mappings.yaml`, Module 2, and Module 6.

The current fuel eligibility key is drive-only. That is sufficient while every
PHEV shares the gasoline-family rule, but it cannot express “LPV/LCV PHEV uses
gasoline while truck PHEV uses diesel.” Add a reviewed vehicle-specific override
rather than broadening the global PHEV list.

The same rule must control all of these places:

- Module 2 branch enumeration;
- Module 6 eligibility and zero-stock bootstrapping;
- PHEV liquid-fuel distribution;
- subtraction from the correct ESTO liquid pools;
- ordinary-fuel allocation after PHEV subtraction; and
- validation of impossible drive/fuel combinations.

If diesel truck PHEV is approved, update tests that currently assert PHEV diesel
is always excluded. Narrow those assertions to the vehicle types where the rule
still applies.

### 7. Confirm sales-share and size behavior

Module 5 models shares by `(economy, scenario, year, vehicle_type, drive_type)`.
If the Module 1 input supplies `PHEV medium` and `PHEV heavy` shares, it sums the
size rows into one truck-PHEV drive share. When T11 is built, Module 6 fans the
drive share back to size branches using reconciled stock proportions, with an
equal split fallback for zero-stock drives.

Decide whether that behavior is acceptable. If policy assumptions need
different medium- and heavy-truck PHEV trajectories, size must become a
preserved Module 5 dimension rather than being aggregated away.

### 8. Add the branches to LEAP before strict export

The reference workbook at `config/road model leap export.xlsx` currently has
LCV PHEV branches but no truck PHEV branches. The strict writer merges T11
against a LEAP reference export and preserves its metadata. Python cannot make
an absent LEAP technology importable just by emitting a new path.

Create the approved branches in the LEAP area, export a fresh reference
workbook, and replace the configured reference through the normal reviewed
process. Confirm the metadata rows, branch paths, variables, scenarios, region,
and Level columns follow the LEAP export contract.

### 9. Test each boundary, then run an economy end to end

Minimum automated checks:

- adapter retains truck-PHEV Module 1 rows;
- Module 2 creates both sizes and only approved fuels;
- Module 5 includes PHEV in truck sales shares and preserves the intended size
  behavior;
- Module 4 turnover keeps truck-PHEV cohorts and sales;
- Module 6 splits electric/liquid mileage at the approved rate;
- fuel reconciliation subtracts truck-PHEV liquid energy from the correct ESTO
  pool;
- Device Shares sum to 100% for each size;
- T11 contains Stock Share, Sales Share, Mileage, Fuel Economy, and Device Share
  on the correct paths; and
- the strict LEAP writer matches every new row.

Run focused tests first:

```powershell
python -m pytest codebase\tests\test_config_contract.py codebase\tests\test_module2_base_year.py codebase\tests\test_module4.py codebase\tests\test_module5.py codebase\tests\test_module6.py codebase\tests\test_leap_import_writer.py
```

Then run a full economy from the current static package:

```powershell
python codebase\road_workflow.py <ECONOMY> --scenario Target --no-vis
```

Inspect:

```text
results/<economy>/module5/T7f_future_shares.csv
results/<economy>/module6/T11_leap_ready.csv
results/<economy>/module6/T12_phev_utilisation_diagnostics.csv
results/<economy>/module6/<economy>_leap_import.xlsx
```

Finally, import into a disposable copy of the LEAP area and confirm that LEAP
accepts the branches and produces plausible stock and energy results. A
successful workbook write alone is not the last verification step.

### 10. Update documentation and release notes

When activation is complete:

- update the branch trees and remove “Truck PHEV is out of scope” from the
  current methodology and modeller guide;
- document the selected liquid-fuel and utilisation methods;
- record the source package/version and LEAP reference export used;
- retain this case study as the decision history; and
- mark the pending feature complete only after the cross-repo and LEAP checks
  pass.

## What the feasibility proof does and does not prove

The automated proof:

- adds `PHEV` to an in-memory copy of the truck drive matrix;
- generates medium and heavy PHEV branches from the existing fuel map;
- constructs a synthetic medium-truck electric/liquid split;
- calculates 40% and 60% Device Shares; and
- confirms that T11 contains `Demand\Freight road\Trucks\PHEV medium` and its
  fuel leaves.

It does not:

- change the production branch matrix;
- approve gasoline as the truck combustion fuel;
- validate the proxy input values;
- add truck-specific utilisation data;
- add branches to the LEAP area/reference workbook; or
- prove a complete economy run and LEAP import.

Verification performed on 29 August 2026:

```text
python -m pytest codebase\tests\test_config_contract.py -q
7 passed

python -m pytest codebase\tests\test_module6.py -q
46 passed
```

The LEAP reference workbook was also inspected read-only across its used range
(`Sheet2!A1:U3377`). It contains LCV PHEV paths and no matching truck-PHEV path.

## Reusable checklist for any new drive/vehicle combination

Use this shorter checklist after reading the case study:

- [ ] Define the technology, sizes, fuels, and labels.
- [ ] Decide whether existing drive-wide rules are valid for the new vehicle.
- [ ] Add reviewed source rows with provenance.
- [ ] Extend the interface static contract and justified exclusions.
- [ ] Regenerate; never hand-edit the static bundle.
- [ ] Extend both model scope gates.
- [ ] Update guidance configuration without creating runtime fallbacks.
- [ ] Verify Module 4/5 dimensions, especially size aggregation.
- [ ] Verify Module 6 eligibility, reconciliation, and diagnostics.
- [ ] Add the same branches to LEAP and refresh the reference export.
- [ ] Test each boundary and one full economy.
- [ ] Update current documentation and record the release decision.

## Rollback

Keep the feature in one coherent cross-repository change. If end-to-end checks
fail, revert the source/contract, model scope, fuel rules, and LEAP reference
together, regenerate the prior static version, and rerun the smoke economy. Do
not leave the interface advertising rows that the model drops, or leave Python
emitting paths absent from LEAP.
