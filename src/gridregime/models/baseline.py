"""Seasonal decomposition baseline model."""

from __future__ import annotations

import numpy as np
import pandas as pd
from statsmodels.tsa.seasonal import seasonal_decompose, STL


def fit_stl(series: pd.Series, period: int = 8760, **kwargs) -> object:
    """Fit STL decomposition to a hourly series.

    Args:
        series: Hourly time series with DatetimeIndex.
        period: Seasonality period in hours (default: annual).

    Returns:
        Fitted STLForecast result.
    """
    result = STL(series, period=period, **kwargs).fit()
    return result


def residuals(series: pd.Series, period: int = 8760) -> pd.Series:
    """Return STL residuals (actual minus trend minus seasonal)."""
    result = fit_stl(series, period=period)
    return result.resid
