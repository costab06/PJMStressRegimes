"""Weather-based features."""

from __future__ import annotations

import numpy as np
import pandas as pd


def heating_degree_hours(temp_c: pd.Series, base_c: float = 18.0) -> pd.Series:
    """Hourly heating degree-hours relative to base temperature."""
    return (base_c - temp_c).clip(lower=0)


def cooling_degree_hours(temp_c: pd.Series, base_c: float = 18.0) -> pd.Series:
    """Hourly cooling degree-hours relative to base temperature."""
    return (temp_c - base_c).clip(lower=0)


def wind_chill(temp_c: pd.Series, wind_speed_mps: pd.Series) -> pd.Series:
    """Environment Canada wind chill index (valid for T <= 10°C, V >= 1.3 m/s)."""
    v_kmh = wind_speed_mps * 3.6
    wc = (
        13.12
        + 0.6215 * temp_c
        - 11.37 * v_kmh**0.16
        + 0.3965 * temp_c * v_kmh**0.16
    )
    return wc.where((temp_c <= 10) & (v_kmh >= 4.8), other=temp_c)


def temp_deviation(temp_c: pd.Series, clim_mean: pd.Series) -> pd.Series:
    """Temperature deviation from climatological normal."""
    return temp_c - clim_mean
