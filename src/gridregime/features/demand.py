"""Demand-based features: z-scores, ramp rates, forecast error."""

from __future__ import annotations

import numpy as np
import pandas as pd


def demand_zscore(df: pd.DataFrame, window_days: int = 30) -> pd.Series:
    """Rolling z-score of hourly demand vs. same-hour-of-week baseline.

    Args:
        df: DataFrame with [timestamp_utc, demand_mwh_clean].
        window_days: Rolling window size for baseline statistics.

    Returns:
        Series of z-scores aligned to df index.
    """
    df = df.set_index("timestamp_utc").sort_index()
    # Group by hour-of-week to capture diurnal + weekly pattern
    df["hour_of_week"] = df.index.dayofweek * 24 + df.index.hour
    result = pd.Series(index=df.index, dtype=float)
    for h, group in df.groupby("hour_of_week"):
        roll = group["demand_mwh_clean"].rolling(window=window_days, min_periods=7)
        result.loc[group.index] = (group["demand_mwh_clean"] - roll.mean()) / roll.std()
    return result


def ramp_rate(df: pd.DataFrame, periods: int = 1) -> pd.Series:
    """Hour-over-hour ramp rate in MW/h."""
    return df["demand_mwh_clean"].diff(periods)


def forecast_error(df: pd.DataFrame) -> pd.Series:
    """Signed forecast error: actual - forecast."""
    return df["demand_mwh_clean"] - df["demand_forecast_mwh"]
