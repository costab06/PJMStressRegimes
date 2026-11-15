"""Small deterministic tests for the reader-facing demo."""
import pandas as pd
import pytest
from gridregime.demo import analyze, validate


def sample():
    return pd.DataFrame({
        "timestamp_utc": pd.to_datetime([
            "2026-07-02T20:00:00Z", "2026-07-02T21:00:00Z",
            "2026-07-02T22:00:00Z",
        ]),
        "demand_mwh": [100000.0, 101000.0, 102000.0],
        "forecast_mwh": [100000.0, 100000.0, 100000.0],
        "interchange_mwh": [-500.0, -500.0, -500.0],
    })


def test_analysis_is_transparent():
    result = analyze(validate(sample()))
    assert result["observed_hours"] == 3
    assert result["peak_demand_mwh"] == 102000
    assert result["maximum_hourly_demand_increase_mwh"] == 1000
    assert result["mean_absolute_forecast_error_pct"] == pytest.approx(1)


def test_duplicate_hour_fails_closed():
    raw = pd.concat([sample(), sample().iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="Duplicate"):
        validate(raw)


def test_missing_measurement_fails_closed():
    with pytest.raises(ValueError, match="Missing required"):
        validate(sample().drop(columns="forecast_mwh"))
