"""Exploratory feature-family ablation with continuous, month-matched scores.

Run: python -m gridregime.pipeline.ablate_anomaly_features
Uses the existing 2021 candidate baseline; NOT independent validation.
Fits each model only to Jan-Sep 2021, scores the full 2021 reference for
month-matched descriptive percentiles, and replays historical event windows.
"""
from __future__ import annotations

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
OUT = ROOT / "results/anomaly_ablation_v1"
FEAT = ROOT / "data/processed/anomaly_features_v1"
SCORE_NAMES = ("mahalanobis_d2", "isolation_score")


def families(cols):
    state = list(BASE)
    dynamics = [c for c in cols if "_diff" in c or "_std" in c]
    persistence = [c for c in cols if c.startswith("joint_")]
    relationships = [c for c in cols if c.startswith(("corr_", "lagcorr_"))]
    groups = {"state": state, "dynamics": dynamics, "persistence": persistence,
              "relationships": relationships, "all": list(cols)}
    if len(set(state+dynamics+persistence+relationships)) != len(cols):
        raise ValueError("Feature family classification is incomplete or overlapping")
    return groups


def clean(df, cols):
    return df.replace([np.inf, -np.inf], np.nan).dropna(subset=cols).copy()


def fit(train, cols):
    x = train[cols].to_numpy(dtype=float)
    scaler = RobustScaler().fit(x)
    z = scaler.transform(x)
    return scaler, LedoitWolf().fit(z), IsolationForest(
        n_estimators=300, max_samples=min(1024,len(z)),
        random_state=20261114, n_jobs=-1).fit(z)


def score(frame, cols, models):
    df = clean(frame, cols)
    if df.empty:
        return pd.DataFrame(columns=["timestamp_utc",*SCORE_NAMES])
    scaler,cov,forest = models
    z = scaler.transform(df[cols].to_numpy(dtype=float))
    delta = z-cov.location_
    df["mahalanobis_d2"] = np.einsum("ij,jk,ik->i",delta,cov.precision_,delta)
    df["isolation_score"] = -forest.score_samples(z)
    return df[["timestamp_utc",*SCORE_NAMES]].copy()


def episode_anchors(events, reference):
    anchors={}
    for episode,group in events.groupby("episode_id"):
        severity=group["severity"].unique()
        if len(severity)!=1:
            raise ValueError(f"Inconsistent severity for {episode}")
        severity=severity[0]
        col="operator_action_time" if severity=="S3" else "first_alert_time"
        times=pd.to_datetime(group[col].dropna(),utc=True)
        if len(times):
            anchors[episode]=(times.min(),severity,col)
        elif severity=="S1":
            # Retrospective anchor; not usable for prospective comparisons.
            p=ROOT/"data/processed/episode_features_unique.parquet"
            if not p.exists():
                raise FileNotFoundError(p)
            f=pd.read_parquet(p)
            f=f.loc[f["episode_id"].eq(episode)]
            anchor=pd.to_datetime(f.loc[f["load_z"].idxmax(),"timestamp_utc"],utc=True)
            anchors[episode]=(anchor,severity,"retrospective_peak_load_z")
        else:
            raise ValueError(f"Missing anchor for {episode}")
    return anchors


