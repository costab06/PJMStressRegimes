"""Exploratory weather-and-demand matched S3 vs S2 comparison.

Run: python -m gridregime.pipeline.match_escalation_conditions

Each S3 pre-action hour is matched to an S2 pre-alert hour from a different
episode, in the SAME cold/hot regime, minimizing standardized distance in
24-hour temperature and hourly demand. S2 controls are used at most once
within each S3 episode. Matching uses no outcomes or grid-response features.
This is descriptive, not a causal estimate or validated escalation predictor.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

from gridregime.pipeline.fit_temperature_regimes import ROOT, WEATHER, weather_regimes
from gridregime.pipeline.ablate_anomaly_features import FEAT, episode_anchors
from gridregime.pipeline.fit_temperature_regimes import reference_features

OUT = ROOT / "results/matched_escalation_v1"
# Raw, interpretable variables and their evolution. No outcomes in matching.
METRICS = [
    "fe_z", "ic_z", "ramp3_z",
    "fe_z_diff3h", "ic_z_diff3h", "ramp3_z_diff3h",
    "fe_z_std12h", "ic_z_std12h",
    "corr_fe_z_ic_z_24h", "corr_load_z_ic_z_24h",
    "lagcorr_fe_z_ic_z_24h",
]
MATCH = ["temperature_24h_f", "demand_mwh"]


def collect():
    catalog = pd.read_csv(ROOT / "metadata/events.csv")
    anchors = episode_anchors(catalog, reference_features())
    weather = weather_regimes(WEATHER)
    frames = []
    for eid in catalog["event_id"]:
        f = pd.read_parquet(FEAT / f"{eid}.parquet")
        f["timestamp_utc"] = pd.to_datetime(f["timestamp_utc"], utc=True)
        f["event_id"] = eid
        frames.append(f)
    data = pd.concat(frames, ignore_index=True)
    data = data.merge(catalog[["event_id", "episode_id", "severity"]],
                      on="event_id", how="left", validate="many_to_one")
    data = data.merge(weather[["timestamp_utc", "temperature_24h_f", "weather_regime"]],
                      on="timestamp_utc", how="left", validate="many_to_one")
    if "demand_mwh" not in data:
        raise ValueError("Event anomaly feature Parquets lack raw demand_mwh")
    # Overlapping windows can have inconsistent warmup-derived features.
    # Retain only episode-hours for which all selected values agree.
    selected = MATCH + METRICS
    records = []
    dropped_conflicts = 0
    for (episode, t), group in data.groupby(["episode_id", "timestamp_utc"], sort=True):
        anchor, severity, kind = anchors[episode]
        if severity not in ("S2", "S3"):
            continue
        if t + pd.Timedelta(hours=1) > anchor or t < anchor - pd.Timedelta(hours=48):
            continue
        if group["weather_regime"].iloc[0] not in ("cold", "hot"):
            continue
        vals = group[selected].replace([np.inf, -np.inf], np.nan)
        if vals.isna().any().any():
            continue
        a = vals.to_numpy(dtype=float)
        if not np.allclose(a, a[0], atol=1e-7, rtol=1e-7):
            dropped_conflicts += 1
            continue
        row = {"episode_id": episode, "severity": severity,
               "timestamp_utc": t, "regime": group["weather_regime"].iloc[0],
               "anchor_kind": kind, "hours_before_anchor":
                   (anchor - (t + pd.Timedelta(hours=1))).total_seconds() / 3600}
        row.update(dict(zip(selected, a[0])))
        records.append(row)
    result = pd.DataFrame(records)
    if result.empty:
        raise ValueError("No complete pre-anchor rows")
    return result, dropped_conflicts


def run():
    df, conflicts = collect()
    OUT.mkdir(parents=True, exist_ok=True)
    pairs = []
    audit = []
    for regime in ("cold", "hot"):
        treated = df.loc[(df["regime"] == regime) & (df["severity"] == "S3")]
        controls = df.loc[(df["regime"] == regime) & (df["severity"] == "S2")]
        if treated.empty:
            continue
        if controls.empty:
            raise ValueError(f"No S2 comparison hours for {regime}")
        # Standardization uses only S2 controls, not outcomes or S3 distribution.
        scale = controls[MATCH].std(ddof=0).to_numpy(dtype=float)
        if not np.isfinite(scale).all() or (scale <= 0).any():
            raise ValueError(f"Degenerate S2 matching scale for {regime}")
        for episode, s3 in treated.groupby("episode_id"):
            eligible = controls.loc[controls["episode_id"] != episode].copy()
            if len(eligible) < len(s3):
                raise ValueError(f"{episode}: insufficient distinct S2 control hours")
            left = s3[MATCH].to_numpy(dtype=float) / scale
            right = eligible[MATCH].to_numpy(dtype=float) / scale
            distances = np.sqrt(((left[:, None, :] - right[None, :, :]) ** 2).sum(axis=2))
            rows, cols = linear_sum_assignment(distances)
            for i, j in zip(rows, cols):
                a = s3.iloc[i]
                b = eligible.iloc[j]
                row = {
                    "regime": regime, "s3_episode": episode,
                    "s3_timestamp_utc": a["timestamp_utc"],
                    "s2_episode": b["episode_id"],
                    "s2_timestamp_utc": b["timestamp_utc"],
                    "distance_standardized": float(distances[i, j]),
                    "s3_hours_before_anchor": a["hours_before_anchor"],
                    "s2_hours_before_anchor": b["hours_before_anchor"],
                }
                for variable in MATCH + METRICS:
                    row["s3_" + variable] = float(a[variable])
                    row["s2_" + variable] = float(b[variable])
                    row["delta_" + variable] = float(a[variable] - b[variable])
                pairs.append(row)
            audit.append({
                "regime": regime, "s3_episode": episode, "s3_hours": len(s3),
                "available_s2_hours": len(eligible), "matched_pairs": len(rows),
                "s2_episode_count": eligible["episode_id"].nunique(),
                "matching_scales_s2_std": dict(zip(MATCH, scale.tolist())),
            })
    matches = pd.DataFrame(pairs)
    if matches.empty:
        raise ValueError("No matched comparisons")
    matches.to_csv(OUT / "matched_hours.csv", index=False)
    summaries = []
    for (regime, episode), part in matches.groupby(["regime", "s3_episode"]):
        base = {"regime": regime, "s3_episode": episode,
                "pairs": len(part),
                "control_episodes_used": part["s2_episode"].nunique(),
                "distance_median": part["distance_standardized"].median(),
                "distance_p90": part["distance_standardized"].quantile(.9)}
        for variable in MATCH + METRICS:
            delta = part["delta_" + variable]
            base[variable + "_s3_median"] = part["s3_" + variable].median()
            base[variable + "_s2_median"] = part["s2_" + variable].median()
            base[variable + "_median_pair_delta"] = delta.median()
            base[variable + "_mean_pair_delta"] = delta.mean()
        summaries.append(base)
    summary = pd.DataFrame(summaries)
    summary.to_csv(OUT / "episode_matched_comparison.csv", index=False)
    (OUT / "audit.json").write_text(json.dumps({
        "status": "exploratory_matched_descriptive_not_causal",
        "match_variables": MATCH,
        "response_variables": METRICS,
        "matching": "within regime; S2 standardized Euclidean distance; optimal "
                    "one-to-one assignment without control reuse within S3 episode",
        "matched_episode_metadata": audit,
        "overlap_conflicts_dropped": conflicts,
        "warnings": [
            "Only two S3 episodes; hours within an episode are NOT independent replicates",
            "No caliper: report distances and balance before interpreting differences",
            "No match on clock hour, season, year, or hours before alert/action",
            "S2 pre-alert and S3 pre-action windows have different anchor meanings",
            "Some S2 controls can be reused across different S3 episodes",
            "Selection on episodes and availability is retrospective",
            "PJM weather is four-city equal-weight ERA5 proxy, not load-weighted",
            "Unobserved outages, reserves, dispatch and transmission may confound",
            "No causal effect, significance test or predictive validation is claimed",
        ]
    }, indent=2, default=str) + "\n")
    print("\nMatching balance (medians of absolute within-pair differences):")
    for (regime, episode), part in matches.groupby(["regime", "s3_episode"]):
        print(f"{episode} ({regime}): {len(part)} pairs, "
              f"{part['s2_episode'].nunique()} S2 episodes, "
              f"median distance={part['distance_standardized'].median():.2f}; "
              f"|temp difference|={part['delta_temperature_24h_f'].abs().median():.2f} F, "
              f"|demand difference|={part['delta_demand_mwh'].abs().median():,.0f} MWh")
    display = ["regime", "s3_episode", "pairs", "distance_median"]
    display += [x + "_median_pair_delta" for x in METRICS]
    print("\nS3 minus matched S2 median within-pair differences:")
    print(summary[display].to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    print(f"\nSaved to {OUT}")
    return summary


if __name__ == "__main__":
    run()
