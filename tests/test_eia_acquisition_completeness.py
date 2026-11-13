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


def test_isolated_sentinel_interpolated_with_audit():
    from gridregime.pipeline.milestone_1a import clean_isolated_sentinels
    raw = month().iloc[:5].copy().reset_index(drop=True)
    raw.loc[2, "demand_mwh"] = -99999
    raw.loc[1, "demand_mwh"] = 94767
    raw.loc[3, "demand_mwh"] = 104129
    clean = clean_isolated_sentinels(raw)
    assert clean.loc[2, "demand_mwh"] == 99448
    assert bool(clean.loc[2, "demand_mwh_imputed"])
    assert clean.loc[2, "demand_mwh_source_value"] == -99999
    assert raw.loc[2, "demand_mwh"] == -99999


def test_adjacent_sentinels_are_not_interpolated():
    from gridregime.pipeline.milestone_1a import clean_isolated_sentinels
    raw = month().iloc[:5].copy().reset_index(drop=True)
    raw.loc[[2, 3], "demand_mwh"] = -99999
    clean = clean_isolated_sentinels(raw)
    assert clean.loc[[2, 3], "demand_mwh"].isna().all()
    assert has_failures(validate(clean, "TEST"))


def test_plausible_99999_demand_preserved():
    from gridregime.pipeline.milestone_1a import clean_isolated_sentinels
    raw = month().iloc[:5].copy().reset_index(drop=True)
    raw.loc[2, "demand_mwh"] = 99999
    cleaned = clean_isolated_sentinels(raw)
    assert cleaned.loc[2, "demand_mwh"] == 99999
    assert not has_failures(validate(cleaned, "TEST"))
