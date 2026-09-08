# Economy exceptions section plan

## Purpose

Add a concise, economy-specific section that explains modelling decisions which cannot be understood reliably from the charts alone. This should capture manual overrides, unusual base-year treatment, deliberate zeros, proxy assumptions, scope limitations and other special rules.

The section should explain decisions, not repeat patterns that are already clear in the plots.

## Recommended dashboard design

Place an **Economy notes and exceptions** section below the charts. It changes with the economy dropdown and contains:

1. **Important exceptions** — short, reviewed statements that materially affect interpretation.
2. **Data and scope limitations** — missing data, proxies, excluded activity and domestic/international boundaries.
3. **Technical implementation notes** — rules introduced only to make the transport model run or remain consistent with another model component.

Each entry should show:

- A short title and plain-language explanation.
- The affected scenario, years, medium, transport type, drive or fuel.
- The practical effect on the results.
- The source file, code location or analyst record supporting the statement.
- A review status and reviewer/date.

The section should initially show only high-impact reviewed entries. A disclosure control can reveal technical detail and lower-priority items.

## Exception registry

Maintain the content in a separate table rather than embedding prose in dashboard code. Recommended fields:

| Field | Purpose |
|---|---|
| `Exception_id` | Stable identifier. |
| `Economy` | Economy code. |
| `Title` | Short reviewer-facing title. |
| `Category` | Activity, intensity, drive switching, fuel switching, base year, data gap, scope or technical. |
| `Scenario` | Reference, Target or both. |
| `Medium` | Air, rail, ship or all. |
| `Transport_type` | Passenger, freight or both. |
| `Drive_or_fuel` | Specific affected series, when relevant. |
| `Start_year` / `End_year` | Period affected. |
| `Explanation` | What the exception is and why it exists. |
| `Result_effect` | How it changes activity, intensity, energy or fuel allocation. |
| `Source_type` | Code, input file, external source, analyst judgement or inferred. |
| `Source_reference` | File path, cell/range, line number or URL. |
| `Confidence` | Confirmed, probable or candidate. |
| `Review_status` | Needs review, accepted, rejected or superseded. |
| `Reviewer` / `Review_date` | Governance record. |

## How to populate it

### 1. Automated candidate scan

Use reproducible checks to flag patterns that may require explanation:

- Activity fixed for many years.
- Activity deliberately zero.
- Only one drive active across a medium.
- Abrupt activity, intensity or fuel-share changes.
- A drive appearing or disappearing in one year.
- Reference and Target scenarios unexpectedly identical.
- Model-output and fuel-output vintage mismatches.
- Energy not reconciling between drive and fuel outputs.
- Missing domestic/international coverage.

The first scan has produced `economy_exception_candidates_all_economies.csv`. These are review prompts, not confirmed exceptions.

### 2. Code and configuration scan

Search for economy-specific branches, mappings and manual assignments in:

- Non-road model calculation code.
- Economy-specific configuration.
- User-input creation and cleaning scripts.
- Fuel-mixing workbook comments and regional mappings.
- Base-year adjustment and ESTO reconciliation code.
- International bunker treatment.

Record the exact source reference and translate the technical rule into plain language.

### 3. Analyst review

An economy modeller should confirm whether each candidate is:

- An intentional modelling assumption.
- A source-data limitation.
- An expected structural feature.
- A model artefact or error requiring correction.

Only confirmed, interpretation-relevant items should appear prominently in the dashboard.

## Initial implementation sequence

1. Build the registry template and seed it with Russia and China.
2. Confirm known examples such as Russia's aviation treatment and China's intensity assumptions against their exact sources.
3. Review the 113 automatically generated candidates across all economies.
4. Add the section to the dashboard using the same economy dropdown.
5. Add validation requiring every displayed exception to have a source and review status.
6. Expand the code/configuration scan economy by economy.

## Important guardrails

- Do not describe every zero as an exception; many are valid unused technologies.
- Do not infer rationale from a trajectory alone.
- Keep numerical diagnostics separate from reviewed explanatory notes.
- Preserve superseded notes for audit history, but do not display them by default.
- Clearly label unverified candidates so they cannot be mistaken for modeller intent.
