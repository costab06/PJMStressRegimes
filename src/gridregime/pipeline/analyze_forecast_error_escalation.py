"""Diagnose whether demand underforecast distinguishes S3 from S2.

Run: python -m gridregime.pipeline.analyze_forecast_error_escalation

Uses existing matched pre-anchor S3/S2 pairs and raw EIA-930 hourly
actual/forecast. Positive error = actual - forecast (underforecast).
Produces paired comparisons, 12-hour relative-to-anchor trajectories,
and an S2 counterexample inventory. Descriptive, not causal/predictive.
"""
from __future__ import annotations

import json
import numpy as np
import pandas as pd
from gridregime.pipeline.fit_temperature_regimes import ROOT

MATCHED = ROOT / "results/matched_escalation_v1/matched_hours.csv"
OUT = ROOT / "results/forecast_error_escalation_v1"


def raw_hourly():
    catalog = pd.read_csv(ROOT / "metadata/events.csv")
    parts = []
    for eid in catalog["event_id"]:
        f = pd.read_parquet(ROOT / "data/interim/eia930" / f"{eid}.parquet")
        f["timestamp_utc"] = pd.to_datetime(f["timestamp_utc"], utc=True)
        parts.append(f[["timestamp_utc", "demand_mwh", "forecast_mwh"]])
    all_hours = pd.concat(parts, ignore_index=True)
    for field in ("demand_mwh", "forecast_mwh"):
        if all_hours.groupby("timestamp_utc")[field].agg(
            lambda x: x.max() - x.min()).gt(1e-6).any():
            raise ValueError(f"Conflicting {field} in overlapping windows")
    all_hours = all_hours.drop_duplicates("timestamp_utc")
    all_hours = all_hours.loc[
        all_hours["demand_mwh"].between(10000, 200000) &
        all_hours["forecast_mwh"].between(10000, 200000)].copy()
    all_hours["error_mw"] = all_hours["demand_mwh"] - all_hours["forecast_mwh"]
    all_hours["underforecast_mw"] = all_hours["error_mw"].clip(lower=0)
    all_hours["absolute_error_mw"] = all_hours["error_mw"].abs()
    all_hours["error_pct"] = 100 * all_hours["error_mw"] / all_hours["forecast_mwh"]
    return all_hours


