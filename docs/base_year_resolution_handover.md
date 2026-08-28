# Base-year resolution handover

## Scope and policy confirmed by the user

Implement a reversible base-year system across `leap_road_model` and its sibling
`road_model_inputs_interface`.

- The economy registry is the authoritative default base-year source.
- Per-run overrides are allowed only when explicit and auditable.
- Keep Russia's configured 2021 exception.
- Exact-year native observations must beat earlier carried-forward observations.
- A future observation may seed an earlier base year only when there is no
  eligible exact-year or earlier observation; it must be recorded as future
  use, never as native to the requested year.
- ESTO energy balances remain exact-year reconciliation anchors.
- Generated outputs must never be read back as source inputs.
- Do not alter production Drive, Secrets, production source/default/static data,
  deployment configuration, model inputs, or model results.

The user explicitly accepted an unrelated pre-existing test failure and asked
the work to continue.

## Repository status

`leap_road_model` has one pre-existing untracked directory, `outputs/`; leave it
untouched. `road_model_inputs_interface` was clean after the commits below.

Completed commits:

| Repository | Commit | Content |
|---|---|---|
| `road_model_inputs_interface` | `1b2e713` | Phase 1 hand-off: static-index base-year metadata, browser/API base-year field, runtime package manifest, mismatch check. |
| `leap_road_model` | `3f56691` | Phase 1 model contract: economy-registry resolver, manifest/run validation, legacy package handling. |
| `road_model_inputs_interface` | `23b8c62` | Phase 2 schema: archive normalizer and browser preserve four provenance fields. |
| `leap_road_model` | `d532487` | Phase 2 adapter accepts provenance aliases. |
| `road_model_inputs_interface` | `e068207` | Partial Phase 3: fallback selection retains observation year and records carried-forward treatment. |

## What exists now

### Phase 1 contract

- `leap_road_model/codebase/adapters/base_year_contract.py`
  - Reads `codebase/config/economies.yaml`.
  - `resolve_base_year()` returns registry default or explicit override.
  - `validate_package_base_year()` marks no-manifest packages
    `legacy_inferred`, or raises on disagreement.
- `road_workflow.py` resolves the run year from that registry and validates the
  Module 1 runtime manifest before model work begins.
- The interface static builder writes `base_year` per economy into new
  `index.json` builds; do **not** regenerate the production static bundle as
  part of this task.
- Browser state sends `base_year` to `/run-model`; the API writes
  `road_module1_package_manifest.json` next to the runtime CSV and passes
  `--base-year` to the model.
- Existing static bundles/packages without metadata remain readable. They are
  legacy rather than silently treated as native.

### Phase 2 provenance schema

Canonical long fields now include:

```text
Source Data Year
Source Classification
Base Year Treatment
Derivation Method
```

Accepted classifications:

```text
native_observation, projection, structural_assumption,
model_assumption, legacy_unknown
```

Accepted treatments:

```text
native, carried_forward, carried_backward, transformed, legacy_unrecorded
```

Missing fields are conservatively normalised as `legacy_unknown` and
`legacy_unrecorded`. Browser wide-row conversion stores provenance in
`_provenanceByYear` so it can export per-year metadata losslessly.

`carried_backward` is the canonical treatment for a future observation used as
an earlier requested base year. Exact-year non-native candidates retain their
source classification and use `transformed`; they are never relabelled native.

### Phase 3 resolver contract

`road_model_inputs_interface/back-end/core/base_year_candidate_resolver.py`
now provides a small pure resolver over explicit original candidate records.
It validates candidate identity/key/source fields, source-data years,
classification and policy configuration; rejects duplicate candidate IDs; and
returns the selected candidate plus structured rejection reasons. Its ordering
is exact year, latest eligible earlier, then earliest eligible future; quality
and source priority are configured tie-breakers, followed by stable candidate
identity. It neither reads nor writes production files.

The supplied policy identifiers are `energy_balance_exact_year` and
`seed_eligible`. Variable-to-policy assignment is intentionally left to a later
reviewed integration: this phase does not invent production assignments, source
quality rankings, or age limits, and does not alter static/generated packages.

