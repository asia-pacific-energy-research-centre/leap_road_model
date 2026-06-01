"""
Adapter: LEAP Data() expression format.

Converts between tidy (year, value) time series and the
LEAP import/export expression string format:
    Data(2022, v1, 2023, v2, ..., 2060, v39)

These are pure format converters. Keep them separate from model logic.
"""

from __future__ import annotations

import re
import pandas as pd


def to_leap_expression(series: pd.Series) -> str:
    """
    Convert a pd.Series indexed by year into a LEAP Data() expression string.

    Args:
        series: pd.Series indexed by integer year, sorted ascending.

    Returns:
        String like 'Data(2022, 0.0, 2023, 1234.5, ...)'

    Example:
        >>> s = pd.Series({2022: 0.0, 2023: 100.0, 2024: 200.0})
        >>> to_leap_expression(s)
        'Data(2022, 0.0, 2023, 100.0, 2024, 200.0)'
    """
    series = series.sort_index()
    parts = []
    for year, value in series.items():
        parts.append(str(int(year)))
        parts.append(f"{value:g}")
    return "Data(" + ", ".join(parts) + ")"


def from_leap_expression(expression: str) -> pd.Series:
    """
    Parse a LEAP Data() expression string into a pd.Series indexed by year.

    Args:
        expression: String like 'Data(2022, 0, 2023, 100.0, ...)'.
            Can also handle empty or constant expressions.

    Returns:
        pd.Series indexed by integer year.

    Raises:
        ValueError: If the expression cannot be parsed.
    """
    if not expression or not isinstance(expression, str):
        return pd.Series(dtype=float)

    expr = expression.strip()

    # Handle LEAP constant: just a number
    if re.match(r"^-?\d+(\.\d+)?([eE][+-]?\d+)?$", expr):
        return pd.Series(dtype=float)  # constant — no year-indexed data

    # Handle Data(...) format
    match = re.match(r"Data\((.+)\)", expr, re.IGNORECASE)
    if not match:
        raise ValueError(f"Cannot parse LEAP expression: {expression!r}")

    tokens = [t.strip() for t in match.group(1).split(",")]
    if len(tokens) % 2 != 0:
        raise ValueError(f"Odd number of tokens in expression: {expression!r}")

    years = []
    values = []
    for i in range(0, len(tokens), 2):
        years.append(int(float(tokens[i])))
        values.append(float(tokens[i + 1]))

    return pd.Series(values, index=years, dtype=float)


def parse_expression_column(df: pd.DataFrame, expression_col: str = "Expression") -> pd.DataFrame:
    """
    Expand a DataFrame with a LEAP Expression column into tidy long format.

    Input DataFrame must have at minimum: Expression, plus any metadata columns.
    Returns a new DataFrame with a 'year' and 'value' column for each expression row.

    Args:
        df: DataFrame with Expression column.
        expression_col: Name of the expression column.

    Returns:
        Tidy DataFrame with one row per (original_row × year).
    """
    meta_cols = [c for c in df.columns if c != expression_col]
    rows = []
    for _, row in df.iterrows():
        try:
            series = from_leap_expression(row[expression_col])
        except (ValueError, TypeError):
            continue
        for year, value in series.items():
            record = {col: row[col] for col in meta_cols}
            record["year"] = year
            record["value"] = value
            rows.append(record)
    return pd.DataFrame(rows)
