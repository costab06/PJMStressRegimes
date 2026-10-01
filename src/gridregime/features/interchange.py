"""Interchange-based features."""

from __future__ import annotations

import pandas as pd


def interchange_anomaly(df: pd.DataFrame, window_days: int = 30) -> pd.Series:
    """Rolling z-score of net interchange vs. same-hour-of-week baseline."""
    df = df.set_index("timestamp_utc").sort_index()
    df["hour_of_week"] = df.index.dayofweek * 24 + df.index.hour
    result = pd.Series(index=df.index, dtype=float)
    for h, group in df.groupby("hour_of_week"):
        roll = group["interchange_mwh"].rolling(window=window_days, min_periods=7)
        result.loc[group.index] = (group["interchange_mwh"] - roll.mean()) / roll.std()
    return result
