"""Weather-conditioned exploratory anomaly models.

Requires a *real*, PJM-region representative hourly temperature series:
  data/processed/weather/pjm_temperature_hourly.csv
Columns: timestamp_utc,temperature_f
Temperature should be a documented load-weighted PJM aggregate. No synthetic
weather, season-derived labels, or event-label-derived weather classifications.

Run:
  python -m gridregime.pipeline.fit_temperature_regimes

Uses trailing 24 *completed* hourly temperatures, with strictly consecutive
observations. Scores EIA observations only after their hour is complete;
actual historical data-publication delays remain unverified.

Outputs descriptive episode summaries, hourly scores, and audit metadata.
All results exploratory; 2021 baseline and training are not independent.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from gridregime.features.seasonal import apply_zscore
from gridregime.pipeline.ablate_anomaly_features import (
    ROOT, FEAT, SCORE_NAMES, clean, episode_anchors, fit, score
)
from gridregime.pipeline.build_anomaly_features import build_features

WEATHER = ROOT / "data/processed/weather/pjm_temperature_hourly.csv"
OUT = ROOT / "results/temperature_regimes_v1"
REGIMES = ("cold", "moderate", "hot")


def weather_regimes(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Supply actual PJM-representative hourly "
            "temperature data with timestamp_utc,temperature_f columns. "
            "Do not infer weather from event names or months."
        )
    w = pd.read_csv(path)
    required = {"timestamp_utc", "temperature_f"}
    if not required.issubset(w.columns):
        raise ValueError(f"Weather file requires columns {sorted(required)}")
    w["timestamp_utc"] = pd.to_datetime(w["timestamp_utc"], utc=True, errors="raise")
    w["temperature_f"] = pd.to_numeric(w["temperature_f"], errors="raise")
    w = w.sort_values("timestamp_utc").reset_index(drop=True)
    if w["timestamp_utc"].duplicated().any():
        raise ValueError("Duplicate weather timestamps")
    if not w["temperature_f"].between(-100, 140).all():
        raise ValueError("Implausible/missing temperatures; validate units and source")
    if not w["timestamp_utc"].dt.minute.eq(0).all() or not w["timestamp_utc"].dt.second.eq(0).all():
        raise ValueError("Weather timestamps must mark exact UTC hours")
    # Break rolling windows on gaps, never bridge missing weather hours.
    contiguous = w["timestamp_utc"].diff().eq(pd.Timedelta(hours=1))
    segment = (~contiguous).cumsum()
    w["temperature_24h_f"] = w.groupby(segment)["temperature_f"].transform(
        lambda x: x.rolling(24, min_periods=24).mean()
    )
    w["weather_regime"] = pd.Series(pd.NA, index=w.index, dtype="string")
    valid = w["temperature_24h_f"].notna()
    w.loc[valid & (w["temperature_24h_f"] < 40), "weather_regime"] = "cold"
    w.loc[valid & (w["temperature_24h_f"] > 70), "weather_regime"] = "hot"
    w.loc[valid & w["temperature_24h_f"].between(40, 70), "weather_regime"] = "moderate"
    return w[["timestamp_utc", "temperature_f", "temperature_24h_f", "weather_regime"]]


def reference_features():
    baseline = pd.read_parquet(ROOT / "data/processed/baseline_2021_frozen_v1.parquet")
    paths = [ROOT / f"data/raw/eia930/PJM_2021-{m:02d}.parquet" for m in range(1,13)]
    raw = pd.concat([pd.read_parquet(p) for p in paths], ignore_index=True)
    raw["timestamp_utc"] = pd.to_datetime(raw["timestamp_utc"], utc=True)
    raw = raw.sort_values("timestamp_utc").reset_index(drop=True)
    if raw["timestamp_utc"].duplicated().any():
        raise ValueError("Duplicate 2021 EIA hours")
    bad = ~raw["demand_mwh"].between(10000, 200000)
    raw.loc[bad, ["demand_mwh", "forecast_mwh", "interchange_mwh"]] = np.nan
    raw["t"] = (raw["timestamp_utc"] - raw["timestamp_utc"].iloc[0]).dt.total_seconds()/3600
    return build_features(apply_zscore(raw, baseline))


def run():
    manifest = json.loads((FEAT / "manifest.json").read_text())
    cols = manifest["feature_columns"]
    w = weather_regimes(WEATHER)
    ref = reference_features().merge(w, on="timestamp_utc", how="left", validate="one_to_one")
    events = pd.read_csv(ROOT / "metadata/events.csv")
    anchors = episode_anchors(events, ref)
    frames = []
    for eid in events["event_id"]:
        frame = pd.read_parquet(FEAT / f"{eid}.parquet")
        frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
        frame = frame.merge(w, on="timestamp_utc", how="left", validate="one_to_one")
        frame["event_id"] = eid
        frames.append(frame)
    event_hours = pd.concat(frames, ignore_index=True).merge(
        events[["event_id", "episode_id", "severity"]],
        on="event_id", how="left", validate="many_to_one"
    )
    OUT.mkdir(parents=True, exist_ok=True)
    hourly, calibration, coverage = [], [], []
    training_cut = pd.Timestamp("2021-10-01", tz="UTC")
    for regime in REGIMES:
        training = clean(ref.loc[
            (ref["timestamp_utc"] < training_cut) &
            (ref["weather_regime"] == regime)], cols)
        holdout = clean(ref.loc[
            (ref["timestamp_utc"] >= training_cut) &
            (ref["weather_regime"] == regime)], cols)
        ev = event_hours.loc[event_hours["weather_regime"] == regime]
        coverage.append({"regime": regime, "train_complete_hours": len(training),
                         "calibration_complete_hours": len(holdout),
                         "event_complete_hours": len(clean(ev, cols))})
        # A model with fewer than 200 samples is not meaningfully trainable here.
        if len(training) < 200:
            raise ValueError(f"{regime}: only {len(training)} training hours; "
                             "expand the reference period instead of fitting a weak model")
        models = fit(training, cols)
        train_scores = score(training, cols, models)
        holdout_scores = score(holdout, cols, models)
        thresholds = {name: float(train_scores[name].quantile(.99))
                      for name in SCORE_NAMES}
        for name in SCORE_NAMES:
            calibration.append({
                "regime": regime, "detector": name,
                "train_hours": len(training), "calibration_hours": len(holdout),
                "training_p99": thresholds[name],
                "calibration_exceedance_rate": (
                    float((holdout_scores[name] > thresholds[name]).mean())
                    if len(holdout_scores) else np.nan)
            })
        scored = score(ev, cols, models)
        # score() preserves original indices; reattach metadata by index.
        scored = scored.join(ev[["episode_id", "severity", "temperature_24h_f"]])
        for (episode, t), group in scored.groupby(["episode_id", "timestamp_utc"]):
            vals = group[list(SCORE_NAMES)].to_numpy(dtype=float)
            if not np.allclose(vals, vals[0], rtol=1e-7, atol=1e-7):
                continue
            anchor, severity, kind = anchors[episode]
            if t + pd.Timedelta(hours=1) > anchor or t < anchor-pd.Timedelta(hours=48):
                continue
            for i,name in enumerate(SCORE_NAMES):
                hourly.append({
                    "episode_id": episode, "severity": severity,
                    "anchor_kind": kind, "regime": regime, "detector": name,
                    "timestamp_utc": t, "temperature_24h_f": float(group["temperature_24h_f"].iloc[0]),
                    "score": float(vals[0,i]),
                    "above_training_p99": bool(vals[0,i] > thresholds[name])
                })
        print(f"{regime}: train={len(training)}, calibration={len(holdout)}, "
              f"event hours={len(clean(ev, cols))}")
    traces = pd.DataFrame(hourly)
    traces.to_csv(OUT / "episode_hourly_temperature_scores.csv", index=False)
    if traces.empty:
        raise ValueError("No scored pre-anchor event hours; check weather coverage and timestamps")
    rows = []
    for (episode, severity, regime, detector), g in traces.groupby(
        ["episode_id", "severity", "regime", "detector"]):
        rows.append({"episode_id": episode, "severity": severity, "regime": regime,
                     "detector": detector, "observed_48h": len(g),
                     "temperature_24h_median_f": float(g["temperature_24h_f"].median()),
                     "median_score": float(g["score"].median()),
                     "max_score": float(g["score"].max()),
                     "exceed_hours_48h": int(g["above_training_p99"].sum())})
    result = pd.DataFrame(rows)
    result.to_csv(OUT / "episode_temperature_summary.csv", index=False)
    pd.DataFrame(calibration).to_csv(OUT / "regime_calibration.csv", index=False)
    pd.DataFrame(coverage).to_csv(OUT / "regime_coverage.csv", index=False)
    (OUT / "audit.json").write_text(json.dumps({
        "status": "exploratory_post_hoc_not_independent_validation",
        "weather_input": str(WEATHER.relative_to(ROOT)),
        "weather_definition": "trailing 24 consecutive hourly temperatures",
        "weather_thresholds_f": {"cold_below":40,"hot_above":70,
                                  "moderate_inclusive":[40,70]},
        "weather_geography": "must be verified by provider as PJM-representative",
        "training": "Jan-Sep 2021 by regime; 2021 all-year seasonal normalization",
        "calibration": "Oct-Dec 2021 by regime, not independent of normalization",
        "primary_regimes": ["cold","hot"],
        "secondary_regime": "moderate",
        "warnings": [
            "Only two S3 episodes in catalog",
            "Temperature may be observed rather than point-in-time forecast",
            "EIA-930 historical publication delays unverified",
            "Scores of separate regime models are not numerically comparable",
            "Weather coverage gaps omit hours; inspect regime_coverage.csv",
            "S1 anchor is retrospective"
        ]}, indent=2)+"\n")
    print("\nEpisode summary:")
    print(result.to_string(index=False))
    print(f"\nSaved {OUT}/")
    return result


if __name__ == "__main__":
    run()
