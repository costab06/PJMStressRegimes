"""Regression tests for incomplete EIA cache and missing mandatory source series."""
import pandas as pd
import pytest
from gridregime.ingest.eia930 import _require_complete_month
from gridregime.clean.validate import validate, has_failures
from gridregime.pipeline.milestone_1a import compute_coverage


def month():
    times = pd.date_range("2025-06-01T00:00Z", "2025-06-30T23:00Z", freq="h")
    return pd.DataFrame({"timestamp_utc": times, "ba": "PJM",
                         "demand_mwh": 100000.0, "forecast_mwh": 101000.0,
                         "interchange_mwh": 2000.0})


def test_complete_month_and_missing_interchange():
    df = month()
    _require_complete_month(df, df.timestamp_utc.min(), df.timestamp_utc.max())
    with pytest.raises(ValueError, match="Missing required"):
        _require_complete_month(df.drop(columns="interchange_mwh"),
                                df.timestamp_utc.min(), df.timestamp_utc.max())
    with pytest.raises(ValueError, match="Null mandatory"):
        _require_complete_month(df.assign(interchange_mwh=float("nan")),
                                df.timestamp_utc.min(), df.timestamp_utc.max())


def test_partial_source_is_validation_failure():
    df = month().drop(columns="forecast_mwh")
    assert has_failures(validate(df, "TEST"))


def test_coverage_requires_all_three_columns():
    df = month().iloc[:24].drop(columns="interchange_mwh")
    event = pd.Series({"event_id":"TEST", "window_start":pd.Timestamp("2025-06-04T00:00Z"),
                       "event_end":pd.Timestamp("2025-06-04T23:00Z")})
    from gridregime.pipeline import milestone_1a
    original_pre, original_post = milestone_1a.PRE_HOURS, milestone_1a.POST_HOURS
    try:
        milestone_1a.PRE_HOURS = milestone_1a.POST_HOURS = 0
        result = compute_coverage(df, event)
    finally:
        milestone_1a.PRE_HOURS, milestone_1a.POST_HOURS = original_pre, original_post
    assert result["missing_pct"] == 100.0
