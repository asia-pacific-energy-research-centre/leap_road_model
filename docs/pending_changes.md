# Pending changes

## Interface TODO

- [ ] Add researcher-change persistence and history. When edits are detected and the researcher runs the road model, show small explanatory text below the Run Road Model button stating that the changes will be saved and may be used in future road-model datasets, then automatically save an immutable, timestamped copy of the completed economy CSV to the shared Google Drive archive. Record each researcher override against the canonical Module 1 key `(Economy, Scenario, Branch Path, Variable, Year)`, including the previous value, new value, comment/provenance, timestamp, and researcher/session identity. Preserve and reapply these overrides when source defaults or static bundles are regenerated, while keeping the generated default value available for comparison and allowing previous submissions to be retrieved and reviewed.
- [ ] Build a reviewed process for incorporating archived researcher submissions into future model data. Normalize each saved submission against the exact source/default version it was based on, produce a per-row diff, and allow each reviewed change to be either (a) retained as a final override or (b) promoted into the appropriate source data and a new immutable generated version while archiving the previous version. Test the process with a small set of changed files, verify model outputs, then revert the test changes and confirm the prior data and outputs are restored.
- [ ] Double-check how correction factors work: document their intended inputs, calculation/application order, scenario behavior, and effect on model and dashboard outputs.

## Model scope TODO

- [ ] Decide whether to activate truck PHEVs, following the [truck PHEV drive-addition case study](new%20model/adding_a_drive_case_study_truck_phev.md). Before activation, approve the truck combustion-fuel family and utilisation granularity, add reviewed Module 1 sources and static-contract rows, implement vehicle-specific fuel eligibility, add matching LEAP branches/reference metadata, and pass the documented cross-repo end-to-end checks.