def run():
    matched = pd.read_csv(MATCHED)
    hourly = raw_hourly()
    for side in ("s3", "s2"):
        matched[side + "_timestamp_utc"] = pd.to_datetime(
            matched[side + "_timestamp_utc"], utc=True)
        fields = ["timestamp_utc", "demand_mwh", "forecast_mwh", "error_mw",
                  "underforecast_mw", "absolute_error_mw", "error_pct"]
        matched = matched.merge(
            hourly[fields].rename(columns={
                x: side + "_" + x for x in fields if x != "timestamp_utc"
            }),
            left_on=side + "_timestamp_utc", right_on="timestamp_utc",
            how="left", validate="many_to_one").drop(columns=["timestamp_utc"])
    if matched[["s3_error_mw", "s2_error_mw"]].isna().any().any():
        raise ValueError("Missing raw forecast/demand in matched pair")
    metrics = ["error_mw", "underforecast_mw", "absolute_error_mw", "error_pct"]
    for metric in metrics:
        matched["delta_" + metric] = matched["s3_" + metric] - matched["s2_" + metric]
    OUT.mkdir(parents=True, exist_ok=True)
    matched.to_csv(OUT / "matched_forecast_errors.csv", index=False)

    summary = []
    for (regime, episode), g in matched.groupby(["regime", "s3_episode"]):
        row = {
            "regime": regime, "s3_episode": episode, "pairs": len(g),
            "s2_control_episodes": g["s2_episode"].nunique(),
            "median_match_distance": g["distance_standardized"].median(),
            "median_abs_demand_gap_mw": g["delta_demand_mwh"].abs().median(),
            "median_abs_temperature_gap_f": g["delta_temperature_24h_f"].abs().median(),
            "s3_underforecast_hour_share": (g["s3_error_mw"] > 0).mean(),
            "s2_underforecast_hour_share": (g["s2_error_mw"] > 0).mean(),
        }
        for metric in metrics:
            row["s3_median_" + metric] = g["s3_" + metric].median()
            row["s2_median_" + metric] = g["s2_" + metric].median()
            row["median_paired_delta_" + metric] = g["delta_" + metric].median()
            row["s3_gt_s2_share_" + metric] = (g["delta_" + metric] > 0).mean()
        summary.append(row)
    summary = pd.DataFrame(summary)
    summary.to_csv(OUT / "matched_forecast_summary.csv", index=False)

    # Use the original matched pairs to recover S2 controls' relative alert time.
    # Derive anchor from metadata (earliest first alert for S2, operator action S3).
    catalog = pd.read_csv(ROOT / "metadata/events.csv")
    anchor_map = {}
    for episode, g in catalog.groupby("episode_id"):
        sev = g["severity"].iloc[0]
        col = "operator_action_time" if sev == "S3" else "first_alert_time"
        vals = pd.to_datetime(g[col].dropna(), utc=True)
        if len(vals):
            anchor_map[episode] = vals.min()
    # Deduplicate same episode-hour if multiple matching rows refer to it.
    rows = []
    for side in ("s3", "s2"):
        sub = matched[[side + "_episode", side + "_timestamp_utc"]].rename(
            columns={side + "_episode": "episode_id",
                     side + "_timestamp_utc": "timestamp_utc"})
        rows.append(sub)
    observed = pd.concat(rows, ignore_index=True).drop_duplicates()
    observed = observed.merge(hourly, on="timestamp_utc", how="left",
                              validate="many_to_one")
    observed["severity"] = observed["episode_id"].map(
        catalog.drop_duplicates("episode_id").set_index("episode_id")["severity"])
    observed["anchor"] = observed["episode_id"].map(anchor_map)
    observed["hours_before_anchor"] = (
        observed["anchor"] - (observed["timestamp_utc"] + pd.Timedelta(hours=1))
    ).dt.total_seconds() / 3600
    observed["bin"] = pd.cut(observed["hours_before_anchor"],
                             bins=[-0.001, 12, 24, 36, 48],
                             labels=["0-12h", "12-24h", "24-36h", "36-48h"])
    trajectory = observed.groupby(
        ["episode_id", "severity", "bin"], observed=True).agg(
            hours=("error_mw", "size"),
            median_signed_error_mw=("error_mw", "median"),
            median_underforecast_mw=("underforecast_mw", "median"),
            peak_underforecast_mw=("underforecast_mw", "max"),
            underforecast_hour_share=("error_mw", lambda x: (x > 0).mean())
        ).reset_index()
    trajectory.to_csv(OUT / "episode_12h_trajectories.csv", index=False)

    # S2 counterexamples: large underforecast relative to S3 benchmark,
    # not proof of comparable reserve stress.
    s3_threshold = observed.loc[observed["severity"] == "S3", "underforecast_mw"].quantile(.75)
    s2 = observed.loc[observed["severity"] == "S2"]
    counter = s2.groupby("episode_id").agg(
        observed_hours=("error_mw", "size"),
        max_underforecast_mw=("underforecast_mw", "max"),
        median_underforecast_mw=("underforecast_mw", "median"),
        hours_above_s3_p75=("underforecast_mw", lambda x: int((x >= s3_threshold).sum()))
    ).reset_index()
    counter.to_csv(OUT / "s2_counterexamples.csv", index=False)
    (OUT / "audit.json").write_text(json.dumps({
        "status": "exploratory_descriptive",
        "sign_convention": "actual demand minus forecast; positive means underforecast",
        "unit": "EIA-930 hourly MWh, numerically equivalent to average MW",
        "s3_75th_percentile_underforecast_mw": float(s3_threshold),
        "warnings": [
            "EIA-930 forecast may not equal PJM operational commitment forecast",
            "S3 anchors are operator actions; S2 anchors are first alerts",
            "Only two S3 episodes; hours are autocorrelated",
            "Trajectory uses matched-hour subset, not necessarily contiguous full 48h",
            "Control hours can be reused across S3 episodes",
            "No operating reserve, forced outage or resource adequacy information",
            "Comparisons do not establish a causal mechanism or prospective prediction"
        ]
    }, indent=2) + "\n")

    columns = ["regime", "s3_episode", "pairs",
               "s3_median_error_mw", "s2_median_error_mw",
               "median_paired_delta_error_mw",
               "s3_gt_s2_share_error_mw",
               "s3_median_underforecast_mw", "s2_median_underforecast_mw",
               "median_paired_delta_underforecast_mw"]
    print("\nRaw forecast error: S3 vs temperature/demand matched S2:")
    print(summary[columns].to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
    print("\nForecast error trajectories (matched-hour subset):")
    print(trajectory.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
    print(f"\nS2 episodes with large underforecast (S3 75th pct threshold: {s3_threshold:,.0f} MW):")
    print(counter.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
    print(f"\nSaved {OUT}/")
    return summary


if __name__ == "__main__":
    run()
