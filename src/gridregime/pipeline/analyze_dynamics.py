"""Exploratory pre-anchor coupling, persistence, and recovery dynamics.

Run: python -m gridregime.pipeline.analyze_dynamics
This is a descriptive, small-sample analysis, NOT a prediction benchmark.
S1 uses a retrospective peak-load anchor and is not a prospective control.
"""
from __future__ import annotations

from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
F = ("load_z", "fe_z", "ramp3_z", "ic_z")
PAIRS = tuple(combinations(F, 2))
WINDOW = 48
HALF = 24
THRESHOLD = 4.0


def corr(a: pd.Series, b: pd.Series) -> float:
    if a.std() < 1e-10 or b.std() < 1e-10:
        return float("nan")
    return float(a.corr(b))


def longest_run(flags: np.ndarray) -> int:
    best = current = 0
    for flag in flags:
        current = current + 1 if flag else 0
        best = max(best, current)
    return best


def run() -> pd.DataFrame:
    events = pd.read_csv(ROOT / "metadata/events.csv")
    data = pd.read_parquet(ROOT / "data/processed/episode_features_unique.parquet")
    data["timestamp_utc"] = pd.to_datetime(data["timestamp_utc"], utc=True)
    output = ROOT / "results/tables"
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    trace_rows = []
    for eid, group in events.groupby("episode_id", sort=True):
        severity = group["severity"].unique()
        if len(severity) != 1:
            raise ValueError(f"{eid}: conflicting severity labels")
        severity = severity[0]
        subset = data.loc[data["episode_id"].eq(eid)].sort_values("timestamp_utc").copy()
        if subset.empty or subset["timestamp_utc"].duplicated().any():
            raise ValueError(f"{eid}: missing or duplicated episode hours")
        anchor_col = "operator_action_time" if severity == "S3" else "first_alert_time"
        anchors = pd.to_datetime(group[anchor_col].dropna().replace("", pd.NA).dropna(), utc=True)
        if len(anchors):
            anchor = anchors.min()
            anchor_kind = anchor_col
        elif severity == "S1":
            anchor = subset.loc[subset["load_z"].idxmax(), "timestamp_utc"]
            anchor_kind = "retrospective_peak_load_z"
        else:
            raise ValueError(f"{eid}: no documented anchor")
        # Strictly before anchor. For an exact-hour anchor, the previous hour
        # is the latest eligible observation.
        last = anchor.ceil("h") - pd.Timedelta(hours=1)
        expected = pd.date_range(end=last, periods=WINDOW, freq="h", tz="UTC")
        window = subset.set_index("timestamp_utc").reindex(expected)
        complete = window[list(F)].notna().all(axis=1).all()
        row = {"episode_id":eid, "severity":severity,
               "anchor_kind":anchor_kind, "anchor_utc":anchor.isoformat(),
               "complete_48h":bool(complete),
               "observed_hours":int(window[list(F)].notna().all(axis=1).sum())}
        if not complete:
            rows.append(row)
            continue
        first, last_half = window.iloc[:HALF], window.iloc[HALF:]
        x = window[list(F)].to_numpy(dtype=float)
        magnitude = np.linalg.norm(x, axis=1)
        early_magnitude, late_magnitude = magnitude[:HALF], magnitude[HALF:]
        row.update({
            "joint_median_first24":float(np.median(early_magnitude)),
            "joint_median_last24":float(np.median(late_magnitude)),
            "joint_median_change":float(np.median(late_magnitude)-np.median(early_magnitude)),
            "joint_last":float(magnitude[-1]),
            "joint_p95":float(np.quantile(magnitude,.95)),
            "hours_above_4_first24":int((early_magnitude>THRESHOLD).sum()),
            "hours_above_4_last24":int((late_magnitude>THRESHOLD).sum()),
            "longest_run_above_4":longest_run(magnitude>THRESHOLD),
            # Recovery proxy: fraction of one-hour magnitude changes moving
            # toward the baseline origin. Not physical grid recovery time.
            "fraction_steps_toward_origin":float(np.mean(np.diff(magnitude)<0)),
            "mean_positive_magnitude_step":float(np.maximum(np.diff(magnitude),0).mean()),
            "mean_negative_magnitude_step":float(np.maximum(-np.diff(magnitude),0).mean()),
        })
        early_corr, late_corr = [], []
        for a,b in PAIRS:
            key = f"{a}__{b}"
            c1,c2 = corr(first[a],first[b]),corr(last_half[a],last_half[b])
            row[f"corr_first24_{key}"]=c1
            row[f"corr_last24_{key}"]=c2
            row[f"corr_change_{key}"]=c2-c1
            if np.isfinite(c1) and np.isfinite(c2):
                early_corr.append(abs(c1))
                late_corr.append(abs(c2))
        row["mean_abs_pair_corr_first24"]=float(np.mean(early_corr)) if early_corr else np.nan
        row["mean_abs_pair_corr_last24"]=float(np.mean(late_corr)) if late_corr else np.nan
        row["mean_abs_pair_corr_change"]=row["mean_abs_pair_corr_last24"]-row["mean_abs_pair_corr_first24"]
        for t,m in zip(expected,magnitude):
            trace_rows.append({"episode_id":eid,"severity":severity,
                               "timestamp_utc":t.isoformat(),
                               "hours_to_anchor":(t-anchor).total_seconds()/3600,
                               "joint_magnitude":float(m)})
        rows.append(row)
    table=pd.DataFrame(rows).sort_values(["severity","episode_id"])
    table.to_csv(output/"pre_event_dynamics_summary.csv",index=False)
    pd.DataFrame(trace_rows).to_csv(output/"pre_event_dynamics_trace.csv",index=False)
    show=["episode_id","severity","complete_48h","observed_hours",
          "joint_median_change","mean_abs_pair_corr_change",
          "longest_run_above_4","fraction_steps_toward_origin"]
    print(table[show].to_string(index=False))
    print(f"\nComplete 48h windows: {table['complete_48h'].sum()}/{len(table)}")
    print("Saved results/tables/pre_event_dynamics_summary.csv")
    print("Saved results/tables/pre_event_dynamics_trace.csv")
    print("\nInterpretation constraints: Pearson correlations over 24h are noisy;")
    print("diurnal cycles and shared baseline normalization can create spurious coupling.")
    print("The S1 anchor is retrospective; this is not a prospective classification test.")
    return table


if __name__=="__main__":
    run()
