"""Ingest NOAA ISD hourly weather observations."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

RAW_PATH = Path("data/raw/noaa")

QUALITY_CODES_OK = {"0", "1", "5"}


def fetch_isd_station(
    station_id: str,
    year: int,
    out_path: Optional[Path] = None,
) -> pd.DataFrame:
    """Download and parse ISD lite data for a station and year.

    Args:
        station_id: USAF-WBAN station identifier (e.g. "725030-14732").
        year: Calendar year to fetch.
        out_path: Directory to write raw file; defaults to RAW_PATH.

    Returns:
        DataFrame with columns [timestamp_utc, station_id, temp_c, dewpoint_c,
        wind_speed_mps, wind_dir_deg, precip_mm].
    """
    raise NotImplementedError


def load_cached(station_id: str, year: int) -> pd.DataFrame:
    """Load a previously-cached NOAA ISD parquet file."""
    path = RAW_PATH / f"{station_id}_{year}.parquet"
    return pd.read_parquet(path)
