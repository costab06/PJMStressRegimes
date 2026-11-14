"""Pre-event descriptive trajectories, preserving frozen-v1 feature definitions.

Run: python -m gridregime.pipeline.compare_trajectories
Anchors: first operator action (S3), first alert (S2), or peak LoadZ
for S1 descriptive comparison only. Never use S1 peak as a prediction label.
"""
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
F = ["load_z", "fe_z", "ramp3_z", "ic_z"]
HORIZONS = (6, 12, 24, 48)


def run():
    events = pd.read_csv(ROOT / "metadata/events.csv")
    data = pd.read_parquet(ROOT / "data/processed/episode_features_unique.parquet")
    data["timestamp_utc"] = pd.to_datetime(data["timestamp_utc"], utc=True)
    dest = ROOT / "results/tables"
    dest.mkdir(parents=True, exist_ok=True)
    rows, traces = [], []
    for eid, group in events.groupby("episode_id"):
        subset = data.loc[data["episode_id"].eq(eid)].sort_values("timestamp_utc").copy()
        severity = group["severity"].iloc[0]
        col = "operator_action_time" if severity == "S3" else "first_alert_time"
        anchors = pd.to_datetime(group[col].dropna().replace("", pd.NA).dropna(), utc=True)
        if len(anchors):
            anchor = anchors.min()
            anchor_kind = col
        elif severity == "S1":
            # Peak of the feature within the observed episode is retrospective
            # and therefore unsuitable for predictive evaluation.
            anchor = subset.loc[subset["load_z"].idxmax(), "timestamp_utc"]
            anchor_kind = "retrospective_peak_load_z"
        else:
            raise ValueError(f"{eid}: no documented pre-event anchor")
        # Avoid using the hour containing a subhour alert/action; include only
        # completed hourly observations strictly before the decision.
        pre = subset.loc[subset["timestamp_utc"] < anchor].copy()
        pre["hours_before_anchor"] = (anchor - pre["timestamp_utc"]).dt.total_seconds() / 3600
        for horizon in HORIZONS:
            win = pre.loc[pre["hours_before_anchor"] <= horizon].copy()
            row = {"episode_id":eid,"severity":severity,"anchor_kind":anchor_kind,
                   "anchor_utc":anchor.isoformat(),"horizon_hours":horizon,
                   "observed_hours":len(win),"complete_window":False}
            # Require every completed hourly sample in the intended horizon.
            expected = pd.date_range(anchor.ceil("h") - pd.Timedelta(hours=horizon),
                                     anchor.ceil("h") - pd.Timedelta(hours=1),freq="h",tz="UTC")
            if len(win) == horizon and pd.DatetimeIndex(win["timestamp_utc"]).equals(expected):
                row["complete_window"] = True
                x = win[F].to_numpy(dtype=float)
                magnitude = np.linalg.norm(x,axis=1)
                velocity = np.linalg.norm(np.diff(x,axis=0),axis=1)
                row.update({"joint_median":float(np.median(magnitude)),
                            "joint_p95":float(np.quantile(magnitude,.95)),
                            "joint_last":float(magnitude[-1]),
                            "joint_first":float(magnitude[0]),
                            "joint_net_change":float(magnitude[-1]-magnitude[0]),
                            "vector_displacement":float(np.linalg.norm(x[-1]-x[0])),
                            "step_velocity_mean":float(velocity.mean()),
                            "step_velocity_p95":float(np.quantile(velocity,.95)),
                            "hours_joint_above_4":int((magnitude>4).sum())})
                for i,f in enumerate(F):
                    row[f+"_start"]=float(x[0,i])
                    row[f+"_end"]=float(x[-1,i])
                    row[f+"_change"]=float(x[-1,i]-x[0,i])
                if horizon==48:
                    win["anchor_kind"]=anchor_kind
                    win["anchor_utc"]=anchor
                    traces.append(win)
            rows.append(row)
    table=pd.DataFrame(rows)
    table.to_csv(dest/"pre_event_trajectory_summary.csv",index=False)
    if traces:
        pd.concat(traces,ignore_index=True).to_csv(dest/"pre_event_trajectory_48h.csv",index=False)
    print(table.loc[table["horizon_hours"].eq(24),
          ["episode_id","severity","anchor_kind","observed_hours","complete_window",
           "joint_net_change","vector_displacement","step_velocity_mean","hours_joint_above_4"]].to_string(index=False))
    print("\nComplete windows by horizon:")
    print(table.groupby("horizon_hours")["complete_window"].agg(["sum","count"]).to_string())
    print("\nSaved results/tables/pre_event_trajectory_summary.csv")
    if traces:
        print("Saved results/tables/pre_event_trajectory_48h.csv")
    print("CAUTION: S1 anchor is retrospectively selected; comparison is descriptive only.")
    return table


if __name__=="__main__":
    run()
