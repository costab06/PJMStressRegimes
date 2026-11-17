"""Bounded deterministic investigations selected by the local model.

The model chooses a predefined question; it cannot execute arbitrary code.
"""
from __future__ import annotations

import pandas as pd
from gridregime.demo import validate

QUESTIONS = {
    "forecast_accuracy": "Does lower percentage error at high demand persist in MWh and after matching hour of day?",
    "ramp_interchange": "Is the weak association with interchange level also present for hourly interchange changes?",
}


def investigate(frame: pd.DataFrame, question: str) -> dict:
    if question not in QUESTIONS:
        raise ValueError(f"Unsupported investigation: {question}")
    d = validate(frame).copy()
    if len(d) < 48:
        raise ValueError("At least 48 hours required")
    if (d["forecast_mwh"] <= 0).any() or d[["demand_mwh", "forecast_mwh", "interchange_mwh"]].isna().any().any():
        raise ValueError("Missing or invalid measurements")
    d["hour"] = d["timestamp_utc"].dt.hour
    if question == "forecast_accuracy":
        d["absolute_mwh"] = (d["demand_mwh"] - d["forecast_mwh"]).abs()
        d["absolute_pct"] = 100 * d["absolute_mwh"] / d["forecast_mwh"]
        threshold = d["demand_mwh"].quantile(.90)
        d["high"] = d["demand_mwh"] >= threshold
        high, other = d[d.high], d[~d.high]
        # Within each clock-hour compare high and other hours, then average
        # differences equally across eligible clock-hours (not across observations).
        matched = []
        for hour, group in d.groupby("hour"):
            h, o = group[group.high], group[~group.high]
            if len(h) >= 2 and len(o) >= 2:
                matched.append({
                    "hour_utc": int(hour), "high_n": int(len(h)), "other_n": int(len(o)),
                    "difference_pct_points": round(float(h.absolute_pct.mean() - o.absolute_pct.mean()), 4),
                    "difference_mwh": round(float(h.absolute_mwh.mean() - o.absolute_mwh.mean()), 3),
                })
        return {
            "question": question, "method": "Top-decile demand comparison and within-UTC-hour stratification",
            "threshold_mwh": round(float(threshold), 3),
            "high_n": int(len(high)), "other_n": int(len(other)),
            "overall": {
                "high_mean_absolute_pct": round(float(high.absolute_pct.mean()), 4),
                "other_mean_absolute_pct": round(float(other.absolute_pct.mean()), 4),
                "high_mean_absolute_mwh": round(float(high.absolute_mwh.mean()), 3),
                "other_mean_absolute_mwh": round(float(other.absolute_mwh.mean()), 3),
            },
            "hour_matched": {
                "eligible_hours": len(matched),
                "per_hour": matched,
                "mean_difference_pct_points": round(float(sum(x["difference_pct_points"] for x in matched) / len(matched)), 4) if matched else None,
                "mean_difference_mwh": round(float(sum(x["difference_mwh"] for x in matched) / len(matched)), 3) if matched else None,
            },
            "limitations": [
                "UTC-hour matching does not control for weather, weekday, or demand selection effects",
                "Percentage errors have forecast magnitude in the denominator",
                "Descriptive comparison only; no causal or statistical significance claim",
            ],
        }
    d = d.sort_values("timestamp_utc").reset_index(drop=True)
    contiguous = d.timestamp_utc.diff().eq(pd.Timedelta(hours=1))
    d["ramp"] = d.demand_mwh.diff().where(contiguous)
    d["interchange_change"] = d.interchange_mwh.diff().where(contiguous)
    paired = d[["ramp", "interchange_change"]].dropna()
    correlation = None
    if len(paired) >= 3 and paired.ramp.std() > 0 and paired.interchange_change.std() > 0:
        c = paired.ramp.corr(paired.interchange_change)
        if pd.notna(c):
            correlation = round(float(c), 4)
    return {
        "question": question, "method": "Pearson correlation between contiguous hourly demand and interchange changes",
        "paired_hours": int(len(paired)), "pearson_r": correlation,
        "limitations": [
            "Interchange sign conventions and balancing-area accounting require domain review",
            "Contemporaneous correlation does not establish cause or operational response",
            "No generation dispatch or reserve data",
        ],
    }
