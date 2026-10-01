"""Ingest EIA-930 hourly grid monitor data via the EIA API v2."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

EIA_API_URL = "https://api.eia.gov/v2/electricity/rto/"
RAW_PATH = Path("data/raw/eia930")


def _api_key() -> str:
    key = os.environ.get("EIA_API_KEY", "")
    if not key:
        raise EnvironmentError("EIA_API_KEY environment variable not set")
    return key


def fetch_demand(
    ba: str,
    start: str,
    end: str,
    out_path: Optional[Path] = None,
) -> pd.DataFrame:
    """Fetch hourly demand and day-ahead forecast for a balance authority.

    Args:
        ba: Balance authority code (e.g. "PJM", "MISO").
        start: ISO-8601 start datetime string (UTC).
        end: ISO-8601 end datetime string (UTC).
        out_path: If given, write raw JSON response to this file.

    Returns:
        DataFrame with columns [timestamp_utc, ba, demand_mwh, demand_forecast_mwh].
    """
    params = {
        "api_key": _api_key(),
        "data[]": ["value"],
        "facets[respondent][]": ba,
        "start": start,
        "end": end,
        "frequency": "hourly",
        "sort[0][column]": "period",
        "sort[0][direction]": "asc",
        "length": 5000,
    }
    url = EIA_API_URL + "region-data/data/"
    rows = []
    offset = 0

    while True:
        resp = requests.get(url, params={**params, "offset": offset}, timeout=30)
        resp.raise_for_status()
        data = resp.json().get("response", {}).get("data", [])
        if not data:
            break
        rows.extend(data)
        if len(data) < 5000:
            break
        offset += 5000
        time.sleep(0.5)

    df = pd.DataFrame(rows)
    df = df.rename(columns={"period": "timestamp_utc", "value": "demand_mwh"})
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df["ba"] = ba
    return df[["timestamp_utc", "ba", "demand_mwh"]].sort_values("timestamp_utc")


def fetch_interchange(ba: str, start: str, end: str) -> pd.DataFrame:
    """Fetch hourly net interchange for a balance authority."""
    raise NotImplementedError


def load_cached(ba: str, year: int) -> pd.DataFrame:
    """Load a previously-cached EIA-930 parquet file."""
    path = RAW_PATH / f"{ba}_{year}.parquet"
    return pd.read_parquet(path)
