"""
Validation helpers for road transport model data contracts.

These are intentionally simple — just pandas-based checks, no heavy
validation library required. Each function returns a list of error strings.
An empty list means the table passed validation.
"""

from __future__ import annotations

import pandas as pd
from typing import Any

from schemas.tables import (
    SCHEMAS,
    VALID_TRANSPORT_TYPES,
    VALID_VEHICLE_TYPES,
    VALID_DRIVE_TYPES,
    VALID_SCENARIOS,
)


class ValidationError(Exception):
    """Raised when a required validation check fails."""


def validate_table(df: pd.DataFrame, schema_key: str, raise_on_error: bool = False) -> list[str]:
    """
    Validate a DataFrame against the named schema.

    Args:
        df: DataFrame to validate.
        schema_key: Key into SCHEMAS dict, e.g. 'T5_stock_targets'.
        raise_on_error: If True, raise ValidationError on first failure.

    Returns:
        List of error message strings. Empty means all checks passed.
    """
    if schema_key not in SCHEMAS:
        raise ValueError(f"Unknown schema key: {schema_key!r}")

    schema = SCHEMAS[schema_key]
    errors: list[str] = []

    # --- Required columns present ---
    for col, spec in schema["columns"].items():
        if spec["required"] and col not in df.columns:
            errors.append(f"[{schema_key}] Missing required column: {col!r}")

    if errors and raise_on_error:
        raise ValidationError("\n".join(errors))

    # --- No nulls in required columns that are present ---
    for col, spec in schema["columns"].items():
        if spec["required"] and col in df.columns:
            null_count = df[col].isna().sum()
            if null_count > 0:
                errors.append(
                    f"[{schema_key}] Column {col!r} has {null_count} null value(s)"
                )

    # --- Schema-specific checks ---
    if schema_key == "T5_stock_targets" and "target_stock" in df.columns:
        neg = (df["target_stock"] < 0).sum()
        if neg:
            errors.append(f"[T5] {neg} row(s) with negative target_stock")

    if schema_key == "T7_sales_shares" and "sales_share" in df.columns:
        errors.extend(_check_shares_sum_to_one(
            df, ["economy", "scenario", "vehicle_type"], "sales_share", schema_key
        ))
        out_of_range = ((df["sales_share"] < 0) | (df["sales_share"] > 1)).sum()
        if out_of_range:
            errors.append(f"[T7] {out_of_range} sales_share value(s) outside [0, 1]")

    if schema_key == "T10_device_shares" and "device_share" in df.columns:
        errors.extend(_check_shares_sum_to_one(
            df,
            ["economy", "scenario", "transport_type", "vehicle_type", "drive_type"],
            "device_share",
            schema_key,
        ))

    if schema_key == "T11_leap_ready":
        errors.extend(_check_leap_ready(df))

    if schema_key == "T6_sales_turnover":
        errors.extend(_check_stock_accounting(df))

    if raise_on_error and errors:
        raise ValidationError("\n".join(errors))

    return errors


def _check_shares_sum_to_one(
    df: pd.DataFrame,
    group_cols: list[str],
    share_col: str,
    schema_key: str,
    tolerance: float = 0.01,
) -> list[str]:
    """Check that share_col sums to 1.0 within each group."""
    errors = []
    present = [c for c in group_cols if c in df.columns]
    if not present or share_col not in df.columns:
        return errors

    totals = df.groupby(present)[share_col].sum()
    bad = totals[(totals - 1.0).abs() > tolerance]
    if not bad.empty:
        errors.append(
            f"[{schema_key}] {len(bad)} group(s) where {share_col!r} does not sum to 1.0 "
            f"(max deviation: {(bad - 1.0).abs().max():.4f})"
        )
    return errors


def _check_stock_accounting(df: pd.DataFrame, tolerance: float = 0.5) -> list[str]:
    """Check the stock accounting identity: stock ≈ surviving_stock + new_sales - additional_retirements."""
    errors = []
    required = {"stock", "surviving_stock", "new_sales", "additional_retirements"}
    if not required.issubset(df.columns):
        return errors

    implied = df["surviving_stock"] + df["new_sales"] - df["additional_retirements"]
    deviation = (df["stock"] - implied).abs()
    bad = (deviation > tolerance).sum()
    if bad:
        errors.append(
            f"[T6] Stock accounting identity violated in {bad} row(s) "
            f"(max deviation: {deviation.max():.2f} vehicles)"
        )
    return errors


def _check_leap_ready(df: pd.DataFrame) -> list[str]:
    """Check T11 LEAP-ready table."""
    errors = []

    if "value" in df.columns:
        neg = (df["value"] < 0).sum()
        if neg:
            errors.append(f"[T11] {neg} row(s) with negative value")

    if "year" in df.columns:
        years = set(df["year"].unique())
        expected = set(range(2022, 2061))
        missing = expected - years
        if missing:
            errors.append(f"[T11] Missing years in output: {sorted(missing)[:5]}...")

    return errors


def summarise_validation(errors: list[str]) -> str:
    """Return a human-readable validation summary."""
    if not errors:
        return "All checks passed."
    return f"{len(errors)} validation error(s):\n" + "\n".join(f"  • {e}" for e in errors)
