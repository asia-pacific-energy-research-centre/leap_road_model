# Pending changes

## Interface TODO

- [ ] Add researcher-change persistence and history. Record each researcher override against the canonical Module 1 key `(Economy, Scenario, Branch Path, Variable, Year)`, including the previous value, new value, comment/provenance, timestamp, and researcher/session identity. Preserve and reapply these overrides when source defaults or static bundles are regenerated, while keeping the generated default value available for comparison and allowing the change history to be exported or reviewed.
