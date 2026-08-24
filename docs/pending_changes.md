# Pending changes

## Interface TODO

- [ ] Add researcher-change persistence and history. Record each researcher override against the canonical Module 1 key `(Economy, Scenario, Branch Path, Variable, Year)`, including the previous value, new value, comment/provenance, timestamp, and researcher/session identity. Preserve and reapply these overrides when source defaults or static bundles are regenerated, while keeping the generated default value available for comparison and allowing the change history to be exported or reviewed.
- [ ] Check the non-specified road treatment, with particular attention to fuel oil in PRC: confirm the source data, branch allocation, and resulting model/LEAP outputs are correct.
- [ ] Check that Reference versus Target is displayed correctly in the dashboards, including scenario labels, charts, tables, and any comparison views.
