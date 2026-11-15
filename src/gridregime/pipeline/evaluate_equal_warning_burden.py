"""Equal-warning-burden challenge with chronological background split.

Run:
  python -m gridregime.pipeline.challenge_incremental_value
  python -m gridregime.pipeline.evaluate_equal_warning_burden

Exploratory only: backgrounds unverified, small sample, event outcomes reused.
Calibration uses EARLIER background windows; later windows never set thresholds.
"""
from __future__ import annotations
import json
import numpy as np
import pandas as pd
from gridregime.pipeline.fit_temperature_regimes import ROOT

OUT=ROOT/"results/equal_warning_burden_v1"
SOURCE=ROOT/"results/incremental_value_challenge_v1/hourly_comparison.csv"
MODELS=("weather_demand","full_gridregime")
TARGETS=(.01,.05,.10)


def metrics(frame,signal):
    x=frame.sort_values("timestamp_utc")
    early=x.loc[x["lead"]>=48,signal]
    late=x.loc[x["lead"]<48,signal]
    if len(x)<160 or len(early)<110 or len(late)<45:return None
    first=x.loc[x[signal],"lead"]
    return {"hours":len(x),"warning_fraction":float(x[signal].mean()),
            "early_fraction":float(early.mean()),"late_fraction":float(late.mean()),
            "late_minus_early":float(late.mean()-early.mean()),
            "any_warning":bool(x[signal].any()),
            "first_warning_lead_h":float(first.max()) if len(first) else np.nan}


def main():
    if not SOURCE.exists():raise FileNotFoundError(f"First run challenge_incremental_value: {SOURCE}")
    OUT.mkdir(parents=True,exist_ok=True)
    d=pd.read_csv(SOURCE)
    d["timestamp_utc"]=pd.to_datetime(d["timestamp_utc"],utc=True)
    scorecols=[m+"_score" for m in MODELS]
    missing=[c for c in scorecols if c not in d.columns]
    if missing:raise ValueError(f"Missing {missing}; pull latest code and rerun challenge_incremental_value")
    # Enforce identical complete-case hours across both models.
    d=d.replace([np.inf,-np.inf],np.nan).dropna(subset=scorecols).copy()
    background=d.loc[d["sample"].eq("background_unverified")].copy()
    windows=background.groupby("episode_id")["timestamp_utc"].max().sort_values()
    if len(windows)<6:raise ValueError(f"Only {len(windows)} complete background windows; need >=6")
    split=len(windows)//2
    calibration_ids=set(windows.index[:split])
    test_ids=set(windows.index[split:])
    cal=background.loc[background["episode_id"].isin(calibration_ids)]
    test=background.loc[background["episode_id"].isin(test_ids)]
    # Distinct windows; test observations must occur strictly after calibration.
    if cal["timestamp_utc"].max()>=test["timestamp_utc"].min():
        raise ValueError("Chronological calibration/test windows overlap")
    print(f"Background windows: calibration={len(calibration_ids)}, held-out={len(test_ids)}")
    thresholds=[]; rows=[]
    for target in TARGETS:
        for model in MODELS:
            column=model+"_score"
            threshold=float(cal[column].quantile(1-target))
            thresholds.append({"target_background_fraction":target,"model":model,
                               "threshold":threshold,"calibration_hours":len(cal),
                               "calibration_fraction":float((cal[column]>threshold).mean())})
            for sample,subset in (("calibration_background",cal),
                                  ("heldout_background",test),
                                  ("event",d.loc[d["sample"].eq("event")])):
                for episode,g in subset.groupby("episode_id"):
                    g=g.copy()
                    g["warn"]=g[column]>threshold
                    met=metrics(g,"warn")
                    if met:
                        rows.append({"target_background_fraction":target,
                                     "model":model,"sample":sample,
                                     "episode_id":episode,**met})
    results=pd.DataFrame(rows)
    thresholds=pd.DataFrame(thresholds)
    thresholds.to_csv(OUT/"calibrated_thresholds.csv",index=False)
    results.to_csv(OUT/"window_comparison.csv",index=False)
    windows.rename("window_end_utc").to_csv(OUT/"background_windows.csv")
    print("\nHeld-out background warning burden (window averages):")
    held=results.loc[results["sample"].eq("heldout_background")]
    print(held.groupby(["target_background_fraction","model"])[
        ["warning_fraction","any_warning"]].mean().round(3).to_string())
    print("\nEvent warning fractions (window averages):")
    ev=results.loc[results["sample"].eq("event")]
    print(ev.groupby(["target_background_fraction","model"])[
        ["warning_fraction","any_warning","late_minus_early"]].mean().round(3).to_string())
    print("\nEvent details at nominal 5% calibration target:")
    print(ev.loc[ev["target_background_fraction"].eq(.05)].pivot(
        index="episode_id",columns="model",
        values=["warning_fraction","first_warning_lead_h"]).round(2).to_string())
    print("\nNOTE: Nominal targets are CALIBRATION rates, not matched held-out rates.")
    print("Compare held-out burden before interpreting event detection.")
    (OUT/"audit.json").write_text(json.dumps({
        "status":"exploratory, not a validated operational warning system",
        "split":"background windows ordered by end timestamp; earlier floor(n/2) calibrate, later windows evaluate",
        "thresholds":"per-model empirical upper quantile of pooled calibration background hours",
        "target_fractions":TARGETS,
        "calibration_windows":sorted(calibration_ids),
        "heldout_windows":sorted(test_ids),
        "warnings":[
            "Only nine background windows previously observed; sampling uncertainty high",
            "Background windows are not verified alert-free",
            "Events are selected retrospectively and used in prior exploratory analysis",
            "Events may overlap calibration background chronology; only background windows split",
            "Models use 2021 normalization; all-year baseline overlap remains",
            "No guarantee of equal held-out false-alarm burden",
            "Event first-warning lead can be left-censored at seven days",
            "Event S3 anchors are operator action times, not first public alert",
            "Observed weather and demand and EIA publication latency preclude prospective claims",
            "No uncertainty intervals or independent external validation"
        ]},indent=2)+"\n")
    print("\nSaved",OUT)


if __name__=="__main__":
    main()
