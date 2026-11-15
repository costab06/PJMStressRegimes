"""Incremental-value challenge: weather/demand vs full multivariate detector.

Run: python -m gridregime.pipeline.challenge_incremental_value

Same Isolation Forest architecture, training period and per-regime p99
thresholds for two feature sets. Full model uses the existing 2021-normalized
feature contract; demand model uses ONLY temperature, demand and their trailing
changes. Evaluation uses event windows and complete later-year background
windows, explicitly NOT verified alert-free. No claim of prospective skill.
"""
from __future__ import annotations
import json
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler
from gridregime.pipeline.fit_temperature_regimes import ROOT, WEATHER, REGIMES, reference_features, weather_regimes
from gridregime.pipeline.ablate_anomaly_features import clean, fit, score
from gridregime.pipeline.evaluate_seven_day_onset import load_months
from gridregime.pipeline.build_anomaly_features import build_features
from gridregime.features.seasonal import apply_zscore

OUT=ROOT/"results/incremental_value_challenge_v1"
SRC=ROOT/"results/seven_day_onset_v1/seven_day_hourly.csv"
CUT=pd.Timestamp("2021-10-01",tz="UTC")
BASELINE_COLS=["temperature_24h_f","temperature_diff6h_f","temperature_diff24h_f",
               "demand_mwh","demand_diff3h","demand_diff24h"]
MODELS=("weather_demand","full_gridregime")
SEED=20261115


def enrich(frame, weather):
    x=frame.copy()
    x["timestamp_utc"]=pd.to_datetime(x["timestamp_utc"],utc=True)
    x=x.sort_values("timestamp_utc").reset_index(drop=True)
    x=x.merge(weather,on="timestamp_utc",how="left",validate="one_to_one")
    # Require continuous hours; rolling/differences never bridge a gap.
    segment=(~x["timestamp_utc"].diff().eq(pd.Timedelta(hours=1))).cumsum()
    for hours in (6,24):
        x[f"temperature_diff{hours}h_f"]=x.groupby(segment)["temperature_f"].diff(hours)
    for hours in (3,24):
        x[f"demand_diff{hours}h"]=x.groupby(segment)["demand_mwh"].diff(hours)
    return x


def build_from_raw(raw,baseline,weather):
    raw=raw.copy().sort_values("timestamp_utc").reset_index(drop=True)
    bad=~raw["demand_mwh"].between(10000,200000)
    raw.loc[bad,["demand_mwh","forecast_mwh","interchange_mwh"]]=np.nan
    raw["t"]=(raw["timestamp_utc"]-raw["timestamp_utc"].iloc[0]).dt.total_seconds()/3600
    return enrich(build_features(apply_zscore(raw,baseline)),weather)


def train_model(frame,columns):
    x=frame[columns].to_numpy(dtype=float)
    scaler=RobustScaler().fit(x)
    model=IsolationForest(n_estimators=300,max_samples=min(1024,len(x)),
                          random_state=SEED,n_jobs=-1).fit(scaler.transform(x))
    threshold=float(np.quantile(-model.score_samples(scaler.transform(x)),.99))
    return scaler,model,threshold


def predict(frame,columns,model):
    scaler,forest,threshold=model
    complete=frame[columns].replace([np.inf,-np.inf],np.nan).notna().all(axis=1)
    out=pd.Series(np.nan,index=frame.index,dtype=float)
    if complete.any():
        values=frame.loc[complete,columns].to_numpy(dtype=float)
        out.loc[complete]=-forest.score_samples(scaler.transform(values))
    return out, (out>threshold).where(out.notna())


