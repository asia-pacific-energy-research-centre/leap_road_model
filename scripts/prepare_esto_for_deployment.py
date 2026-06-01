"""
Prepare a deployment-ready ESTO CSV from the full source file.

Run this locally whenever the source ESTO file changes, then commit the output.
The output is committed to input_data/ so HF Spaces and other server deployments
have it available without needing the full 34 MB source file.

Usage:
    python scripts/prepare_esto_for_deployment.py
    python scripts/prepare_esto_for_deployment.py --src path/to/00APEC_2024_low_with_subtotals.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_SRC = _REPO_ROOT.parent / "leap_transport" / "data" / "00APEC_2024_low_with_subtotals.csv"
_DEFAULT_DST = _REPO_ROOT / "input_data" / "esto_transport_2000_2022.csv"
_MIN_YEAR = 2000


def prepare(src: Path, dst: Path) -> None:
    print(f"Reading {src} ...")
    df = pd.read_csv(src)
    print(f"  Source: {df.shape[0]:,} rows x {df.shape[1]} columns")

    year_cols = [c for c in df.columns if c.isdigit() and int(c) >= _MIN_YEAR]
    keep_cols = ["economy", "flows", "products", "is_subtotal"] + year_cols

    # Keep detail transport flows (15.01, 15.02, …) but drop the top-level
    # '15 Transport sector' aggregate flow — it is a sum of the others.
    # Product-level subtotals (e.g. '19 Total', '07 Petroleum products') are
    # kept because the adapter explicitly needs them for reconciliation.
    detail_flows = df["flows"].str.match(r"^15\.\d+")
    filtered = df[detail_flows][keep_cols].reset_index(drop=True)
    print(f"  Filtered (transport detail flows, {_MIN_YEAR}+): {filtered.shape[0]:,} rows")

    dst.parent.mkdir(parents=True, exist_ok=True)
    filtered.to_csv(dst, index=False)
    size_mb = dst.stat().st_size / 1e6
    print(f"  Written to {dst}  ({size_mb:.2f} MB)")
    print("Done. Commit input_data/esto_transport_2000_2022.csv to make it available on HF Spaces.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--src", type=Path, default=_DEFAULT_SRC, help="Path to full ESTO CSV")
    parser.add_argument("--dst", type=Path, default=_DEFAULT_DST, help="Output path")
    args = parser.parse_args()
    prepare(args.src, args.dst)
