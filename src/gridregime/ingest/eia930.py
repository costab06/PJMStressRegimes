"""Ingest EIA-930 hourly grid monitor data via the EIA API v2.

EIA-930 region-data endpoint type codes used here:
  D   — Demand (actual metered)
  DF  — Day-ahead demand forecast
  NG  — Net generation (all fuels)
  TI  — Total net interchange

Fuel-level generation uses the separate fuel-type endpoint:
  /electricity/rto/fuel-type-data/data/
  fuel types: COL, NG, NUC, OIL, OTH, SUN, WAT, WND

All timestamps returned by the API are local-prevailing-time strings; this
module converts everything to UTC before returning.

Caching: fetch_window() writes one parquet per (ba, type, month) under
data/raw/eia930/. Re-running skips months that are already on disk.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Literal

import pandas as pd
import requests

EIA_API_URL = "https://api.eia.gov/v2/electricity/rto/"
RAW_PATH = Path("data/raw/eia930")

# EIA type codes for region-data endpoint
RegionType = Literal["D", "DF", "NG", "TI"]

# EIA fuel type codes
FUEL_TYPES = ["COL", "NG", "NUC", "OIL", "OTH", "SUN", "WAT", "WND"]


def _api_key() -> str:
    key = os.environ.get("EIA_API_KEY", "")
    if not key:
        raise EnvironmentError("EIA_API_KEY environment variable not set")
    return key


# ---------------------------------------------------------------------------
# Low-level paginated fetch
# ---------------------------------------------------------------------------

def _paginate(url: str, params: dict, page_size: int = 5000) -> list[dict]:
    """Fetch all pages from an EIA v2 endpoint."""
    rows: list[dict] = []
    offset = 0
    while True:
        resp = requests.get(url, params={**params, "offset": offset, "length": page_size}, timeout=30)
        resp.raise_for_status()
        page = resp.json().get("response", {}).get("data", [])
        rows.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
        time.sleep(0.3)
    return rows


# ---------------------------------------------------------------------------
# Single-type fetches
# ---------------------------------------------------------------------------

def fetch_region_type(
    ba: str,
    data_type: RegionType,
    start: str,
    end: str,
) -> pd.DataFrame:
    """Fetch one region-data type series for a balance authority.

    Args:
        ba: EIA balance authority code (e.g. "PJM").
        data_type: One of D, DF, NG, TI.
        start: ISO-8601 UTC start (e.g. "2022-12-20T00").
        end: ISO-8601 UTC end.

    Returns:
        DataFrame with columns [timestamp_utc, ba, <col>] where col is
        demand_mwh, forecast_mwh, generation_mwh, or interchange_mwh.
    """
    col_map: dict[str, str] = {
        "D": "demand_mwh",
        "DF": "forecast_mwh",
        "NG": "generation_mwh",
        "TI": "interchange_mwh",
    }
    params = {
        "api_key": _api_key(),
        "data[]": "value",
        "facets[respondent][]": ba,
        "facets[type][]": data_type,
        "start": start,
        "end": end,
        "frequency": "hourly",
        "sort[0][column]": "period",
        "sort[0][direction]": "asc",
    }
    rows = _paginate(EIA_API_URL + "region-data/data/", params)
    if not rows:
        return pd.DataFrame(columns=["timestamp_utc", "ba", col_map[data_type]])

    df = pd.DataFrame(rows)
    df["timestamp_utc"] = pd.to_datetime(df["period"], utc=True)
    df["ba"] = ba
    df = df.rename(columns={"value": col_map[data_type]})
    df[col_map[data_type]] = pd.to_numeric(df[col_map[data_type]], errors="coerce")
    return df[["timestamp_utc", "ba", col_map[data_type]]].sort_values("timestamp_utc").reset_index(drop=True)


def fetch_generation_by_fuel(
    ba: str,
    start: str,
    end: str,
) -> pd.DataFrame:
    """Fetch hourly net generation broken out by fuel type.

    Returns:
        DataFrame with columns [timestamp_utc, ba, gen_COL, gen_NG, gen_NUC,
        gen_OIL, gen_OTH, gen_SUN, gen_WAT, gen_WND] (MWh each).
    """
    params = {
        "api_key": _api_key(),
        "data[]": "value",
        "facets[respondent][]": ba,
        "start": start,
        "end": end,
        "frequency": "hourly",
        "sort[0][column]": "period",
        "sort[0][direction]": "asc",
    }
    rows = _paginate(EIA_API_URL + "fuel-type-data/data/", params)
    if not rows:
        return pd.DataFrame(columns=["timestamp_utc", "ba"])

    df = pd.DataFrame(rows)
    df["timestamp_utc"] = pd.to_datetime(df["period"], utc=True)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["fuel_col"] = "gen_" + df["fueltype"].str.upper()

    wide = df.pivot_table(
        index="timestamp_utc", columns="fuel_col", values="value", aggfunc="sum"
    ).reset_index()
    wide["ba"] = ba
    # Ensure all standard fuel columns exist even if absent in the data
    for fuel in FUEL_TYPES:
        col = f"gen_{fuel}"
        if col not in wide.columns:
            wide[col] = float("nan")
    cols = ["timestamp_utc", "ba"] + [f"gen_{f}" for f in FUEL_TYPES]
    return wide[[c for c in cols if c in wide.columns]].sort_values("timestamp_utc").reset_index(drop=True)


# ---------------------------------------------------------------------------
# High-level: fetch and merge all series for a window, with monthly caching
# ---------------------------------------------------------------------------

def fetch_window(
    ba: str,
    start: str,
    end: str,
    cache_dir: Path = RAW_PATH,
    skip_generation: bool = False,
) -> pd.DataFrame:
    """Fetch and merge demand, forecast, interchange, and generation for a window.

    Results are cached as parquet files split by (ba, YYYY-MM) so that
    re-running a pipeline step doesn't re-hit the API for already-downloaded
    months. Only months not already on disk are fetched.

    Args:
        ba: EIA balance authority code.
        start: ISO-8601 UTC start string.
        end: ISO-8601 UTC end string.
        cache_dir: Root directory for cached parquet files.
        skip_generation: If True, omit fuel-type breakdown (faster).

    Returns:
        DataFrame with columns [timestamp_utc, ba, demand_mwh, forecast_mwh,
        generation_mwh, interchange_mwh, gen_COL, gen_NG, ...].
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    t0 = pd.Timestamp(start, tz="UTC")
    t1 = pd.Timestamp(end, tz="UTC")

    # Determine which months are needed and which are already cached
    months = pd.date_range(t0.floor("D"), t1.ceil("D"), freq="MS", tz="UTC")
    if len(months) == 0:
        months = pd.DatetimeIndex([t0.floor("MS")])

    month_dfs: list[pd.DataFrame] = []
    for month_start in months:
        month_end = month_start + pd.offsets.MonthEnd(1) + pd.Timedelta(hours=23)
        cache_path = cache_dir / f"{ba}_{month_start.strftime('%Y-%m')}.parquet"
        if cache_path.exists():
            month_dfs.append(pd.read_parquet(cache_path))
            continue

        # Fetch all types for this month
        fetch_start = month_start.strftime("%Y-%m-%dT%H")
        fetch_end = month_end.strftime("%Y-%m-%dT%H")

        region_dfs = []
        for dtype in ("D", "DF", "NG", "TI"):
            try:
                region_dfs.append(fetch_region_type(ba, dtype, fetch_start, fetch_end))
            except Exception as exc:
                print(f"  Warning: {ba} {dtype} {month_start.date()} failed: {exc}")

        if not region_dfs:
            continue

        merged = region_dfs[0]
        for rdf in region_dfs[1:]:
            merged = merged.merge(rdf, on=["timestamp_utc", "ba"], how="outer")

        if not skip_generation:
            try:
                gen_df = fetch_generation_by_fuel(ba, fetch_start, fetch_end)
                merged = merged.merge(gen_df, on=["timestamp_utc", "ba"], how="outer")
            except Exception as exc:
                print(f"  Warning: {ba} fuel-type {month_start.date()} failed: {exc}")

        merged = merged.sort_values("timestamp_utc").reset_index(drop=True)
        merged.to_parquet(cache_path, index=False)
        month_dfs.append(merged)

    if not month_dfs:
        raise RuntimeError(f"No data retrieved for {ba} {start}–{end}")

    full = pd.concat(month_dfs, ignore_index=True)
    full = full.drop_duplicates("timestamp_utc").sort_values("timestamp_utc")
    # Trim to the requested window
    return full[(full["timestamp_utc"] >= t0) & (full["timestamp_utc"] <= t1)].reset_index(drop=True)


def load_cached_month(ba: str, year: int, month: int, cache_dir: Path = RAW_PATH) -> pd.DataFrame:
    """Load a previously-cached monthly parquet file."""
    path = Path(cache_dir) / f"{ba}_{year:04d}-{month:02d}.parquet"
    return pd.read_parquet(path)
