"""Exploratory seven-day anomaly trajectories and grouped feature sensitivity.

Run:
  python -m gridregime.pipeline.analyze_seven_day_trajectories

Uses existing seven_day_hourly.csv for trajectories; reconstructs feature
vectors for sensitivity, with fixed 2021-trained regime models. Feature
replacement is an attribution diagnostic, NOT causal importance.
"""
from __future__ import annotations

import json
import numpy as np
import pandas as pd
from gridregime.pipeline.evaluate_seven_day_onset import (
    ROOT, WEATHER, REGIMES, HORIZON, WARMUP, load_months
)
from gridregime.pipeline.fit_temperature_regimes import reference_features, weather_regimes
from gridregime.pipeline.ablate_anomaly_features import clean, fit, score, families
from gridregime.pipeline.build_anomaly_features import build_features
from gridregime.features.seasonal import apply_zscore

OUT = ROOT / "results/seven_day_trajectories_v1"
SOURCE = ROOT / "results/seven_day_onset_v1/seven_day_hourly.csv"
CUT = pd.Timestamp("2021-10-01", tz="UTC")


def episode_anchor(group):
    alert = pd.to_datetime(group["first_alert_time"].dropna(), utc=True)
    action = pd.to_datetime(group["operator_action_time"].dropna(), utc=True)
    if len(alert):
        return alert.min(), "first_documented_alert"
    if len(action):
        return action.min(), "operator_action_NOT_first_alert"
    return None, "no_anchor"