def run():
    manifest=json.loads((FEAT/"manifest.json").read_text())
    groups=families(manifest["feature_columns"])
    baseline=pd.read_parquet(ROOT/"data/processed/baseline_2021_frozen_v1.parquet")
    paths=[ROOT/f"data/raw/eia930/PJM_2021-{m:02d}.parquet" for m in range(1,13)]
    raw=pd.concat([pd.read_parquet(p) for p in paths],ignore_index=True)
    raw["timestamp_utc"]=pd.to_datetime(raw["timestamp_utc"],utc=True)
    raw=raw.sort_values("timestamp_utc").reset_index(drop=True)
    if raw["timestamp_utc"].duplicated().any():
        raise ValueError("Duplicate reference hours")
    bad=~raw["demand_mwh"].between(10000,200000)
    raw.loc[bad,["demand_mwh","forecast_mwh","interchange_mwh"]]=np.nan
    raw["t"]=(raw["timestamp_utc"]-raw["timestamp_utc"].iloc[0]).dt.total_seconds()/3600
    ref=build_features(apply_zscore(raw,baseline))
    events=pd.read_csv(ROOT/"metadata/events.csv")
    anchors=episode_anchors(events,ref)
    event_frames={eid:pd.read_parquet(FEAT/f"{eid}.parquet")
                  for eid in events["event_id"]}
    OUT.mkdir(parents=True,exist_ok=True)
    summary=[]
    hourly=[]
    calibration=[]
    for family,cols in groups.items():
        train=clean(ref.loc[ref["timestamp_utc"]<pd.Timestamp("2021-10-01",tz="UTC")],cols)
        models=fit(train,cols)
        reference=score(ref,cols,models)
        reference["month"]=reference["timestamp_utc"].dt.month
        # Month-matched percentiles use ALL 2021, including training rows.
        # This is a descriptive normalization, not a held-out null.
        month_scores={name:{m:np.sort(g[name].to_numpy(dtype=float))
                            for m,g in reference.groupby("month")}
                      for name in SCORE_NAMES}
        q99={name:float(score(train,cols,models)[name].quantile(.99))
             for name in SCORE_NAMES}
        cal=reference.loc[reference["timestamp_utc"]>=pd.Timestamp("2021-10-01",tz="UTC")]
        for name in SCORE_NAMES:
            calibration.append({"family":family,"detector":name,"feature_count":len(cols),
                                "training_p99":q99[name],
                                "calibration_exceedance_rate":float((cal[name]>q99[name]).mean())})
        parts=[]
        for eid,frame in event_frames.items():
            scored=score(frame,cols,models)
            scored["event_id"]=eid
            parts.append(scored)
        combined=pd.concat(parts,ignore_index=True).merge(
            events[["event_id","episode_id","severity"]],on="event_id",
            how="left",validate="many_to_one")
        conflicts=0
        # Overlapping event windows can have different warmup histories.
        # Drop conflicting scores rather than selecting an arbitrary window.
        for (episode,t),group in combined.groupby(["episode_id","timestamp_utc"],sort=True):
            vals=group[list(SCORE_NAMES)].to_numpy(dtype=float)
            if not np.allclose(vals,vals[0],rtol=1e-7,atol=1e-7):
                conflicts+=1
                continue
            anchor,severity,kind=anchors[episode]
            # UTC timestamps mark the START of an hourly interval.
            if t+pd.Timedelta(hours=1)>anchor:
                continue
            if t<anchor-pd.Timedelta(hours=48):
                continue
            month=t.month
            for j,name in enumerate(SCORE_NAMES):
                value=float(vals[0,j])
                distribution=month_scores[name].get(month,np.array([]))
                pct=float(np.searchsorted(distribution,value,side="right")/len(distribution)) if len(distribution) else np.nan
                hourly.append({"family":family,"detector":name,"episode_id":episode,
                               "severity":severity,"anchor_kind":kind,"timestamp_utc":t,
                               "hours_before_anchor":(anchor-t).total_seconds()/3600,
                               "score":value,"reference_month_percentile":pct,
                               "above_training_p99":value>q99[name]})
        print(f"{family}: {len(cols)} dimensions, conflicting overlap hours={conflicts}")
    trace=pd.DataFrame(hourly)
    trace.to_csv(OUT/"episode_hourly_ablation.csv",index=False)
    for (family,name,episode),g in trace.groupby(["family","detector","episode_id"]):
        g=g.sort_values("timestamp_utc")
        severity=g["severity"].iloc[0]
        row={"family":family,"detector":name,"episode_id":episode,
             "severity":severity,"anchor_kind":g["anchor_kind"].iloc[0],
             "observed_48h":len(g),"score_median_48h":float(g["score"].median()),
             "score_max_48h":float(g["score"].max()),
             "month_percentile_median_48h":float(g["reference_month_percentile"].median()),
             "month_percentile_p95_48h":float(g["reference_month_percentile"].quantile(.95)),
             "above_training_p99_hours_48h":int(g["above_training_p99"].sum())}
        # Trend is measured on the available scores, not a claimed prediction.
        if len(g)>=2:
            row["score_change_first_to_last"]=float(g["score"].iloc[-1]-g["score"].iloc[0])
            row["percentile_change_first_to_last"]=float(
                g["reference_month_percentile"].iloc[-1]-g["reference_month_percentile"].iloc[0])
        summary.append(row)
    result=pd.DataFrame(summary)
    result.to_csv(OUT/"episode_family_comparison.csv",index=False)
    pd.DataFrame(calibration).to_csv(OUT/"family_calibration.csv",index=False)
    (OUT/"audit.json").write_text(json.dumps({
        "status":"exploratory_post_hoc_not_independent_validation",
        "feature_groups":groups,
        "normalization":"2021 month-hour baseline, fitted using all 2021",
        "model_training":"Jan-Sep 2021",
        "month_reference":"All 2021, includes model training and baseline fitting",
        "warnings":["No point-in-time EIA publication guarantee",
                    "Only two S3 episodes; no model selection from episode outcomes",
                    "S1 anchor selected retrospectively",
                    "Overlapping event windows with conflicting scores omitted",
                    "Anomaly scores across different dimensional models are not directly comparable; use within-family percentiles",
                    "2021 data are not independently certified normal operations"]
    },indent=2)+"\n")
    print("\nEpisode-level month-matched median percentiles (descriptive):")
    print(result.pivot_table(index=["episode_id","severity"],columns=["family","detector"],
                             values="month_percentile_median_48h").round(3).to_string())
    print(f"\nSaved {OUT}/")
    return result


if __name__=="__main__":
    run()
