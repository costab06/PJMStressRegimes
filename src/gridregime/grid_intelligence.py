"""Deterministic evidence for a bounded PJM grid interpretation."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from gridregime.demo import OUTPUT, load, validate


def build_evidence(data: pd.DataFrame) -> dict:
    """Compute inspectable observations; do not infer causation or emergencies."""
    d = validate(data).copy()
    if len(d) < 48:
        raise ValueError("At least 48 hourly observations required for interpretation")
    if not np.isfinite(d[["demand_mwh", "forecast_mwh", "interchange_mwh"]].to_numpy(dtype=float)).all():
        raise ValueError("Non-finite input measurements")
    if (d["forecast_mwh"] <= 0).any():
        raise ValueError("Forecasts must be positive")
    d["error_pct"] = 100 * (d["demand_mwh"] - d["forecast_mwh"]) / d["forecast_mwh"]
    d["absolute_error_pct"] = d["error_pct"].abs()
    threshold = float(d["demand_mwh"].quantile(0.90))
    high = d["demand_mwh"] >= threshold
    normal = ~high
    if not high.any() or not normal.any():
        raise ValueError("Cannot compare high and ordinary demand")
    consecutive = d["timestamp_utc"].diff().eq(pd.Timedelta(hours=1))
    d["ramp_mwh"] = d["demand_mwh"].diff().where(consecutive)
    ramps = d["ramp_mwh"].dropna()
    if ramps.empty:
        raise ValueError("No contiguous hours for ramp comparison")
    top_ramp_idx = ramps.idxmax()
    # Correlation is descriptive only; a null value means insufficient variation.
    valid = d[["ramp_mwh", "interchange_mwh"]].dropna()
    corr = None
    if len(valid) >= 3 and valid["ramp_mwh"].std() > 0 and valid["interchange_mwh"].std() > 0:
        corr = float(valid["ramp_mwh"].corr(valid["interchange_mwh"]))
        if not np.isfinite(corr):
            corr = None
    return {
        "scope": "PJM July 2026 historical observations; descriptive, not causal or predictive",
        "units": {"demand": "MWh per hour", "forecast_error": "percent", "interchange": "MWh per hour"},
        "observations": [
            {"id": "E1", "finding": "high_demand_threshold", "value": round(threshold, 3),
             "high_hours": int(high.sum()), "other_hours": int(normal.sum()),
             "definition": "Demand >= empirical 90th percentile (ties included)"},
            {"id": "E2", "finding": "mean_absolute_forecast_error_by_demand",
             "high_demand_pct": round(float(d.loc[high, "absolute_error_pct"].mean()), 4),
             "other_hours_pct": round(float(d.loc[normal, "absolute_error_pct"].mean()), 4),
             "definition": "Mean absolute (actual - forecast)/forecast * 100, split using E1"},
            {"id": "E3", "finding": "signed_forecast_bias_by_demand",
             "high_demand_pct": round(float(d.loc[high, "error_pct"].mean()), 4),
             "other_hours_pct": round(float(d.loc[normal, "error_pct"].mean()), 4),
             "definition": "Positive indicates actual demand exceeded forecast"},
            {"id": "E4", "finding": "maximum_contiguous_hourly_demand_ramp",
             "increase_mwh": round(float(ramps.max()), 3),
             "hour_utc": d.loc[top_ramp_idx, "timestamp_utc"].isoformat(),
             "definition": "Only consecutive hourly records contribute"},
            {"id": "E5", "finding": "ramp_interchange_level_correlation",
             "pearson_r": None if corr is None else round(corr, 4),
             "paired_hours": int(len(valid)),
             "definition": "Pearson correlation of hourly demand change and interchange level; not causal"},
        ],
        "limitations": [
            "No weather, outage, generation availability, or operating reserve measurements",
            "Observational comparisons may reflect time-of-day and seasonal confounding",
            "No emergency risk score, prediction, or causal attribution",
            "Source publication time has not been verified",
        ],
    }


def main() -> None:
    evidence = build_evidence(load())
    OUTPUT.mkdir(parents=True, exist_ok=True)
    target = OUTPUT / "grid_evidence.json"
    target.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    print(f"Saved {target}")


if __name__ == "__main__":
    main()
