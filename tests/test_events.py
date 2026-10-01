"""Tests for event window and control matching."""

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def long_series():
    idx = pd.date_range("2018-01-01", periods=24 * 365 * 5, freq="h", tz="UTC")
    return pd.DataFrame({
        "timestamp_utc": idx,
        "demand_mwh_clean": np.random.default_rng(1).normal(10000, 500, len(idx)),
    })


def test_extract_window_length(long_series):
    from gridregime.events.windows import extract_window
    window = extract_window(
        long_series,
        "2022-12-23 00:00",
        "2022-12-26 23:00",
        pre_hours=72,
        post_hours=72,
    )
    # 72 + 4*24 + 72 hours = 240 hours
    assert len(window) == 240


def test_extract_window_has_hours_col(long_series):
    from gridregime.events.windows import extract_window
    window = extract_window(long_series, "2022-06-01", "2022-06-02", pre_hours=24, post_hours=24)
    assert "hours_to_event" in window.columns


def test_control_windows_count(long_series):
    from gridregime.events.controls import iter_control_windows
    controls = list(iter_control_windows(
        long_series,
        "2022-12-23 00:00",
        "2022-12-26 23:00",
        n_prior_years=3,
        pre_hours=24,
        post_hours=24,
    ))
    assert len(controls) == 3
