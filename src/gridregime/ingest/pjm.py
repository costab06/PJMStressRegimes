"""Ingest PJM Dataminer2 operational data."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

PJM_API_URL = "https://dataminer2.pjm.com/api/"
RAW_PATH = Path("data/raw/pjm")


def fetch_realtime_load(start: str, end: str) -> pd.DataFrame:
    """Fetch PJM real-time load by zone.

    Args:
        start: ISO-8601 start datetime (Eastern).
        end: ISO-8601 end datetime (Eastern).

    Returns:
        DataFrame with columns [timestamp_et, zone, load_mw].
    """
    raise NotImplementedError


def fetch_emergency_procedures(start: str, end: str) -> pd.DataFrame:
    """Fetch PJM emergency procedure declarations.

    Returns:
        DataFrame with columns [timestamp_et, procedure_type, description].
    """
    raise NotImplementedError


def load_cached(data_type: str, year: int) -> pd.DataFrame:
    """Load a previously-cached PJM parquet file."""
    path = RAW_PATH / f"{data_type}_{year}.parquet"
    return pd.read_parquet(path)
