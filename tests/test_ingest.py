"""Tests for data ingestion modules."""

import pytest
import pandas as pd


def test_load_cached_eia930_missing(tmp_path):
    """load_cached_month raises FileNotFoundError for non-existent file."""
    import gridregime.ingest.eia930 as m
    with pytest.raises(FileNotFoundError):
        m.load_cached_month("PJM", 2022, 1, cache_dir=tmp_path)


def test_load_historical_empty(tmp_path):
    """load_event returns empty dict for empty event directory."""
    from gridregime.ingest import historical
    orig = historical.EVENTS
    historical.EVENTS = {"test_event": tmp_path}
    try:
        result = historical.load_event("test_event")
        assert result == {}
    finally:
        historical.EVENTS = orig
