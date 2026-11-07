"""Regression checks for the historical EIA-930 equivalence command.

No external API or Redis required; the same cached-style source frame is used
on both sides of the adapter boundary.
"""
import pandas as pd
import pytest

from gridregime.oaf import compare_historical


def sample():
    return pd.DataFrame({
        "timestamp_utc": pd.to_datetime(
            ["2022-12-20T00:00Z", "2022-12-20T01:00Z"], utc=True
        ),
        "ba": ["PJM", "PJM"],
        "demand_mwh": [100.125, 101.375],
        "forecast_mwh": [99.25, 100.5],
        "generation_mwh": [105.0, 106.0],
        "interchange_mwh": [-2.5, -3.5],
    })


def test_historical_comparison_preserves_values(monkeypatch, tmp_path):
    calls = []
    def cached_fetch(ba, start, end):
        calls.append((ba, start, end))
        return sample().copy()
    monkeypatch.setattr(compare_historical, "fetch_window", cached_fetch)
    result = compare_historical.compare_window(
        "PJM", "2022-12-20T00", "2022-12-20T01", tmp_path
    )
    assert result["rows"] == 2
    assert len(result["sha256"]) == 64
    assert len(calls) == 1


def test_historical_comparison_rejects_incomplete_source(monkeypatch, tmp_path):
    def incomplete(ba, start, end):
        return sample().iloc[:1].copy()
    monkeypatch.setattr(compare_historical, "fetch_window", incomplete)
    with pytest.raises(ValueError, match="hourly coverage mismatch"):
        compare_historical.compare_window(
            "PJM", "2022-12-20T00", "2022-12-20T01", tmp_path
        )