def window_metrics(x,model):
    x=x.sort_values("timestamp_utc")
    if len(x)<160:return None
    early=x.loc[x["lead"]>=48,model].dropna()
    late=x.loc[x["lead"]<48,model].dropna()
    if len(early)<110 or len(late)<45:return None
    return {"scored_hours":len(early)+len(late),
            "early_fraction":float(early.mean()),"late_fraction":float(late.mean()),
            "increase":float(late.mean()-early.mean()),
            "overall_fraction":float(pd.concat([early,late]).mean())}


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    if not SRC.exists():raise FileNotFoundError(f"Run evaluate_seven_day_onset first: {SRC}")
    ev=pd.read_csv(SRC)
    ev["timestamp_utc"]=pd.to_datetime(ev["timestamp_utc"],utc=True)
    manifest=json.loads((ROOT/"data/processed/anomaly_features_v1/manifest.json").read_text())
    fullcols=manifest["feature_columns"]
    weather=weather_regimes(WEATHER)
    ref=enrich(reference_features(),weather)
    trained={}
    training_counts=[]
    for regime in REGIMES:
        for name,cols in (("weather_demand",BASELINE_COLS),("full_gridregime",fullcols)):
            train=clean(ref.loc[(ref["timestamp_utc"]<CUT)&
                                ref["weather_regime"].eq(regime)],cols)
            if len(train)<200:raise ValueError(f"Insufficient {regime} {name} training hours")
            trained[(regime,name)]=train_model(train,cols)
            training_counts.append({"regime":regime,"model":name,"train_hours":len(train)})
    # Use exact same pre-anchor seven-day hours and warmup as the existing study.
    catalog=pd.read_csv(ROOT/"metadata/events.csv")
    baseline=pd.read_parquet(ROOT/"data/processed/baseline_2021_frozen_v1.parquet")
    raw_months={}
    episodes=[];missing=[]
    for episode,g in ev.groupby("episode_id"):
        meta=catalog.loc[catalog["episode_id"].eq(episode)]
        alert=pd.to_datetime(meta["first_alert_time"].dropna(),utc=True)
        action=pd.to_datetime(meta["operator_action_time"].dropna(),utc=True)
        if len(alert):anchor=alert.min()
        elif len(action):anchor=action.min()
        else:continue
        try:raw=load_months(anchor-pd.Timedelta(days=10),anchor)
        except FileNotFoundError as exc:
            missing.append({"episode_id":episode,"reason":str(exc)});continue
        f=build_from_raw(raw,baseline,weather)
        f=f.loc[f["timestamp_utc"].isin(g["timestamp_utc"])].copy()
        if len(f)<160:
            missing.append({"episode_id":episode,"reason":"insufficient joined hours"});continue
        f["lead"]=(anchor-f["timestamp_utc"]-pd.Timedelta(hours=1)).dt.total_seconds()/3600
        f["episode_id"]=episode
        f["sample"]="event"
        episodes.append(f)
    # Later-year reference controls: complete seven-day windows from all
    # locally available monthly files, excluding +/- 14 days around any
    # catalog event anchor. Not verified alert-free.
    paths=sorted((ROOT/"data/raw/eia930").glob("PJM_20??-??.parquet"))
    years=sorted({int(p.stem[4:8]) for p in paths if p.stem[4:8].isdigit()
                  and int(p.stem[4:8])>=2022})
    event_anchors=[]
    for _,r in catalog.iterrows():
        for c in ("first_alert_time","operator_action_time"):
            t=pd.to_datetime(r[c],utc=True,errors="coerce")
            if pd.notna(t):event_anchors.append(t)
    controls=[]
    for year in years:
        year_paths=sorted((ROOT/"data/raw/eia930").glob(f"PJM_{year}-??.parquet"))
        if len(year_paths)<2:continue
        raw=pd.concat([pd.read_parquet(p) for p in year_paths],ignore_index=True)
        raw["timestamp_utc"]=pd.to_datetime(raw["timestamp_utc"],utc=True)
        if raw["timestamp_utc"].duplicated().any():
            missing.append({"episode_id":f"background_{year}","reason":"duplicate raw hours"})
            continue
        f=build_from_raw(raw,baseline,weather).set_index("timestamp_utc").sort_index()
        if f.empty:continue
        # Weekly nonoverlapping calendar windows; full seven days only.
        start=f.index.min().ceil("D")+pd.Timedelta(days=7)
        for end in pd.date_range(start,f.index.max(),freq="7D"):
            if any(abs(end-a)<pd.Timedelta(days=14) for a in event_anchors):continue
            idx=pd.date_range(end-pd.Timedelta(hours=167),end,freq="h",tz="UTC")
            if not idx.isin(f.index).all():continue
            w=f.loc[idx].copy().reset_index()
            w["lead"]=np.arange(167,-1,-1)
            w["episode_id"]=f"background_{year}_{end:%Y%m%d}"
            w["sample"]="background_unverified"
            controls.append(w)
    all_frames=episodes+controls
    if not all_frames:raise ValueError("No evaluation windows")
    rows=[]; hourly=[]
    for f in all_frames:
        f=f.copy()
        for name,cols in (("weather_demand",BASELINE_COLS),("full_gridregime",fullcols)):
            f[name]=pd.Series(np.nan,index=f.index,dtype="boolean")
            for regime in REGIMES:
                mask=f["weather_regime"].eq(regime).fillna(False)
                if not mask.any():continue
                scores,flags=predict(f.loc[mask],cols,trained[(regime,name)])
                f.loc[mask,name]=flags.astype("boolean")
                f.loc[mask,name+"_score"]=scores
        # Complete-case comparison: same observed hours for both models.
        f=f.dropna(subset=list(MODELS)).copy()
        for name in MODELS:
            m=window_metrics(f,name)
            if m:
                rows.append({"episode_id":f["episode_id"].iloc[0],
                             "sample":f["sample"].iloc[0],"model":name,**m})
        hourly.append(f[["episode_id","sample","timestamp_utc","lead",
                         "weather_regime",*MODELS,*(name+"_score" for name in MODELS)]])
    result=pd.DataFrame(rows)
    result.to_csv(OUT/"window_metrics.csv",index=False)
    pd.concat(hourly,ignore_index=True).to_csv(OUT/"hourly_comparison.csv",index=False)
    pd.DataFrame(training_counts).to_csv(OUT/"training_counts.csv",index=False)
    pd.DataFrame(missing,columns=["episode_id","reason"]).to_csv(
        OUT/"missing_inputs.csv",index=False)
    if not result.empty:
        print("\nEvent model comparison (same complete hours):")
        print(result.loc[result["sample"].eq("event")].pivot(
            index="episode_id",columns="model",
            values=["overall_fraction","increase"]).round(3).to_string())
        bg=result.loc[result["sample"].eq("background_unverified")]
        print("\nLater-year background windows:",bg["episode_id"].nunique())
        if not bg.empty:
            print(bg.groupby("model")[["overall_fraction","increase"]].agg(
                ["mean","median"]).round(3).to_string())
    print("\nMissing inputs:",len(missing))
    for item in missing[:12]:print(item["episode_id"],item["reason"])
    (OUT/"audit.json").write_text(json.dumps({
        "status":"exploratory incremental-value screen, NOT a prospective prediction study",
        "baseline_features":BASELINE_COLS,"full_feature_count":len(fullcols),
        "training":"Jan-Sep 2021; both models use regime-specific Isolation Forest p99",
        "reference":"later-year nonoverlapping 168h windows where raw monthly data exist",
        "exclusion":"background endpoints within 14 days of documented catalog anchors",
        "caveats":[
            "Background windows are not independently verified alert-free",
            "2021 seasonal baseline uses all of 2021; no independent 2021 holdout",
            "Baseline uses observed temperature and demand, not forecast-only inputs",
            "Different models' p99 thresholds do not ensure equal out-of-sample alert burden",
            "Background selection may include other PJM alerts and partial weather coverage",
            "The full model may detect weather effects not captured by six baseline features",
            "No point-in-time publication latency guarantee",
            "Episode selection and hyperparameters are exploratory, not preregistered"
        ]},indent=2)+"\n")
    print("\nSaved",OUT)


if __name__=="__main__":
    main()
