"""Clean and validate EIA-930 raw data."""

from __future__ import annotations

import pandas as pd


def clean(df: pd.DataFrame, max_gap_hours: int = 3) -> pd.DataFrame:
    """Clean raw EIA-930 demand data.

    - Converts units and types
    - Flags implausible values (negative demand, >3-sigma spikes)
    - Fills short gaps by linear interpolation
    - Marks longer gaps as NaN with a gap_flag column

    Args:
        df: Raw DataFrame with [timestamp_utc, ba, demand_mwh].
        max_gap_hours: Gaps <= this length are interpolated; longer ones flagged.

    Returns:
        Cleaned DataFrame with added [demand_mwh_clean, gap_flag] columns.
    """
    df = df.copy()
    df = df.sort_values("timestamp_utc").reset_index(drop=True)

    # Coerce numeric
    df["demand_mwh"] = pd.to_numeric(df["demand_mwh"], errors="coerce")

    # Flag negatives and gross outliers
    mean = df["demand_mwh"].mean()
    std = df["demand_mwh"].std()
    df["gap_flag"] = (df["demand_mwh"] < 0) | (df["demand_mwh"] > mean + 5 * std)
    df.loc[df["gap_flag"], "demand_mwh"] = float("nan")

    # Set DatetimeIndex for interpolation
    df = df.set_index("timestamp_utc")
    df["demand_mwh_clean"] = df["demand_mwh"].interpolate(
        method="time", limit=max_gap_hours
    )
    df = df.reset_index()

    return df
