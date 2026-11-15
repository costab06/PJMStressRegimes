"""Exploratory weather/demand-matched control and simple-baseline challenge.

Run: python -m gridregime.pipeline.test_weather_demand_confounding

Controls are 2021 reference windows, NOT certified alert-free. Matching uses
24h temperature and absolute demand level. 2021 baseline overlaps training,
so this is a confounding screen, NOT an out-of-sample performance estimate.
"""
from __future__ import annotations
import json
import numpy as np
import pandas as pd
from gridregime.pipeline.fit_temperature_regimes import ROOT, WEATHER, REGIMES, weather_regimes, reference_features
from gridregime.pipeline.ablate_anomaly_features import clean, fit, score
from gridregime.pipeline.evaluate_seven_day_onset import HORIZON

OUT=ROOT/"results/weather_demand_controls_v1"
SRC=ROOT/"results/seven_day_onset_v1/seven_day_hourly.csv"
TRAIN_CUT=pd.Timestamp("2021-10-01",tz="UTC")
N_CONTROLS=5
SEED=20261115


def summarize(x, warning):
    early=x.loc[x["lead"]>=48]
    late=x.loc[x["lead"]<48]
    return {"early_fraction":float(early[warning].mean()) if len(early) else np.nan,
            "late_fraction":float(late[warning].mean()) if len(late) else np.nan,
            "increase":float(late[warning].mean()-early[warning].mean()) if len(early) and len(late) else np.nan,
            "overall_fraction":float(x[warning].mean()),"hours":len(x)}


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    if not SRC.exists():
        raise FileNotFoundError(f"Run evaluate_seven_day_onset first: {SRC}")
    events=pd.read_csv(SRC)
    events["timestamp_utc"]=pd.to_datetime(events["timestamp_utc"],utc=True)
    manifest=json.loads((ROOT/"data/processed/anomaly_features_v1/manifest.json").read_text())
    allcols=manifest["feature_columns"]
    weather=weather_regimes(WEATHER)
    ref=reference_features().merge(weather,on="timestamp_utc",how="left",validate="one_to_one")
    # Use raw demand (not demand_z alone) as a transparent baseline.
    raw=pd.concat([pd.read_parquet(ROOT/f"data/raw/eia930/PJM_2021-{m:02d}.parquet")
                   for m in range(1,13)],ignore_index=True)
    raw["timestamp_utc"]=pd.to_datetime(raw["timestamp_utc"],utc=True)
    raw=raw[["timestamp_utc","demand_mwh"]]
    if raw["timestamp_utc"].duplicated().any():
        raise ValueError("Duplicate reference demand hours")
    ref=ref.merge(raw,on="timestamp_utc",how="left",validate="one_to_one")
    # Existing event scores are preserved; attach weather and demand from
    # available monthly historical EIA data, not from event names.
    event_months=set((t.year,t.month) for t in events["timestamp_utc"])
    frames=[]
    for year,month in sorted(event_months):
        p=ROOT/f"data/raw/eia930/PJM_{year}-{month:02d}.parquet"
        if not p.exists():
            raise FileNotFoundError(p)
        f=pd.read_parquet(p)[["timestamp_utc","demand_mwh"]]
        f["timestamp_utc"]=pd.to_datetime(f["timestamp_utc"],utc=True)
        frames.append(f)
    ev_demand=pd.concat(frames,ignore_index=True)
    if ev_demand["timestamp_utc"].duplicated().any():
        raise ValueError("Duplicate event demand timestamps")
    events=events.merge(ev_demand,on="timestamp_utc",how="left",validate="many_to_one")
    events=events.merge(weather[["timestamp_utc","temperature_24h_f"]],
                        on="timestamp_utc",how="left",validate="many_to_one")
    models={}; thresholds={}; demand_q={}
    for regime in REGIMES:
        training=clean(ref.loc[(ref["timestamp_utc"]<TRAIN_CUT)&
                                 ref["weather_regime"].eq(regime)],allcols)
        models[regime]=fit(training,allcols)
        thresholds[regime]=float(score(training,allcols,models[regime])[
            "isolation_score"].quantile(.99))
        demand_q[regime]=float(training["demand_mwh"].quantile(.99))
    ref_parts=[]
    for regime in REGIMES:
        f=clean(ref.loc[ref["weather_regime"].eq(regime)],allcols)
        if f.empty:continue
        s=score(f,allcols,models[regime])
        f=f.merge(s[["timestamp_utc","isolation_score"]],on="timestamp_utc",
                  validate="one_to_one")
        f["warning"]=f["isolation_score"]>thresholds[regime]
        f["demand_only_warning"]=f["demand_mwh"]>demand_q[regime]
        ref_parts.append(f)
    ref=pd.concat(ref_parts,ignore_index=True).sort_values("timestamp_utc")
    events["demand_only_warning"]=events.apply(
        lambda r: bool(r["demand_mwh"]>demand_q[r["regime"]])
        if pd.notna(r["demand_mwh"]) and r["regime"] in demand_q else False,axis=1)
    # Construct complete 168-hour reference windows, with no gap bridging.
    ref=ref.set_index("timestamp_utc").sort_index()
    candidates=[]
    for end in pd.date_range("2021-01-08","2021-12-31",freq="24h",tz="UTC"):
        idx=pd.date_range(end-pd.Timedelta(hours=167),end,freq="h",tz="UTC")
        if not idx.isin(ref.index).all():continue
        w=ref.loc[idx].copy()
        if len(w)!=168:continue
        candidates.append({"end":end,"temp":float(w["temperature_24h_f"].mean()),
                           "demand":float(w["demand_mwh"].mean()),
                           "regime_hot":float(w["weather_regime"].eq("hot").mean()),
                           "regime_cold":float(w["weather_regime"].eq("cold").mean())})
    cand=pd.DataFrame(candidates)
    if cand.empty:raise ValueError("No complete 2021 control windows")
    rows=[]; pairs=[]; diagnostics=[]
    for episode,g in events.groupby("episode_id"):
        g=g.sort_values("timestamp_utc")
        if len(g)<160:
            diagnostics.append({"episode_id":episode,"reason":"fewer than 160 event hours"})
            continue
        if g[["temperature_24h_f","demand_mwh"]].isna().any().any():
            diagnostics.append({"episode_id":episode,"reason":"missing weather or demand"})
            continue
        target={"temp":float(g["temperature_24h_f"].mean()),
                "demand":float(g["demand_mwh"].mean()),
                "regime_hot":float(g["regime"].eq("hot").mean()),
                "regime_cold":float(g["regime"].eq("cold").mean())}
        # Predeclared scales: 10F and 10GW plus weather-regime composition.
        distance=(((cand["temp"]-target["temp"])/10)**2+
                  ((cand["demand"]-target["demand"])/10000)**2+
                  4*(cand["regime_hot"]-target["regime_hot"])**2+
                  4*(cand["regime_cold"]-target["regime_cold"])**2)
        eligible=cand.assign(distance=distance).sort_values("distance")
        # Non-overlapping controls within each episode, greedy nearest matching.
        chosen=[]
        for _,candidate in eligible.iterrows():
            if all(abs(candidate["end"]-c["end"])>=pd.Timedelta(days=7) for c in chosen):
                chosen.append(candidate)
            if len(chosen)>=N_CONTROLS:break
        g=g.copy();g["lead"]=g["hours_before_anchor_at_availability"]
        for signal in ("warning","demand_only_warning"):
            rows.append({"episode_id":episode,"sample":"event","control_end_utc":"",
                         "signal":signal,**summarize(g,signal)})
        for c in chosen:
            idx=pd.date_range(c["end"]-pd.Timedelta(hours=167),c["end"],freq="h",tz="UTC")
            w=ref.loc[idx].copy().reset_index()
            w["lead"]=np.arange(167,-1,-1)
            pairs.append({"episode_id":episode,"control_end_utc":c["end"],
                          "distance":float(c["distance"]),
                          "event_mean_temp_f":target["temp"],"control_mean_temp_f":float(c["temp"]),
                          "event_mean_demand_mwh":target["demand"],
                          "control_mean_demand_mwh":float(c["demand"]),
                          "event_hot_fraction":target["regime_hot"],
                          "control_hot_fraction":float(c["regime_hot"]),
                          "event_cold_fraction":target["regime_cold"],
                          "control_cold_fraction":float(c["regime_cold"])})
            for signal in ("warning","demand_only_warning"):
                rows.append({"episode_id":episode,"sample":"control",
                             "control_end_utc":c["end"],"signal":signal,
                             **summarize(w,signal)})
    results=pd.DataFrame(rows)
    results.to_csv(OUT/"event_control_metrics.csv",index=False)
    pd.DataFrame(pairs).to_csv(OUT/"matched_pairs_audit.csv",index=False)
    pd.DataFrame(diagnostics,columns=["episode_id","reason"]).to_csv(
        OUT/"missing_or_incomplete.csv",index=False)
    if not results.empty:
        means=results.groupby(["episode_id","sample","signal"])[
            ["early_fraction","late_fraction","increase","overall_fraction"]].mean()
        print("\nEvent vs matched 2021 control averages:")
        print(means.round(3).to_string())
        print("\nMatching distances (smaller is closer; no guarantee of adequate matches):")
        print(pd.DataFrame(pairs).groupby("episode_id")["distance"].agg(
            ["min","max"]).round(3).to_string())
    print("\nIMPORTANT: Controls are not certified alert-free; 2021 overlaps training.")
    print("Demand-only is a deliberately simple comparator, not a weather forecast.")
    print("No prospective discrimination claim is supported by this experiment.")
    (OUT/"audit.json").write_text(json.dumps({
        "status":"exploratory confounding screen; not independent validation",
        "controls":"up to five non-overlapping 168h 2021 windows per episode",
        "matching":"mean 24h observed temperature, mean demand, cold/hot regime fractions",
        "matching_distance":"squared scaled differences (10F, 10000 MWh, regime weights 4)",
        "simple_benchmark":"weather-regime-specific training p99 of absolute demand",
        "warnings":[
            "2021 controls may contain actual alerts and are not verified negative cases",
            "2021 controls overlap detector training and seasonal normalization",
            "Control selection uses entire window and future-observed weather/demand",
            "Only mean weather/demand matched, not hourly trajectory or forecast changes",
            "No statistical significance or prospective forecast skill is claimed",
            "S3 action timestamps are not first public alert times",
            "Demand-only comparison is not a complete weather-and-demand model",
            "Reference data publication latency and intervention history unavailable"
        ]},indent=2)+"\n")
    print("\nSaved",OUT)


if __name__=="__main__":
    main()
