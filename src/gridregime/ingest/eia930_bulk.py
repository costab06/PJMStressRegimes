"""Ingest EIA-930 historical balance data from semi-annual bulk CSV downloads.

The EIA v2 API provides PJM data only from 2019-01-01 onward. For pre-2019
events (e.g. C2018_COLD) the source is the semi-annual bulk balance CSVs:

    https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/
        EIA930_BALANCE_{YYYY}_{Jan_Jun|Jul_Dec}.csv

The file list is published at:
    https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_File_List_Meta.csv

Each CSV contains one row per (BA, hour). The column layout has changed slightly
across releases; this module handles the known layouts and raises a descriptive
error for any unrecognised format.

Typical usage:
    from gridregime.ingest.eia930_bulk import fetch_window_bulk
    df = fetch_window_bulk("PJM", "2017-12-30T00", "2018-01-11T23")

The returned DataFrame has the same schema as eia930.fetch_window():
    timestamp_utc, ba, demand_mwh, forecast_mwh, generation_mwh, interchange_mwh

Caching: each downloaded CSV is kept in data/raw/eia930/bulk/ and cached as a
parquet file (same key scheme as the API path). Re-runs skip already-downloaded
files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd
import requests

BULK_BASE_URL = "https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/"
BULK_DIR = Path("data/raw/eia930/bulk")

# Known column-name variants across EIA-930 bulk file releases.
# Maps canonical name → list of aliases found in the wild.
_COL_ALIASES: dict[str, list[str]] = {
    "timestamp_raw": [
        "UTC Time at End of Hour",       # current format (2015-present)
        "UTC_TIME_AT_END_OF_HOUR",       # older underscore variant
        "Data Date",
    ],
    "respondent": [
        "Balancing Authority",           # current format (2015-present)
        "RESPONDENT",
        "Respondent",
        "BA",
    ],
    "demand_mwh": [
        "Demand (MW)",
        "DEMAND (MW)",
        "D",
    ],
    "forecast_mwh": [
        "Demand Forecast (MW)",
        "DEMAND_FORECAST (MW)",
        "DAY_AHEAD_DEMAND_FORECAST (MW)",
        "Day-Ahead Demand Forecast (MW)",
        "DF",
    ],
    "generation_mwh": [
        "Net Generation (MW)",
        "NET_GENERATION (MW)",
        "NG",
    ],
    "interchange_mwh": [
        "Total Interchange (MW)",
        "TOTAL_INTERCHANGE (MW)",
        "TI",
    ],
}


def _bulk_filename(year: int, period: str) -> str:
    """Return the EIA bulk CSV filename for a given year and period."""
    return f"EIA930_BALANCE_{year}_{period}.csv"


def _period_for_month(month: int) -> str:
    return "Jan_Jun" if month <= 6 else "Jul_Dec"


def _months_needed(t0: pd.Timestamp, t1: pd.Timestamp) -> list[tuple[int, str]]:
    """Return list of (year, period) tuples covering the window."""
    needed: list[tuple[int, str]] = []
    cur_year = t0.year
    cur_month = t0.month
    while True:
        period = _period_for_month(cur_month)
        entry = (cur_year, period)
        if entry not in needed:
            needed.append(entry)
        if cur_month == 12:
            cur_year += 1
            cur_month = 1
        else:
            cur_month += 1
        if cur_year > t1.year or (cur_year == t1.year and cur_month > t1.month):
            break
    return needed


def _download_csv(year: int, period: str, bulk_dir: Path) -> Path:
    """Download a bulk CSV if not already cached; return path to local file."""
    filename = _bulk_filename(year, period)
    local_path = bulk_dir / filename
    if local_path.exists():
        return local_path

    url = BULK_BASE_URL + filename
    print(f"  Downloading {url} ...")
    resp = requests.get(url, timeout=300, stream=True)
    if resp.status_code == 404:
        raise FileNotFoundError(
            f"Bulk file not found at EIA: {url}\n"
            f"Check that {year} {period} data exists at {BULK_BASE_URL}"
        )
    resp.raise_for_status()
    # Guard: EIA serves an HTML stub (20 bytes) for unknown paths
    content = resp.content
    if len(content) < 200 or content[:9] == b"<!doctype":
        raise FileNotFoundError(
            f"EIA returned HTML instead of CSV for {url}. "
            f"The file may not exist or the URL format has changed."
        )
    local_path.write_bytes(content)
    print(f"  Saved → {local_path}  ({len(content):,} bytes)")
    return local_path


def _resolve_column(df: pd.DataFrame, canonical: str) -> Optional[str]:
    """Return the actual column name in df that matches the canonical name."""
    for alias in _COL_ALIASES[canonical]:
        if alias in df.columns:
            return alias
    return None


def _parse_bulk_csv(csv_path: Path, ba: str) -> pd.DataFrame:
    """Parse the balance CSV for one BA.

    Returns:
        DataFrame with columns [timestamp_utc, ba, demand_mwh, forecast_mwh,
        generation_mwh, interchange_mwh], filtered to the requested BA.
    """
    raw = pd.read_csv(csv_path, low_memory=False)

    # Resolve timestamp column
    ts_col = _resolve_column(raw, "timestamp_raw")
    if ts_col is None:
        raise ValueError(
            f"Cannot find timestamp column in {csv_path.name}. "
            f"Available columns: {list(raw.columns[:10])}. "
            f"Expected one of: {_COL_ALIASES['timestamp_raw']}"
        )

    # Resolve BA / respondent column
    ba_col = _resolve_column(raw, "respondent")
    if ba_col is None:
        raise ValueError(
            f"Cannot find respondent column in {csv_path.name}. "
            f"Available: {list(raw.columns[:10])}"
        )

    # Filter to requested BA immediately to reduce memory pressure
    df = raw[raw[ba_col].astype(str).str.strip() == ba].copy()
    if df.empty:
        raise ValueError(
            f"BA '{ba}' not found in {csv_path.name}. "
            f"Sample respondents: {raw[ba_col].dropna().unique()[:10].tolist()}"
        )

    # Parse timestamp — bulk files use hour-ending UTC strings
    df["timestamp_utc"] = pd.to_datetime(df[ts_col], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp_utc"])

    # Map data columns
    out = pd.DataFrame({"timestamp_utc": df["timestamp_utc"], "ba": ba})
    for canonical in ["demand_mwh", "forecast_mwh", "generation_mwh", "interchange_mwh"]:
        src = _resolve_column(df, canonical)
        if src is not None:
            out[canonical] = pd.to_numeric(df[src].values, errors="coerce")
        else:
            out[canonical] = float("nan")

    return out.sort_values("timestamp_utc").reset_index(drop=True)


def fetch_window_bulk(
    ba: str,
    start: str,
    end: str,
    bulk_dir: Path = BULK_DIR,
) -> pd.DataFrame:
    """Fetch and merge EIA-930 bulk data for a window, with per-period caching.

    Downloads the semi-annual CSV files as needed, parses the BA rows,
    caches as parquet (one file per year+period under bulk_dir), and trims
    to [start, end].

    Args:
        ba: EIA balance authority code (e.g. "PJM").
        start: ISO-8601 UTC start string (e.g. "2017-12-30T00").
        end: ISO-8601 UTC end string (e.g. "2018-01-11T23").
        bulk_dir: Directory for CSV downloads and parquet cache.

    Returns:
        DataFrame with columns [timestamp_utc, ba, demand_mwh, forecast_mwh,
        generation_mwh, interchange_mwh].
    """
    bulk_dir = Path(bulk_dir)
    bulk_dir.mkdir(parents=True, exist_ok=True)

    t0 = pd.Timestamp(start, tz="UTC")
    t1 = pd.Timestamp(end, tz="UTC")
    periods = _months_needed(t0, t1)

    period_dfs: list[pd.DataFrame] = []
    for year, period in periods:
        cache_path = bulk_dir / f"{ba}_{year}_{period}.parquet"
        if cache_path.exists():
            print(f"  Bulk cache hit: {cache_path.name}")
            period_dfs.append(pd.read_parquet(cache_path))
            continue

        csv_path = _download_csv(year, period, bulk_dir)
        print(f"  Parsing {csv_path.name} for BA={ba} ...")
        df = _parse_bulk_csv(csv_path, ba)

        if df.empty:
            print(f"  Warning: no rows for {ba} in {csv_path.name}")
            continue

        df.to_parquet(cache_path, index=False)
        print(f"  Cached → {cache_path.name}  ({len(df)} rows)")
        period_dfs.append(df)

    if not period_dfs:
        raise RuntimeError(f"No bulk data retrieved for {ba} {start}–{end}")

    full = pd.concat(period_dfs, ignore_index=True)
    full = full.drop_duplicates("timestamp_utc").sort_values("timestamp_utc")
    return full[(full["timestamp_utc"] >= t0) & (full["timestamp_utc"] <= t1)].reset_index(drop=True)
