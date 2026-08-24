# Pending changes

## Interface TODO

- [ ] Add researcher-change persistence and history. When edits are detected and the researcher runs the road model, show small explanatory text below the Run Road Model button stating that the changes will be saved and may be used in future road-model datasets, then automatically save an immutable, timestamped copy of the completed economy CSV to the shared Google Drive archive. Record each researcher override against the canonical Module 1 key `(Economy, Scenario, Branch Path, Variable, Year)`, including the previous value, new value, comment/provenance, timestamp, and researcher/session identity. Preserve and reapply these overrides when source defaults or static bundles are regenerated, while keeping the generated default value available for comparison and allowing previous submissions to be retrieved and reviewed.
- [ ] Check the non-specified road treatment, with particular attention to fuel oil in PRC: confirm the source data, branch allocation, and resulting model/LEAP outputs are correct.
- [ ] Check that Reference versus Target is displayed correctly in the dashboards, including scenario labels, charts, tables, and any comparison views.
- [ ] Double-check how correction factors work: document their intended inputs, calculation/application order, scenario behavior, and effect on model and dashboard outputs.
