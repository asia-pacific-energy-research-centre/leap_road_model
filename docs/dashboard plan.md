# Build a lightweight static transport model dashboard

Near-term note for the current Python road workflow:

- keep lightweight matplotlib QA figures as the first verification layer;
- generate them at the end of each module and for the whole workflow;
- keep them behind a workflow switch so batch runs can disable them when needed;
- treat the static dashboard below as the next layer up: a richer exploration
   surface built from already-curated workflow outputs rather than raw model files.

Do not use Dash.
Do not use a backend.
Do not use a database.
Do not require Python at runtime.
The app must be compatible with GitHub Pages.

Use:

- static HTML/CSS/JavaScript;
- Plotly.js for charts;
- Python only as a preprocessing/build step;
- JSON files for the first version;
- a schema that can later support Parquet/DuckDB-WASM if needed.

The dashboard should make a large transport model dataset easier to investigate.

Core requirements:

1. sidebar filters for run, economy, scenario, data stage, year range, transport type, vehicle type, drive, fuel, and variable;
2. a collapsible model tree showing transport type → vehicle type → drive → fuel;
3. clicking the tree should filter the charts and tables;
4. charts should update from the selected filters;
5. include Plotly charts for:
   - energy by fuel over time;
   - stock by vehicle type;
   - sales by drive;
   - reconciliation gap by fuel;
6. include a searchable validation flags table;
7. include a detail panel showing selected branch, variables, units, source/default flags, and warnings;
8. use a dashboard data layer, not raw model files directly;
9. include a `data_stage` field so we can later compare pre-LEAP import data with post-LEAP exported data;
10. keep all code simple and readable.

Create:

- proposed folder structure;
- dashboard-ready data schemas;
- Python preprocessing script outline;
- static dashboard page layout;
- JavaScript module structure;
- first implementation plan.

Do not build a complex framework.
Prioritise clarity, speed, and GitHub Pages compatibility.
