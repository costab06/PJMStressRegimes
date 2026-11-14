"""Exploratory anomaly detectors; 2021 normalization is IN-SAMPLE.

Run: python -m gridregime.pipeline.fit_anomaly_exploratory
Requires build_anomaly_features and raw 2021 monthly Parquets.
Not a prospective model, operational alert, or independent validation.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler

from gridregime.features.seasonal import apply_zscore
from gridregime.pipeline.build_anomaly_features import BASE, build_features

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "data/raw/eia930"
OUT = ROOT / "results/anomaly_exploratory_v1"
FEAT = ROOT / "data/processed/anomaly_features_v1"


def complete_vectors(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    return df.replace([np.inf, -np.inf], np.nan).dropna(subset=cols).copy()


def score(df: pd.DataFrame, cols: list[str], scaler: RobustScaler,
          cov: LedoitWolf, forest: IsolationForest) -> pd.DataFrame:
    clean = complete_vectors(df, cols)
    if clean.empty:
        return pd.DataFrame(columns=["timestamp_utc","mahalanobis_d2","isolation_score"])
    z = scaler.transform(clean[cols].to_numpy(dtype=float))
    delta = z - cov.location_
    clean["mahalanobis_d2"] = np.einsum("ij,jk,ik->i",delta,cov.precision_,delta)
    clean["isolation_score"] = -forest.score_samples(z)
    return clean[["timestamp_utc","mahalanobis_d2","isolation_score"]]


def run() -> dict:
    paths = [RAW / f"PJM_2021-{m:02d}.parquet" for m in range(1,13)]
    if any(not p.exists() for p in paths):
        raise FileNotFoundError("Missing 2021 raw monthly data")
    manifest_path = FEAT / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError("Run python -m gridregime.pipeline.build_anomaly_features first")
    manifest = json.loads(manifest_path.read_text())
    cols = manifest["feature_columns"]
    baseline_path = ROOT / "data/processed/baseline_2021_frozen_v1.parquet"
    baseline = pd.read_parquet(baseline_path)
    frames = [pd.read_parquet(p) for p in paths]
    raw = pd.concat(frames, ignore_index=True)
    raw["timestamp_utc"] = pd.to_datetime(raw["timestamp_utc"],utc=True)
    raw = raw.sort_values("timestamp_utc").reset_index(drop=True)
    if raw["timestamp_utc"].duplicated().any():
        raise ValueError("Duplicate reference timestamps")
    # Exclude known implausible demand measurements, and prevent any rolling
    # window from treating a corrupted observation as valid.
    invalid = ~raw["demand_mwh"].between(10_000,200_000)
    raw.loc[invalid,["demand_mwh","forecast_mwh","interchange_mwh"]] = np.nan
    raw["t"] = (raw["timestamp_utc"]-raw["timestamp_utc"].iloc[0]).dt.total_seconds()/3600
    base = apply_zscore(raw,baseline)
    expanded = build_features(base)
    train = complete_vectors(expanded.loc[expanded["timestamp_utc"] < pd.Timestamp("2021-10-01",tz="UTC")],cols)
    calibration = complete_vectors(expanded.loc[expanded["timestamp_utc"] >= pd.Timestamp("2021-10-01",tz="UTC")],cols)
    if len(train) < 1000 or len(calibration) < 100:
        raise ValueError(f"Insufficient train/calibration observations: {len(train)}/{len(calibration)}")
    X = train[cols].to_numpy(dtype=float)
    scaler = RobustScaler(quantile_range=(25,75)).fit(X)
    z = scaler.transform(X)
    # Covariance shrinkage regularizes highly redundant engineered dimensions.
    cov = LedoitWolf().fit(z)
    forest = IsolationForest(n_estimators=300,max_samples=min(1024,len(z)),
                             random_state=20261114,n_jobs=-1).fit(z)
    OUT.mkdir(parents=True,exist_ok=True)
    train_scores = score(train,cols,scaler,cov,forest)
    calibration_scores = score(calibration,cols,scaler,cov,forest)
    # Thresholds use the training distribution only, not historical events.
    thresholds = {c:float(train_scores[c].quantile(.99)) for c in
                  ("mahalanobis_d2","isolation_score")}
    calibration_scores.to_csv(OUT/"calibration_2021_scores.csv",index=False)
    catalog = pd.read_csv(ROOT/"metadata/events.csv")
    event_rows=[]
    for event_id in catalog["event_id"]:
        path=FEAT/f"{event_id}.parquet"
        if not path.exists():
            raise FileNotFoundError(path)
        data=pd.read_parquet(path)
        if any(c not in data for c in cols):
            raise ValueError(f"{event_id}: missing feature columns")
        scored=score(data,cols,scaler,cov,forest)
        scored.insert(0,"event_id",event_id)
        event_rows.append(scored)
        print(f"{event_id}: {len(scored)} scored hours")
    event_scores=pd.concat(event_rows,ignore_index=True)
    event_scores.to_csv(OUT/"event_hourly_scores.csv",index=False)
    audit={"status":"exploratory_in_sample_normalization",
           "feature_version":manifest["version"],
           "feature_columns":cols,
           "train_period":"2021-01-01 to 2021-09-30 UTC",
           "calibration_period":"2021-10-01 to 2021-12-31 UTC",
           "train_hours":len(train),"calibration_hours":len(calibration),
           "excluded_bad_demand_hours":int(invalid.sum()),
           "models":["LedoitWolf_shrinkage_Mahalanobis","IsolationForest"],
           "thresholds_training_p99":thresholds,
           "calibration_exceedance_rates":{c:float((calibration_scores[c]>v).mean())
                                           for c,v in thresholds.items()},
           "baseline_sha256":hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
           "feature_manifest_sha256":hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
           "caveats":[
               "The 2021 baseline uses all of 2021: the chronological calibration is not independent.",
               "EIA-930 publication delays and revisions have not been point-in-time verified.",
               "The training period has not been independently screened for known emergencies.",
               "Event windows may overlap and must be consolidated by episode before evaluation.",
               "These scores and thresholds must not be interpreted as operational warnings."
           ]}
    (OUT/"audit.json").write_text(json.dumps(audit,indent=2,sort_keys=True)+"\n")
    print(f"\nTrain: {len(train)} hours; calibration: {len(calibration)} hours")
    print(f"Feature dimensions: {len(cols)}")
    print("Training 99th-percentile thresholds:",thresholds)
    print("Calibration exceedance rates:",audit["calibration_exceedance_rates"])
    print(f"Saved {OUT}/")
    return audit


if __name__=="__main__":
    run()
