"""Acquire reproducible hourly PJM-area temperature proxy from Open-Meteo archive.

Run:
    python -m gridregime.pipeline.fetch_pjm_weather

Uses historical gridded/reanalysis temperatures, NOT NOAA station observations,
NOT a load-weighted PJM temperature and NOT point-in-time weather forecasts.
Four fixed locations with equal weights are a preliminary regional proxy.
Coverage is validated for 2021 and event windows; missing periods fail loudly.
Source: https://open-meteo.com/en/docs/historical-weather-api
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[3]
DEST = ROOT / "data/processed/weather/pjm_temperature_hourly.csv"
PROVENANCE = DEST.with_suffix(".provenance.json")
API = "https://archive-api.open-meteo.com/v1/archive"
# Representative cities only; NOT a verified PJM demand-weighted aggregate.
SITES = {
    "pittsburgh_pa": (40.44, -79.99),
    "philadelphia_pa": (39.95, -75.16),
    "columbus_oh": (39.96, -83.00),
    "washington_dc": (38.90, -77.04),
}


def retrieve(session, site, latitude, longitude, start, end):
    response = session.get(API, params={
        "latitude": latitude, "longitude": longitude,
        "start_date": start, "end_date": end,
        "hourly": "temperature_2m", "temperature_unit": "fahrenheit",
        "timezone": "UTC", "models": "era5",
    }, timeout=120)
    response.raise_for_status()
    payload = response.json()
    if "hourly" not in payload:
        raise RuntimeError(f"{site}: missing hourly data: {payload}")
    h = payload["hourly"]
    df = pd.DataFrame({
        "timestamp_utc": pd.to_datetime(h["time"], utc=True),
        site: pd.to_numeric(h["temperature_2m"], errors="coerce"),
    })
    if df["timestamp_utc"].duplicated().any():
        raise ValueError(f"{site}: duplicate timestamps")
    return df


def run():
    events = pd.read_csv(ROOT / "metadata/events.csv")
    required = ["window_start", "event_end"]
    if any(c not in events for c in required):
        raise ValueError("metadata/events.csv must contain window_start and event_end")
    start = min(pd.Timestamp("2021-01-01", tz="UTC"),
                pd.to_datetime(events["window_start"], utc=True).min()).floor("D")
    end = max(pd.Timestamp("2021-12-31", tz="UTC"),
              pd.to_datetime(events["event_end"], utc=True).max()).ceil("D")
    # The archive may not yet have recent ERA5 observations.
    if end > pd.Timestamp.now(tz="UTC").floor("D"):
        raise ValueError(f"Event coverage extends into the future: {end}")
    frames = []
    with requests.Session() as session:
        for site,(lat,lon) in SITES.items():
            chunks=[]
            for year in range(start.year,end.year+1):
                lo=max(start,pd.Timestamp(f"{year}-01-01",tz="UTC"))
                hi=min(end,pd.Timestamp(f"{year}-12-31",tz="UTC"))
                if lo>hi:
                    continue
                print(f"Fetching {site} {lo.date()}–{hi.date()}",flush=True)
                chunks.append(retrieve(session,site,lat,lon,
                                       str(lo.date()),str(hi.date())))
            frames.append(pd.concat(chunks,ignore_index=True).set_index("timestamp_utc"))
    all_sites=pd.concat(frames,axis=1,join="outer").sort_index()
    expected=pd.date_range(start=start,end=end+pd.Timedelta(hours=23),freq="h",tz="UTC")
    all_sites=all_sites.reindex(expected)
    missing=all_sites.isna().sum()
    if missing.any():
        raise ValueError(f"Weather source incomplete; per-site missing hours: {missing.to_dict()}. "
                         "Do not interpolate across missing observations.")
    result=pd.DataFrame({
        "timestamp_utc":expected,
        "temperature_f":all_sites.mean(axis=1).to_numpy(dtype=float),
    })
    if not np.isfinite(result["temperature_f"]).all():
        raise ValueError("Nonfinite temperature data")
    DEST.parent.mkdir(parents=True,exist_ok=True)
    result.to_csv(DEST,index=False,date_format="%Y-%m-%dT%H:%M:%SZ")
    PROVENANCE.write_text(json.dumps({
        "source":"Open-Meteo Historical Weather API",
        "url":API,"model":"ERA5 reanalysis",
        "variable":"temperature_2m","unit":"fahrenheit","timezone":"UTC",
        "locations":{k:{"latitude":lat,"longitude":lon,"weight":0.25}
                     for k,(lat,lon) in SITES.items()},
        "aggregation":"arithmetic mean of four equally weighted grid cells",
        "limitations":[
            "Not NOAA direct station observations",
            "Not PJM load-weighted or calibrated to PJM demand geography",
            "ERA5 reanalysis is retrospective and not available point-in-time",
            "Weather from archive may lag the most recent event windows",
            "The trailing 24-hour average is applied downstream",
        ],
        "coverage_start":str(expected[0]),"coverage_end":str(expected[-1]),
        "hours":len(result),
    },indent=2)+"\n")
    print(f"Saved {len(result)} hours to {DEST}")
    print(f"Provenance: {PROVENANCE}")
    return result


if __name__=="__main__":
    run()
