"""Preview Module 1 dashboard pages using the dummy test fixture.

Generates the module1.html dashboard page from the dummy CSV so you can
visually check what the charts look like with researcher-provided values,
missing rows, and comments — without needing a full model run.

Run from the repo root:
    python scripts/preview_module1_dashboard.py
"""
#%%
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "codebase"))

import pandas as pd
from road_workflow import parse_leap_format_inputs
from diagnostics.plotly_dashboard import write_module_pages

FIXTURE = _REPO / "codebase" / "tests" / "fixtures" / "module1_test_dummy.csv"
OUT_DIR = _REPO / "plotting_output" / "module1_dashboard_test"

raw = pd.read_csv(FIXTURE)
merged = parse_leap_format_inputs(raw)

print(f"Loaded {len(merged)} rows from dummy fixture (rows with values)")
year_cols = [c for c in raw.columns if isinstance(c, str) and c.strip().isdigit() and len(c.strip()) == 4]
missing_raw = int(raw[year_cols].isna().all(axis=1).sum()) if year_cols else 0
print(f"Rows with all year values blank (missing): {missing_raw}")

if "source_type" in merged.columns:
    print(f"\nSource types:\n{merged['source_type'].value_counts(dropna=False).to_string()}")
if "review_reason" in merged.columns:
    comments = merged[merged["review_reason"].fillna("").astype(str).str.strip().ne("")]
    print(f"\nRows with comments: {len(comments)}")

written = write_module_pages(
    {"module1_merged": merged, "module1_raw_df": raw},
    dashboard_dir=OUT_DIR,
    economy="20_USA_TEST",
)
print(f"\nWritten {len(written)} pages to {OUT_DIR}")

index = OUT_DIR / "module1.html"
if index.exists():
    print(f"Open: {index.resolve().as_uri()}")
#%%