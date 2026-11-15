"""Seven-day pre-alert stress onset study, with historical warmup.

Run: python -m gridregime.pipeline.evaluate_seven_day_onset
Requires raw EIA-930 PJM_YYYY-MM.parquet for each relevant month. If absent,
report missing inputs rather than extending 72h event files artificially.
S3 uses operator-action anchor ONLY as a separate descriptive fallback.
"""
from __future__ import annotations

import json
import numpy as np
import pandas as pd
from gridregime.pipeline.fit_temperature_regimes import (
    ROOT, WEATHER, REGIMES, reference_features, weather_regimes
)
from gridregime.pipeline.ablate_anomaly_features import clean, fit, score
from gridregime.pipeline.build_anomaly_features import build_features
from gridregime.features.seasonal import apply_zscore
from gridregime.pipeline.evaluate_early_warning import persistence

OUT = ROOT / "results/seven_day_onset_v1"
HORIZON = pd.Timedelta(days=7)
WARMUP = pd.Timedelta(hours=72)
Q = .99


def load_months(start, end):
    months = pd.period_range(start.tz_localize(None).to_period("M"),
                             end.tz_localize(None).to_period("M"), freq="M")
    paths = [ROOT / f"data/raw/eia930/PJM_{m.year}-{m.month:02d}.parquet" for m in months]
    missing = [str(p.relative_to(ROOT)) for p in paths if not p.exists()]
    if missing:
        raise FileNotFoundError(
            "Seven-day onset requires raw historical hours. Missing:\n" +
            "\n".join(missing) +
            "\nAcquire these months before rerunning; 72-hour event slices cannot support 7 days.")
    raw = pd.concat([pd.read_parquet(p) for p in paths], ignore_index=True)
    raw["timestamp_utc"] = pd.to_datetime(raw["timestamp_utc"], utc=True)
    raw = raw.sort_values("timestamp_utc").drop_duplicates("timestamp_utc", keep=False)
    if raw.empty:
        raise ValueError("No unambiguous hourly records")
    return raw.loc[raw["timestamp_utc"].between(start, end, inclusive="both")].copy()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    events = pd.read_csv(ROOT / "metadata/events.csv")
    baseline = pd.read_parquet(ROOT / "data/processed/baseline_2021_frozen_v1.parquet")
    manifest = json.loads((ROOT/"data/processed/anomaly_features_v1/manifest.json").read_text())
    cols = manifest["feature_columns"]
    weather = weather_regimes(WEATHER)
    reference = reference_features().merge(weather, on="timestamp_utc", how="left",
                                           validate="one_to_one")
    cut = pd.Timestamp("2021-10-01", tz="UTC")
    models, cutoffs = {}, {}
    for regime in REGIMES:
        training = clean(reference.loc[
            (reference["timestamp_utc"] < cut) &
            reference["weather_regime"].eq(regime)], cols)
        models[regime] = fit(training, cols)
        cutoffs[regime] = float(score(training, cols, models[regime])[
            "isolation_score"].quantile(Q))
    hourly, episodes, missing = [], [], []
    for episode, group in events.groupby("episode_id"):
        severity = group["severity"].iloc[0]
        alert = pd.to_datetime(group["first_alert_time"].dropna(), utc=True)
        action = pd.to_datetime(group["operator_action_time"].dropna(), utc=True)
        if len(alert):
            anchor, kind = alert.min(), "first_documented_alert"
        elif len(action):
            anchor, kind = action.min(), "operator_action_NOT_first_alert"
        else:
            missing.append({"episode_id": episode, "reason": "no prospective anchor"})
            continue
        start = anchor-HORIZON-WARMUP
        end = anchor
        try:
            raw = load_months(start, end)
        except FileNotFoundError as exc:
            missing.append({"episode_id": episode, "reason": str(exc)})
            continue
        raw = raw.sort_values("timestamp_utc").reset_index(drop=True)
        for col in ("demand_mwh", "forecast_mwh", "interchange_mwh"):
            if col not in raw:
                raise ValueError(f"{episode}: missing {col}")
        bad = ~raw["demand_mwh"].between(10000, 200000)
        raw.loc[bad, ["demand_mwh", "forecast_mwh", "interchange_mwh"]] = np.nan
        raw["t"] = (raw["timestamp_utc"]-raw["timestamp_utc"].iloc[0]).dt.total_seconds()/3600
        features = build_features(apply_zscore(raw, baseline))
        features = features.merge(weather[["timestamp_utc", "weather_regime"]],
                                  on="timestamp_utc", how="left", validate="one_to_one")
        parts = []
        for regime in REGIMES:
            sub = clean(features.loc[features["weather_regime"].eq(regime)], cols)
            if sub.empty:
                continue
            s = score(sub, cols, models[regime])
            s["regime"] = regime
            s["warning"] = s["isolation_score"] > cutoffs[regime]
            parts.append(s)
        if not parts:
            missing.append({"episode_id": episode, "reason": "no complete scored hours"})
            continue
        scored = pd.concat(parts, ignore_index=True).sort_values("timestamp_utc")
        scored = scored.loc[(scored["timestamp_utc"] >= anchor-HORIZON) &
                            (scored["timestamp_utc"]+pd.Timedelta(hours=1) <= anchor)].copy()
        if scored.empty:
            missing.append({"episode_id": episode, "reason": "no scores in seven-day window"})
            continue
        if scored["timestamp_utc"].duplicated().any():
            raise ValueError(f"{episode}: duplicate scored hours")
        persist = persistence(scored, 3, 6)
        scored["sustained_3_of_6"] = persist.set_index("timestamp_utc")[
            "trigger"].reindex(scored["timestamp_utc"]).to_numpy(dtype=bool)
        scored["episode_id"] = episode
        scored["severity"] = severity
        scored["anchor_kind"] = kind
        scored["hours_before_anchor_at_availability"] = (
            anchor-scored["timestamp_utc"]-pd.Timedelta(hours=1)).dt.total_seconds()/3600
        hourly.append(scored)
        result = {"episode_id": episode, "severity": severity, "anchor_kind": kind,
                  "scored_hours": len(scored), "possible_hours": 168,
                  "raw_warning_hours": int(scored["warning"].sum()),
                  "sustained_warning_hours": int(scored["sustained_3_of_6"].sum())}
        for col in ("warning", "sustained_3_of_6"):
            flagged = scored.loc[scored[col], "timestamp_utc"]
            result[f"{col}_first_lead_hours"] = (
                (anchor-flagged.min()-pd.Timedelta(hours=1)).total_seconds()/3600
                if len(flagged) else np.nan)
            result[f"{col}_left_censored"] = bool(
                len(flagged) and flagged.min() == scored["timestamp_utc"].min())
        episodes.append(result)
    pd.DataFrame(missing, columns=["episode_id", "reason"]).to_csv(
        OUT/"missing_inputs.csv", index=False)
    if hourly:
        pd.concat(hourly, ignore_index=True).to_csv(OUT/"seven_day_hourly.csv", index=False)
    result = pd.DataFrame(episodes)
    result.to_csv(OUT/"episode_onset_summary.csv", index=False)
    (OUT/"audit.json").write_text(json.dumps({
        "status": "exploratory; no point-in-time validation",
        "horizon_hours": 168, "warmup_hours": 72,
        "threshold": "fixed training p99 Isolation Forest by weather regime",
        "sustained_rule": "3 of preceding 6 hours, current hour above threshold",
        "cautions": [
            "S3 operator-action anchors are not first public alerts",
            "2021 normalization and detector training are not independent",
            "Left-censored warnings may begin earlier than seven days",
            "Incomplete historical months and weather coverage must be audited",
            "Historical actual measurements may not have been available in real time",
            "Existing episode catalog is selected, not an unbiased population"
        ]}, indent=2)+"\n")
    print("\nSeven-day episode onset summary:")
    print(result.to_string(index=False) if not result.empty else "No episodes scored")
    print("\nMissing input episodes:", len(missing))
    for row in missing:
        print(row["episode_id"], ":", row["reason"])
    print("\nSaved", OUT)


if __name__ == "__main__":
    main()