def segments(x):
    """Early=168..48 hours before anchor; late=last 48 hours."""
    return {"early_168_to_48h": x.loc[x["lead"] >= 48],
            "late_48h": x.loc[x["lead"] < 48],
            "final_24h": x.loc[x["lead"] < 24]}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if not SOURCE.exists():
        raise FileNotFoundError(f"Run evaluate_seven_day_onset first: {SOURCE}")
    hourly = pd.read_csv(SOURCE, parse_dates=["timestamp_utc"])
    hourly["timestamp_utc"] = pd.to_datetime(hourly["timestamp_utc"], utc=True)
    hourly["lead"] = hourly["hours_before_anchor_at_availability"]
    if hourly.duplicated(["episode_id", "timestamp_utc"]).any():
        raise ValueError("Duplicate episode hours")
    events = pd.read_csv(ROOT / "metadata/events.csv")
    manifest = json.loads((ROOT/"data/processed/anomaly_features_v1/manifest.json").read_text())
    cols = manifest["feature_columns"]
    groups = families(cols)
    groups.pop("all")
    baseline = pd.read_parquet(ROOT/"data/processed/baseline_2021_frozen_v1.parquet")
    weather = weather_regimes(WEATHER)
    reference = reference_features().merge(weather, on="timestamp_utc",
                                           how="left", validate="one_to_one")
    models, medians, thresholds = {}, {}, {}
    for regime in REGIMES:
        training = clean(reference.loc[
            (reference["timestamp_utc"] < CUT) &
            reference["weather_regime"].eq(regime)], cols)
        models[regime] = fit(training, cols)
        medians[regime] = training[cols].median()
        thresholds[regime] = float(score(training, cols, models[regime])[
            "isolation_score"].quantile(.99))
    # Within-regime threshold margin is descriptive; scores are not comparable
    # across regimes. The boolean warning is the only cross-regime aggregation.
    hourly["threshold"] = hourly["regime"].map(thresholds)
    hourly["margin"] = hourly["isolation_score"] - hourly["threshold"]
    trajectory_rows, transition_rows, sensitivity_rows, missing = [], [], [], []
    for episode, g in hourly.groupby("episode_id"):
        g = g.sort_values("timestamp_utc").copy()
        for label, p in segments(g).items():
            trajectory_rows.append({
                "episode_id": episode, "severity": g["severity"].iloc[0],
                "anchor_kind": g["anchor_kind"].iloc[0], "period": label,
                "scored_hours": len(p), "raw_warning_hours": int(p["warning"].sum()),
                "raw_warning_fraction": float(p["warning"].mean()) if len(p) else np.nan,
                "sustained_hours": int(p["sustained_3_of_6"].sum()),
                "mean_threshold_margin": float(p["margin"].mean()) if len(p) else np.nan,
                "median_threshold_margin": float(p["margin"].median()) if len(p) else np.nan,
                "regimes": "|".join(sorted(p["regime"].dropna().unique()))
            })
        for col in ("warning", "sustained_3_of_6"):
            p = g[col].astype(bool)
            gap = g["timestamp_utc"].diff().ne(pd.Timedelta(hours=1))
            onset = p & (~p.shift(fill_value=False) | gap)
            transition_rows.append({
                "episode_id": episode, "signal": col,
                "activations": int(onset.sum()),
                "activations_last_48h": int(onset.loc[g["lead"] < 48].sum()),
                "hours_flagged_last_48h": int(p.loc[g["lead"] < 48].sum())
            })
        rows = events.loc[events["episode_id"].eq(episode)]
        anchor, kind = episode_anchor(rows)
        if anchor is None:
            continue
        try:
            raw = load_months(anchor-HORIZON-WARMUP, anchor)
        except FileNotFoundError as exc:
            missing.append({"episode_id": episode, "reason": str(exc)})
            continue
        raw = raw.sort_values("timestamp_utc").reset_index(drop=True)
        bad = ~raw["demand_mwh"].between(10000, 200000)
        raw.loc[bad, ["demand_mwh", "forecast_mwh", "interchange_mwh"]] = np.nan
        raw["t"] = (raw["timestamp_utc"]-raw["timestamp_utc"].iloc[0]).dt.total_seconds()/3600
        features = build_features(apply_zscore(raw, baseline)).merge(
            weather[["timestamp_utc", "weather_regime"]], on="timestamp_utc",
            how="left", validate="one_to_one")
        features = features.loc[features["timestamp_utc"].isin(g["timestamp_utc"])]
        for regime in REGIMES:
            f = clean(features.loc[features["weather_regime"].eq(regime)], cols)
            if f.empty:
                continue
            original = score(f, cols, models[regime])["isolation_score"]
            for family, names in groups.items():
                replaced = f.copy()
                replaced.loc[:, names] = medians[regime][names].to_numpy()
                modified = score(replaced, cols, models[regime])["isolation_score"]
                # Align by original frame index, not positional assumptions.
                delta = original - modified
                for period, selected in segments(f.assign(
                    lead=(anchor-f["timestamp_utc"]-pd.Timedelta(hours=1)
                          ).dt.total_seconds()/3600)).items():
                    idx = selected.index.intersection(delta.index)
                    if not len(idx):
                        continue
                    sensitivity_rows.append({
                        "episode_id": episode, "severity": g["severity"].iloc[0],
                        "anchor_kind": kind, "regime": regime,
                        "period": period, "family": family, "hours": len(idx),
                        "mean_score_change_on_median_replacement": float(delta.loc[idx].mean()),
                        "median_score_change_on_median_replacement": float(delta.loc[idx].median()),
                        "mean_abs_score_change": float(delta.loc[idx].abs().mean())
                    })
    trajectory = pd.DataFrame(trajectory_rows)
    trajectory.to_csv(OUT/"trajectory_periods.csv", index=False)
    pd.DataFrame(transition_rows).to_csv(OUT/"warning_transitions.csv", index=False)
    sensitivity = pd.DataFrame(sensitivity_rows)
    sensitivity.to_csv(OUT/"feature_family_sensitivity.csv", index=False)
    pd.DataFrame(missing, columns=["episode_id","reason"]).to_csv(
        OUT/"missing_inputs.csv", index=False)
    (OUT/"audit.json").write_text(json.dumps({
        "status": "exploratory post-hoc; no prospective validation",
        "trajectory_definition": "early 168-48h; late 48h; final 24h (nested)",
        "feature_sensitivity": "replace one family with regime-specific training medians; "
                               "difference in Isolation Forest score, not causal attribution",
        "warnings": [
            "Regime-specific score margins cannot be interpreted as standardized magnitudes",
            "Feature groups are correlated; replacement creates potentially off-manifold samples",
            "Early and late periods may have different weather-regime composition",
            "S3 operator-action anchors are not first public alert timestamps",
            "2021 normalization overlaps training; publication latency unverified",
            "Seven-day onset outputs must be regenerated if source data or model changes",
            "Only documented episodes examined; ordinary weather controls needed"
        ]
    }, indent=2)+"\n")
    print("\nSeven-day early vs late warning fractions:")
    p = trajectory.pivot(index="episode_id", columns="period",
                         values="raw_warning_fraction")
    print(p.round(3).to_string())
    print("\nActivation counts:")
    print(pd.DataFrame(transition_rows).to_string(index=False))
    print("\nFeature-family sensitivity (mean absolute score change; descriptive):")
    if not sensitivity.empty:
        s = sensitivity.groupby(["episode_id", "family"])[
            "mean_abs_score_change"].mean().unstack()
        print(s.round(4).to_string())
    else:
        print("No feature vectors available")
    print(f"\nSaved {OUT}/")


if __name__ == "__main__":
    main()
