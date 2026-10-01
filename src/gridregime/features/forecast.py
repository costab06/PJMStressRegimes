"""Forecast accuracy features."""

from __future__ import annotations

import pandas as pd


def forecast_error_zscore(df: pd.DataFrame, window_days: int = 30) -> pd.Series:
    """Rolling z-score of forecast error."""
    err = df["demand_mwh_clean"] - df["demand_forecast_mwh"]
    roll = err.rolling(window=window_days * 24, min_periods=7 * 24)
    return (err - roll.mean()) / roll.std()


def pct_error(df: pd.DataFrame) -> pd.Series:
    """Signed percent forecast error."""
    return (df["demand_mwh_clean"] - df["demand_forecast_mwh"]) / df["demand_forecast_mwh"] * 100
