"""Timestamp normalization utilities."""

from __future__ import annotations

import pandas as pd


def to_utc_hourly(df: pd.DataFrame, col: str = "timestamp") -> pd.DataFrame:
    """Normalize a timestamp column to UTC, hour-ending, with no duplicates.

    Args:
        df: Input DataFrame.
        col: Name of the timestamp column.

    Returns:
        DataFrame with `col` as UTC DatetimeTZDtype, duplicates removed.
    """
    df = df.copy()
    df[col] = pd.to_datetime(df[col], utc=True)
    df[col] = df[col].dt.floor("h")
    df = df.drop_duplicates(subset=[col])
    return df.sort_values(col).reset_index(drop=True)


def assert_no_gaps(df: pd.DataFrame, col: str = "timestamp_utc") -> None:
    """Raise if the hourly time series has any gaps."""
    diffs = df[col].diff().dropna()
    one_hour = pd.Timedelta("1h")
    gaps = diffs[diffs != one_hour]
    if not gaps.empty:
        raise ValueError(f"Time series has {len(gaps)} gap(s): {gaps.index.tolist()[:5]}")
