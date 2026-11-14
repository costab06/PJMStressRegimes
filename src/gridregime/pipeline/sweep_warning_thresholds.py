"""Exploratory early-warning sensitivity sweep, with continuous 2021 replay.

Run: python -m gridregime.pipeline.sweep_warning_thresholds

Thresholds are fixed TRAINING score quantiles (Jan-Sep 2021), never
optimized on the two S3 outcomes. October-December 2021 is a diagnostic
replay, NOT an independent validation set: seasonal normalization uses
all 2021. Scores across weather regimes are never compared directly.
"""
from __future__ import annotations

import json
import numpy as np
import pandas as pd

from gridregime.pipeline.fit_temperature_regimes import (
    ROOT, OUT as MODEL_OUT, WEATHER, REGIMES, reference_features, weather_regimes
)
from gridregime.pipeline.ablate_anomaly_features import (
    FEAT, SCORE_NAMES, clean, fit, score, episode_anchors
)

OUT = ROOT / "results/warning_threshold_sweep_v1"
QUANTILES = (0.90, 0.95, 0.975, 0.99, 0.995)
TRAIN_CUT = pd.Timestamp("2021-10-01", tz="UTC")


def warning_runs(df):
    """Count contiguous warning episodes, breaking on missing hours."""
    if df.empty:
        return 0, 0, 0
    df = df.sort_values("timestamp_utc")
    on = df["warning"].astype(bool)
    starts = on & (~on.shift(fill_value=False) |
                   df["timestamp_utc"].diff().ne(pd.Timedelta(hours=1)))
    lengths = on.groupby(starts.cumsum()).sum()
    lengths = lengths[lengths > 0]
    return int(starts.sum()), int(on.sum()), int(lengths.max()) if len(lengths) else 0


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((FEAT / "manifest.json").read_text())
    cols = manifest["feature_columns"]
    weather = weather_regimes(WEATHER)
    ref = reference_features().merge(weather, on="timestamp_utc", how="left",
                                     validate="one_to_one")
    events = pd.read_csv(ROOT / "metadata/events.csv")
    anchors = episode_anchors(events, ref)
    trace = pd.read_csv(MODEL_OUT / "episode_hourly_temperature_scores.csv")
    trace["timestamp_utc"] = pd.to_datetime(trace["timestamp_utc"], utc=True)
    if trace.duplicated(["episode_id", "detector", "timestamp_utc"]).any():
        raise ValueError("Duplicate event scores")
    replay_parts, thresholds, burden, detection = [], [], [], []
    for regime in REGIMES:
        train = clean(ref.loc[(ref["timestamp_utc"] < TRAIN_CUT) &
                              ref["weather_regime"].eq(regime)], cols)
        cal = clean(ref.loc[(ref["timestamp_utc"] >= TRAIN_CUT) &
                            ref["weather_regime"].eq(regime)], cols)
        if len(train) < 200:
            raise ValueError(f"Insufficient training: {regime}")
        models = fit(train, cols)
        train_scored = score(train, cols, models)
        cal_scored = score(cal, cols, models)
        for detector in SCORE_NAMES:
            cutoffs = {q: float(train_scored[detector].quantile(q))
                       for q in QUANTILES}
            for q, threshold in cutoffs.items():
                thresholds.append({"regime": regime, "detector": detector,
                                   "training_quantile": q, "score_threshold": threshold,
                                   "training_hours": len(train),
                                   "calibration_hours": len(cal)})
                for period, scored in (("training_2021", train_scored),
                                       ("oct_dec_2021", cal_scored)):
                    part = scored[["timestamp_utc", detector]].copy()
                    part = part.rename(columns={detector: "score"})
                    part["warning"] = part["score"] > threshold
                    n_runs, n_warn, longest = warning_runs(part)
                    burden.append({
                        "period": period, "regime": regime, "detector": detector,
                        "training_quantile": q, "scored_hours": len(part),
                        "warning_hours": n_warn,
                        "warning_hour_fraction": n_warn / len(part) if len(part) else np.nan,
                        "warning_runs": n_runs, "longest_warning_run_hours": longest,
                        "runs_per_30_scored_days": n_runs * 720 / len(part) if len(part) else np.nan
                    })
                    if period == "oct_dec_2021":
                        # Replay only held-out-quarter hours; no training replay rows needed.
                        part["regime"] = regime
                        part["detector"] = detector
                        part["training_quantile"] = q
                        replay_parts.append(part)
                sub = trace.loc[trace["regime"].eq(regime) &
                                trace["detector"].eq(detector)]
                for (episode, severity), group in sub.groupby(["episode_id", "severity"]):
                    anchor, _, kind = anchors[episode]
                    ordered = group.sort_values("timestamp_utc").copy()
                    warnings = ordered.loc[ordered["score"] > threshold]
                    # Hourly intervals must have completed before action; score
                    # publication latency remains unknown.
                    first = warnings["timestamp_utc"].min() if len(warnings) else pd.NaT
                    lead = ((anchor - (first + pd.Timedelta(hours=1))).total_seconds()/3600
                            if pd.notna(first) else np.nan)
                    detection.append({
                        "episode_id": episode, "severity": severity,
                        "anchor_kind": kind, "regime": regime, "detector": detector,
                        "training_quantile": q, "observed_hours": len(ordered),
                        "warning_hours": len(warnings),
                        "detected": bool(len(warnings)),
                        "first_warning_lead_hours": lead,
                        "max_score": ordered["score"].max(),
                        "threshold": threshold
                    })
    pd.DataFrame(thresholds).to_csv(OUT / "thresholds.csv", index=False)
    pd.DataFrame(burden).to_csv(OUT / "reference_alert_burden.csv", index=False)
    pd.DataFrame(detection).to_csv(OUT / "episode_detection.csv", index=False)
    pd.concat(replay_parts, ignore_index=True).to_csv(
        OUT / "oct_dec_2021_hourly_replay.csv", index=False)
    det = pd.DataFrame(detection)
    # An episode counts as detected if any of its scored weather regimes warned.
    episode = det.groupby(["detector", "training_quantile", "episode_id", "severity"]).agg(
        detected=("detected", "any"),
        first_warning_lead_hours=("first_warning_lead_hours", "max"),
        scored_hours=("observed_hours", "sum"),
        warning_hours=("warning_hours", "sum")
    ).reset_index()
    episode.to_csv(OUT / "episode_detection_any_regime.csv", index=False)
    summary = episode.groupby(["detector", "training_quantile", "severity"]).agg(
        episodes=("episode_id", "nunique"),
        detected_episodes=("detected", "sum"),
        median_first_warning_lead_hours=("first_warning_lead_hours", "median")
    ).reset_index()
    summary.to_csv(OUT / "threshold_episode_summary.csv", index=False)
    (OUT / "audit.json").write_text(json.dumps({
        "status": "retrospective_sensitivity_not_prospective_validation",
        "thresholds": list(QUANTILES),
        "threshold_selection": "fixed Jan-Sep 2021 training quantiles, independent of S3 labels",
        "calibration_replay": "Oct-Dec 2021, full continuous calendar with regime-specific valid hours",
        "detector_training": "Jan-Sep 2021; same feature construction as temperature-regime model",
        "warnings": [
            "2021 seasonal normalization was fitted on ALL 2021; Oct-Dec is not independent",
            "No demonstrated point-in-time EIA-930 data availability",
            "Only two S3 episodes; retrospective catalog is event-enriched",
            "S2 anchor is first alert; S3 anchor is operator action, not comparable",
            "S1 anchor is retrospectively chosen peak; exclude from prospective claims",
            "Regime-specific run counts can split an alert at a regime transition",
            "Runs per 30 scored days is a rate per eligible regime hours, NOT calendar-month alarms",
            "Hot Oct-Dec 2021 has very few calibration hours; rates are unstable",
            "An event can warn in multiple regimes; episode summary deduplicates",
            "A warning at any time in the 48h window is counted; minimum actionable lead not imposed",
            "False alarms cannot be measured from a baseline not independently certified as normal",
            "Weather is a four-site ERA5 proxy; no operating reserves or outages used",
        ]
    }, indent=2) + "\n")
    print("\nEpisode coverage by fixed training quantile (any weather regime):")
    print(summary.to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    print("\nOct-Dec 2021 reference alert burden (regime-specific):")
    b = pd.DataFrame(burden)
    print(b.loc[b["period"].eq("oct_dec_2021"),
                ["regime","detector","training_quantile","scored_hours",
                 "warning_hours","warning_runs","runs_per_30_scored_days"]].to_string(
                     index=False, float_format=lambda x: f"{x:.3f}"))
    print(f"\nSaved {OUT}/")
    return summary


if __name__ == "__main__":
    run()
