"""Tests for feature engineering modules."""

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def hourly_df():
    idx = pd.date_range("2022-01-01", periods=24 * 60, freq="h", tz="UTC")
    rng = np.random.default_rng(0)
    return pd.DataFrame({
        "timestamp_utc": idx,
        "demand_mwh_clean": 10000 + rng.normal(0, 500, len(idx)),
        "demand_forecast_mwh": 10000 + rng.normal(0, 300, len(idx)),
        "interchange_mwh": rng.normal(0, 200, len(idx)),
    })


def test_ramp_rate_length(hourly_df):
    from gridregime.features.demand import ramp_rate
    result = ramp_rate(hourly_df)
    assert len(result) == len(hourly_df)
    assert pd.isna(result.iloc[0])


def test_forecast_error_zero_mean(hourly_df):
    from gridregime.features.demand import forecast_error
    err = forecast_error(hourly_df)
    assert err.abs().mean() < 1000


def test_heating_degree_hours_nonneg(hourly_df):
    from gridregime.features.weather import heating_degree_hours
    temps = pd.Series(np.linspace(-20, 30, len(hourly_df)))
    hdh = heating_degree_hours(temps)
    assert (hdh >= 0).all()


def test_demand_zscore_shape(hourly_df):
    from gridregime.features.demand import demand_zscore
    z = demand_zscore(hourly_df, window_days=7)
    assert len(z) == len(hourly_df)
