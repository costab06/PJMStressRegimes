"""Episode-level descriptive replay of exploratory anomaly scores.

Run: python -m gridregime.pipeline.summarize_anomaly_episodes
No predictive claims: score thresholds use in-sample-normalized 2021.
"""
from pathlib import Path
import json

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "results/anomaly_exploratory_v1"
SCORES = ("mahalanobis_d2", "isolation_score")


def run():
    audit_path = OUT / "audit.json"
    scores_path = OUT / "event_hourly_scores.csv"
    if not audit_path.exists() or not scores_path.exists():
        raise FileNotFoundError("Run python -m gridregime.pipeline.fit_anomaly_exploratory first")
    audit = json.loads(audit_path.read_text())
    thresholds = audit["thresholds_training_p99"]
    events = pd.read_csv(ROOT / "metadata/events.csv")
    scores = pd.read_csv(scores_path,parse_dates=["timestamp_utc"])
    scores["timestamp_utc"] = pd.to_datetime(scores["timestamp_utc"],utc=True)
    if scores.duplicated(["event_id","timestamp_utc"]).any():
        raise ValueError("Duplicate event/hour score")
    joined = scores.merge(events[["event_id","episode_id","severity"]],
                          on="event_id",how="left",validate="many_to_one")
    if joined["episode_id"].isna().any():
        raise ValueError("Unrecognized event ID")
    # Overlapping event windows must yield identical scores for identical hours.
    # Differences near event-window boundaries are expected due to rolling warmup;
    # do not silently select one. Exclude conflicting hours from evaluation.
    conflicts=[]
    rows=[]
    for (episode,t),group in joined.groupby(["episode_id","timestamp_utc"],sort=True):
        values=group[list(SCORES)].to_numpy(dtype=float)
        if not np.allclose(values,values[0],rtol=1e-7,atol=1e-7):
            conflicts.append({"episode_id":episode,"timestamp_utc":t.isoformat(),
                              "event_ids":";".join(group["event_id"].astype(str))})
            continue
        rows.append({"episode_id":episode,"timestamp_utc":t,
                     **{name:float(values[0,i]) for i,name in enumerate(SCORES)}})
    dedup=pd.DataFrame(rows)
    if dedup.empty:
        raise ValueError("No consistent episode scores")
    conflict_path=OUT/"overlap_conflicts.csv"
    pd.DataFrame(conflicts,columns=["episode_id","timestamp_utc","event_ids"]).to_csv(conflict_path,index=False)
    # Excluded hours must be visible to the reader.
    summary=[]
    traces=[]
    for episode,group in events.groupby("episode_id",sort=True):
        severity=group["severity"].unique()
        if len(severity)!=1:
            raise ValueError(f"{episode}: inconsistent labels")
        severity=severity[0]
        subset=dedup.loc[dedup["episode_id"].eq(episode)].sort_values("timestamp_utc")
        if subset.empty:
            continue
        anchor_col="operator_action_time" if severity=="S3" else "first_alert_time"
        anchors=pd.to_datetime(group[anchor_col].dropna(),utc=True)
        if len(anchors):
            anchor=anchors.min()
            anchor_kind=anchor_col
        elif severity=="S1":
            # Retrospective peak load anchor, from frozen episode features.
            p=ROOT/"data/processed/episode_features_unique.parquet"
            if not p.exists():
                raise FileNotFoundError(p)
            features=pd.read_parquet(p)
            f=features.loc[features["episode_id"].eq(episode)]
            anchor=pd.to_datetime(f.loc[f["load_z"].idxmax(),"timestamp_utc"],utc=True)
            anchor_kind="retrospective_peak_load_z"
        else:
            raise ValueError(f"{episode}: no anchor")
        # Hour labels are START times. Only fully elapsed hours qualify.
        eligible=subset.loc[subset["timestamp_utc"]+pd.Timedelta(hours=1)<=anchor]
        row={"episode_id":episode,"severity":severity,"anchor_kind":anchor_kind,
             "anchor_utc":anchor.isoformat()}
        for horizon in (24,48):
            expected=pd.date_range(end=anchor.ceil("h")-pd.Timedelta(hours=1),
                                   periods=horizon,freq="h",tz="UTC")
            window=eligible.set_index("timestamp_utc").reindex(expected)
            row[f"observed_{horizon}h"]=int(window[SCORES[0]].notna().sum())
            row[f"complete_{horizon}h"]=bool(window[list(SCORES)].notna().all().all())
            for name in SCORES:
                valid=window[name].dropna()
                row[f"{name}_max_{horizon}h"]=float(valid.max()) if len(valid) else np.nan
                row[f"{name}_exceed_hours_{horizon}h"]=int((valid>thresholds[name]).sum())
                row[f"{name}_exceed_fraction_{horizon}h"]=float((valid>thresholds[name]).mean()) if len(valid) else np.nan
        for _,item in eligible.iterrows():
            if item["timestamp_utc"]<anchor-pd.Timedelta(hours=48):
                continue
            traces.append({"episode_id":episode,"severity":severity,
                           "anchor_kind":anchor_kind,"timestamp_utc":item["timestamp_utc"],
                           "hours_before_anchor":(anchor-item["timestamp_utc"]).total_seconds()/3600,
                           **{name:item[name] for name in SCORES},
                           **{name+"_exceeds":bool(item[name]>thresholds[name]) for name in SCORES}})
        summary.append(row)
    table=pd.DataFrame(summary).sort_values(["severity","episode_id"])
    table.to_csv(OUT/"episode_anomaly_summary.csv",index=False)
    pd.DataFrame(traces).to_csv(OUT/"episode_preanchor_scores.csv",index=False)
    print(table[["episode_id","severity","observed_48h",
                 "mahalanobis_d2_exceed_hours_48h","isolation_score_exceed_hours_48h"]].to_string(index=False))
    print(f"\nExcluded conflicting overlap hours: {len(conflicts)}")
    print("Saved episode_anomaly_summary.csv, episode_preanchor_scores.csv, overlap_conflicts.csv")
    print("CAUTION: exploratory; baseline normalization is in-sample, 2021 training is not")
    print("screened for emergencies, and publication latency has not been verified.")
    print("S1 uses a retrospective anchor; these results are NOT prospective lead times.")
    return table


if __name__=="__main__":
    run()
