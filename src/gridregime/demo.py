"""A small, reproducible PJM event analysis for architecture readers.

Run: python -m gridregime.demo
Requires the existing local EIA-930 hourly parquet files for July 2026.
No anomaly model, training, or operational-risk prediction is involved.
"""
from __future__ import annotations

import json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/raw/eia930/PJM_2026-07.parquet"
OUTPUT = ROOT / "results/demo"
REQUIRED = ("timestamp_utc", "demand_mwh", "forecast_mwh", "interchange_mwh")


def load() -> pd.DataFrame:
    """Acquire historical measurements from the existing EIA-930 adapter output."""
    if not SOURCE.exists():
        raise FileNotFoundError(f"Missing {SOURCE}. Supply the July 2026 EIA-930 parquet.")
    return pd.read_parquet(SOURCE)


def validate(frame: pd.DataFrame) -> pd.DataFrame:
    """Enforce the small data contract used by this example."""
    missing = set(REQUIRED) - set(frame.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")
    data = frame.loc[:, REQUIRED].copy()
    data["timestamp_utc"] = pd.to_datetime(data["timestamp_utc"], utc=True)
    data = data.sort_values("timestamp_utc").reset_index(drop=True)
    if data["timestamp_utc"].duplicated().any():
        raise ValueError("Duplicate hourly timestamps")
    if not data["timestamp_utc"].dt.minute.eq(0).all():
        raise ValueError("Timestamps must be hourly")
    data = data.loc[data["demand_mwh"].between(10000, 200000)].copy()
    if data.empty:
        raise ValueError("No plausible demand measurements")
    return data


def analyze(data: pd.DataFrame) -> dict:
    """Compute transparent descriptive measurements, not a stress score."""
    data = data.copy()
    data["forecast_error_pct"] = (
        100 * (data["demand_mwh"] - data["forecast_mwh"]) / data["forecast_mwh"]
    )
    contiguous = data["timestamp_utc"].diff().eq(pd.Timedelta(hours=1))
    data["demand_change_mwh"] = data["demand_mwh"].diff().where(contiguous)
    peak = data.loc[data["demand_mwh"].idxmax()]
    return {
        "observed_hours": int(len(data)),
        "first_hour_utc": data["timestamp_utc"].min().isoformat(),
        "last_hour_utc": data["timestamp_utc"].max().isoformat(),
        "peak_demand_mwh": float(peak["demand_mwh"]),
        "peak_demand_hour_utc": peak["timestamp_utc"].isoformat(),
        "maximum_hourly_demand_increase_mwh": float(data["demand_change_mwh"].max()),
        "mean_absolute_forecast_error_pct": float(data["forecast_error_pct"].abs().mean()),
    }


def main() -> None:
    measurements = validate(load())
    result = analyze(measurements)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    record = {
        "case": "PJM July 2026 — descriptive historical measurements",
        "source": str(SOURCE.relative_to(ROOT)),
        "data_contract": list(REQUIRED),
        "method": "validation + deterministic descriptive statistics",
        "interpretation": "Not an emergency predictor or causal explanation",
        "results": result,
    }
    path = OUTPUT / "case_study.json"
    path.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))
    print(f"\nSaved {path}")


if __name__ == "__main__":
    main()
