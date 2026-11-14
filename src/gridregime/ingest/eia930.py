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
import random
from pathlib import Path
from typing import Literal

import pandas as pd
import requests

EIA_API_URL = "https://api.eia.gov/v2/electricity/rto/"
RAW_PATH = Path("data/raw/eia930")

# Earliest date for which the EIA v2 API has PJM (and most other BA) data.
# Requests before this date return 0 rows without error.
# Historical data pre-2019 requires the EIA bulk download files.
EIA_V2_START = pd.Timestamp("2019-01-01", tz="UTC")

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
        for attempt in range(5):
            try:
                resp = requests.get(url, params={**params, "offset": offset, "length": page_size}, timeout=90)
                resp.raise_for_status()
                page = resp.json().get("response", {}).get("data", [])
                break
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError,
                    requests.exceptions.HTTPError) as exc:
                if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None and exc.response.status_code not in (429, 500, 502, 503, 504):
                    raise
                if attempt == 4:
                    raise RuntimeError(f"EIA request failed after 5 attempts, offset={offset}") from exc
                time.sleep(min(2 ** attempt, 16) + random.uniform(0, 0.5))
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

def _require_complete_month(frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> None:
    """Reject partial cached months, including absent or null required series."""
    required = ("timestamp_utc", "demand_mwh", "forecast_mwh", "interchange_mwh")
    if any(c not in frame.columns for c in required):
        raise ValueError("Missing required source columns")
    ts = pd.to_datetime(frame["timestamp_utc"], utc=True)
    expected = pd.date_range(start, end, freq="h", tz="UTC")
    if ts.duplicated().any() or not pd.DatetimeIndex(ts.sort_values()).equals(expected):
        raise ValueError("Incomplete or duplicate hourly timestamps")
    if frame[list(required[1:])].isna().any().any():
        raise ValueError("Null mandatory source observations")
    if frame["forecast_mwh"].le(0).any():
        raise ValueError("Nonpositive demand forecast")


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

    if t1 < EIA_V2_START:
        # Entire window is pre-2019 — delegate entirely to the bulk path
        from gridregime.ingest.eia930_bulk import fetch_window_bulk
        print(f"  Pre-2019 window: routing to EIA bulk download path.")
        return fetch_window_bulk(ba, start, end, cache_dir / "bulk")
    if t0 < EIA_V2_START:
        # Partial overlap: fetch bulk for the pre-2019 portion, API for the rest,
        # then concatenate. In practice all current events are either fully pre-
        # or fully post-2019, so this branch is defensive.
        from gridregime.ingest.eia930_bulk import fetch_window_bulk
        split = EIA_V2_START.strftime("%Y-%m-%dT%H")
        print(f"  Window straddles EIA v2 start; fetching bulk for pre-{split} portion.")
        bulk_df = fetch_window_bulk(ba, start, split, cache_dir / "bulk")
        api_df = fetch_window(ba, split, end, cache_dir, skip_generation)
        combined = pd.concat([bulk_df, api_df], ignore_index=True)
        return combined.drop_duplicates("timestamp_utc").sort_values("timestamp_utc").reset_index(drop=True)

    # Build list of calendar months to fetch. pandas date_range with freq="MS"
    # raises ValueError on tz-aware inputs in pandas 2.x, so we iterate manually.
    # Start from the 1st of t0's month so we never miss the opening partial month.
    months: list[pd.Timestamp] = []
    cur = t0.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while cur <= t1:
        months.append(cur)
        next_month = cur.month % 12 + 1
        next_year = cur.year + (1 if cur.month == 12 else 0)
        cur = cur.replace(year=next_year, month=next_month)

    month_dfs: list[pd.DataFrame] = []
    for month_start in months:
        # Last hour of the month: advance to next month, back one hour
        next_m = month_start.month % 12 + 1
        next_y = month_start.year + (1 if month_start.month == 12 else 0)
        month_end = month_start.replace(year=next_y, month=next_m) - pd.Timedelta(hours=1)
        cache_path = cache_dir / f"{ba}_{month_start.strftime('%Y-%m')}.parquet"
        if cache_path.exists():
            cached = pd.read_parquet(cache_path)
            try:
                _require_complete_month(cached, month_start, month_end)
            except ValueError as exc:
                print(f"  Incomplete cache {cache_path.name}: {exc}; refetching")
            else:
                month_dfs.append(cached)
                continue

        # Fetch all types for this month
        fetch_start = month_start.strftime("%Y-%m-%dT%H")
        fetch_end = month_end.strftime("%Y-%m-%dT%H")

        region_dfs = []
        for dtype in ("D", "DF", "TI"):
            # These three sources are mandatory for the frozen-v1 vector.
            region_dfs.append(fetch_region_type(ba, dtype, fetch_start, fetch_end))
        merged = region_dfs[0]
        for rdf in region_dfs[1:]:
            merged = merged.merge(rdf, on=["timestamp_utc", "ba"], how="outer")
        if not skip_generation:
            try:
                gen = fetch_region_type(ba, "NG", fetch_start, fetch_end)
                merged = merged.merge(gen, on=["timestamp_utc", "ba"], how="left")
                fuel = fetch_generation_by_fuel(ba, fetch_start, fetch_end)
                merged = merged.merge(fuel, on=["timestamp_utc", "ba"], how="left")
            except Exception as exc:
                print(f"  Optional generation acquisition failed: {exc}")
        merged = merged.sort_values("timestamp_utc").reset_index(drop=True)
        _require_complete_month(merged, month_start, month_end)
        # Replace only after a fully validated replacement has been written.
        import tempfile
        with tempfile.NamedTemporaryFile(dir=cache_dir, suffix=".parquet", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            merged.to_parquet(tmp_path, index=False)
            os.replace(tmp_path, cache_path)
        finally:
            tmp_path.unlink(missing_ok=True)
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
