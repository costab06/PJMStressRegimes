"""Explain anomaly scores using temperature and demand (cold/hot separately).

Run: python -m gridregime.pipeline.regress_anomaly_drivers

Fits temperature-only, demand-only and combined linear models to existing
pre-anchor episode-hour anomaly scores. Reports in-sample and leave-one-episode-
out R². The latter tests transfer between episodes, NOT independence of the
original anomaly detector's 2021 training reference. No causal claims.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score

from gridregime.pipeline.fit_temperature_regimes import ROOT

TRACES = ROOT / "results/temperature_regimes_v1/episode_hourly_temperature_scores.csv"
OUT = ROOT / "results/anomaly_driver_regression_v1"
PREDICTORS = {
    "temperature_only": ["temperature_24h_f"],
    "demand_only": ["demand_mwh"],
    "temperature_plus_demand": ["temperature_24h_f", "demand_mwh"],
}


def load():
    scores = pd.read_csv(TRACES, parse_dates=["timestamp_utc"])
    scores["timestamp_utc"] = pd.to_datetime(scores["timestamp_utc"], utc=True)
    events = pd.read_csv(ROOT / "metadata/events.csv")
    demand = []
    for eid in events["event_id"]:
        frame = pd.read_parquet(ROOT / "data/interim/eia930" / f"{eid}.parquet")
        frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
        demand.append(frame[["timestamp_utc", "demand_mwh"]])
    demand = pd.concat(demand, ignore_index=True)
    discrepancy = demand.groupby("timestamp_utc")["demand_mwh"].agg(
        lambda x: x.max() - x.min())
    if discrepancy.gt(1e-6).any():
        raise ValueError("Event windows disagree on overlapping hourly demand")
    demand = demand.drop_duplicates("timestamp_utc")
    joined = scores.merge(demand, on="timestamp_utc", how="left", validate="many_to_one")
    if joined["demand_mwh"].isna().any():
        raise ValueError("Missing demand for anomaly-score hours")
    if joined.duplicated(["episode_id", "timestamp_utc", "detector"]).any():
        raise ValueError("Duplicate episode-hour-detector scores")
    return joined


def regression(sub, columns):
    x = sub[columns].to_numpy(dtype=float)
    y = sub["score"].to_numpy(dtype=float)
    groups = sub["episode_id"].to_numpy()
    model = LinearRegression().fit(x, y)
    insample = float(model.score(x, y))
    predictions = np.full(len(y), np.nan)
    for episode in np.unique(groups):
        test = groups == episode
        train = ~test
        if train.sum() <= len(columns) + 1:
            continue
        m = LinearRegression().fit(x[train], y[train])
        predictions[test] = m.predict(x[test])
    valid = np.isfinite(predictions)
    pooled_oos = float(r2_score(y[valid], predictions[valid])) if valid.sum() >= 2 else np.nan
    # Baseline predicts training-episode mean, not the test episode's own mean.
    baseline = np.full(len(y), np.nan)
    for episode in np.unique(groups):
        test = groups == episode
        baseline[test] = y[~test].mean()
    sse = np.sum((y[valid] - predictions[valid])**2)
    baseline_sse = np.sum((y[valid] - baseline[valid])**2)
    improvement = float(1 - sse / baseline_sse) if baseline_sse > 0 else np.nan
    return insample, pooled_oos, improvement, model.coef_, model.intercept_


def run():
    scores = load()
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    for regime in ("cold", "hot"):
        for detector in ("isolation_score", "mahalanobis_d2"):
            sub = scores.loc[(scores["regime"] == regime) &
                             (scores["detector"] == detector)].dropna(
                subset=["temperature_24h_f", "demand_mwh", "score"]).copy()
            n_episodes = sub["episode_id"].nunique()
            if n_episodes < 3:
                raise ValueError(f"{regime}/{detector}: need >=3 independent episodes")
            for label, columns in PREDICTORS.items():
                inside, oos, improvement, coefficients, intercept = regression(sub, columns)
                results.append({
                    "regime": regime, "detector": detector,
                    "model": label, "hours": len(sub), "episodes": n_episodes,
                    "in_sample_r2": inside, "leave_episode_out_r2": oos,
                    "leave_episode_out_improvement_vs_training_mean": improvement,
                    "intercept": float(intercept),
                    "temperature_coefficient": float(coefficients[columns.index(
                        "temperature_24h_f")]) if "temperature_24h_f" in columns else np.nan,
                    "demand_coefficient": float(coefficients[columns.index(
                        "demand_mwh")]) if "demand_mwh" in columns else np.nan,
                })
    result = pd.DataFrame(results)
    result.to_csv(OUT / "score_driver_regressions.csv", index=False)
    show = ["regime", "detector", "model", "hours", "episodes",
            "in_sample_r2", "leave_episode_out_r2",
            "leave_episode_out_improvement_vs_training_mean"]
    print("\nAnomaly score explained by temperature and/or demand:")
    print(result[show].to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    print(f"\nSaved: {OUT / 'score_driver_regressions.csv'}")
    print("LOEO R² may be negative; it means worse predictions than the global")
    print("mean of observed scores. The improvement column instead uses the")
    print("training-episode mean as the baseline for each held-out episode.")
    print("Caution: these are event-enriched pre-anchor hours; adjacent hours")
    print("are autocorrelated, and only a few independent episodes are available.")
    return result


if __name__ == "__main__":
    run()