### Superseded partial Phase 3 resolver change

`road_model_inputs_interface/back-end/core/road_module1_defaults.py`
`load_processed_source_inputs()` still needs a dedicated resolver. The old
copy-and-relabel block was only partially corrected:

- it now ranks eligible prior rows by `_priority_sort`, year descending, then
  `_source_name`;
- it records `Source Data Year`, `carried_forward`, and
  `prior_observation_seed` before setting the model `Year` to `BASE_YEAR`.

It is **not** yet sufficient: the resolver is global-`BASE_YEAR` based, does
not emit an audit/rejections table, has no variable-policy registry, and the
new fields are not fully propagated through every source-generation path.

## Required next work, in order

1. Finish Phase 2 before adding more resolver behaviour:
   - add schema/round-trip tests for all four fields;
   - test unknown values and malformed source year;
   - ensure the static build and model adapter preserve the fields;
   - update source/update and hand-off documentation.
2. Connect the Phase 3 resolver only after approving a variable-to-policy map
   and source quality tiers. Keep its original-candidate-only boundary and
   preserve its selected/rejected audit contract.
3. Do not invent age thresholds or source-quality definitions; report age only
   until policy is approved.
4. Write generated resolution outputs to a new, clearly generated temporary or
   versioned build location: package, manifest, audit, needs-newer-data report,
   validation report. Do not write to source directories.
5. Implement Phase 5 UI provenance badges/filter/inspector and protect edits
   from silently changing treatment to native.
6. Complete dynamic base-year work in Modules 2–7 and reconciliation. Audit
   every semantically active `2022`; do not mass replace historical endpoints.
7. Upgrade archive/batch metadata with backward read support for formats 1/2,
   base-year validation, checksum, full key including model year, and compact
   decision sheets.
8. Add the end-to-end reversibility/migration tests listed in the user request.

## Important current risks

## Repair checkpoint: archive, provenance, and package preflight

- The model resolves a registry base year only once. `run_for_economy()` passes
  that resolution provenance into `run_with_config()`; an actual supplied base
  year remains an `explicit_override`.
- Before modelling, a manifest-bearing package must match the selected economy,
  package version, and base year, and its rows must actually include the
  required base year. Packages without a manifest remain explicitly labelled
  `legacy_inferred`; they are never implicitly native.
- Russia remains a 2021 registry economy. The approved temporary compatibility
  bridge rebases an unmanifested, 2022-only Russia package to 2021 at load time,
  without changing the source/static package. It is limited to `16_RUS`, records
  `future_year_seed` provenance and `{source_base_year: 2022,
  target_base_year: 2021}` in workflow metadata, and emits a warning on every
  run. A manifest-bearing package is never rebased.

- The interface source builder still has many direct `BASE_YEAR = 2022`
  dependencies. Do not claim dynamic source builds work yet.
- Russia’s bridge is a temporary modelling policy, not evidence that the
  2022-only package is native 2021 data. Replace it with a reviewed 2021 package
  before any release or source-data promotion.
- The runtime package manifest is overwritten in the runtime input cache; this
  is acceptable for the current cache semantics, but archive metadata must later
  pin the exact package checksum/year.
- The legacy source-loader fallback remains globally `BASE_YEAR` based. It is
  deliberately not connected to the Phase 3 resolver until an approved
  variable-to-policy map exists; do not extend it opportunistically.

## Tests already run

- Interface full suite after Phase 1: `57 passed`.
- Interface focused provenance/router tests after Phase 2: `44 passed`.
- Model adapter/base-year focused tests after Phase 2: `34 passed`.
- Model full suite after Phase 1: `247 passed, 1 failed`.
  The known unrelated failure is
  `codebase/tests/test_plotly_dashboard.py::test_dashboard_writes_pre_and_post_reconciliation_stock_pages`.
  Its expectation excludes `Passenger energy growth context`, but the generated
  dashboard includes it. The user authorized proceeding despite this.

Before each future commit: run focused tests, both full suites, `git diff --check`,
confirm no production/generated data changed, update docs, and commit only that
phase's files using a `codex:` prefix.
