"""Inspect S2 warnings lost to persistence and hourly alert timelines.

Run: python -m gridregime.pipeline.inspect_s2_warning_timelines
Prerequisite: python -m gridregime.pipeline.evaluate_early_warning
This is descriptive, not an independently validated operating-rule comparison.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from gridregime.pipeline.evaluate_early_warning import (
    ROOT, OUT as PRIOR, MODEL_OUT, SWEEP_OUT, DETECTOR, Q,
    RULES, persistence,
)

OUT = ROOT / "results/s2_warning_diagnostics_v1"


def runs(frame, col):
    """Contiguous true runs, including breaks caused by missing observations."""
    f = frame.sort_values("timestamp_utc").copy()
    flag = f[col].fillna(False).astype(bool)
    gaps = f["timestamp_utc"].diff().ne(pd.Timedelta(hours=1))
    starts = flag & (~flag.shift(fill_value=False) | gaps)
    ids = starts.cumsum()
    records = []
    for _, g in f.loc[flag].groupby(ids[flag]):
        records.append({
            "start_utc": g["timestamp_utc"].iloc[0],
            "end_utc_exclusive": g["timestamp_utc"].iloc[-1] + pd.Timedelta(hours=1),
            "duration_hours": len(g),
        })
    return records


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    prior = pd.read_csv(PRIOR / "episode_persistent_warnings.csv")
    s2 = prior.loc[prior["severity"].eq("S2")]
    wide = s2.pivot(index="episode_id", columns="rule", values="detected")
    missed = wide.loc[wide["raw"].eq(True) & wide["3_of_6"].eq(False)].index.tolist()
    print("\nS2 episode-level detection:")
    print(wide.to_string())
    print("\nDetected raw, missed 3-of-6:", missed)

    thresholds = pd.read_csv(SWEEP_OUT / "thresholds.csv")
    thresholds = thresholds.loc[thresholds["detector"].eq(DETECTOR) &
                                np.isclose(thresholds["training_quantile"], Q)]
    cutoffs = dict(zip(thresholds["regime"], thresholds["score_threshold"]))
    trace = pd.read_csv(MODEL_OUT / "episode_hourly_temperature_scores.csv")
    trace["timestamp_utc"] = pd.to_datetime(trace["timestamp_utc"], utc=True)
    trace = trace.loc[trace["detector"].eq(DETECTOR) &
                      trace["severity"].eq("S2")].copy()
    if trace["regime"].map(cutoffs).isna().any():
        raise ValueError("Missing regime threshold")
    trace["warning"] = trace["score"] > trace["regime"].map(cutoffs)
    anchors = pd.read_csv(PRIOR / "first_alert_anchor_audit.csv")
    anchors["first_documented_alert_utc"] = pd.to_datetime(
        anchors["first_documented_alert_utc"], utc=True)
    hourly, run_rows, summary = [], [], []
    for episode, g in trace.groupby("episode_id"):
        anchor = anchors.loc[anchors["episode_id"].eq(episode),
                             "first_documented_alert_utc"].iloc[0]
        g = g.loc[g["timestamp_utc"] + pd.Timedelta(hours=1) <= anchor].copy()
        if g["timestamp_utc"].duplicated().any():
            raise ValueError(f"Duplicate episode hours: {episode}")
        if g.empty:
            continue
        raw_runs = runs(g, "warning")
        row = {"episode_id": episode, "raw_warning_hours": int(g["warning"].sum()),
               "raw_warning_runs": len(raw_runs),
               "longest_raw_run_hours": max(
                   [r["duration_hours"] for r in raw_runs], default=0),
               "observed_hours": len(g)}
        for rule, (n, window) in RULES.items():
            p = persistence(g, n, window)
            if rule == "raw":
                continue
            g[rule] = p.set_index("timestamp_utc")["trigger"].reindex(
                g["timestamp_utc"]).to_numpy(dtype=bool)
            row[f"{rule}_trigger_hours"] = int(g[rule].sum())
        for r in raw_runs:
            run_rows.append({"episode_id": episode, **r,
                             "lead_at_start_hours": (anchor-r["start_utc"]-
                                 pd.Timedelta(hours=1)).total_seconds()/3600})
        g["episode_id"] = episode
        g["hours_before_first_alert_at_availability"] = (
            anchor - g["timestamp_utc"] - pd.Timedelta(hours=1)
        ).dt.total_seconds()/3600
        hourly.append(g[["episode_id", "timestamp_utc", "regime", "score",
                         "warning", "3_of_6", "6_of_12",
                         "hours_before_first_alert_at_availability"]])
        summary.append(row)
    pd.concat(hourly, ignore_index=True).to_csv(OUT/"s2_hourly_timelines.csv", index=False)
    pd.DataFrame(run_rows).to_csv(OUT/"s2_raw_warning_runs.csv", index=False)
    result = pd.DataFrame(summary).sort_values("episode_id")
    result["missed_by_3_of_6"] = result["episode_id"].isin(missed)
    result.to_csv(OUT/"s2_episode_diagnostics.csv", index=False)
    print("\nS2 warning diagnostics:")
    print(result.to_string(index=False))
    print(f"\nSaved {OUT}/")
    print("Caution: 48h traces were generated using prior episode anchors;")
    print("these diagnostics do not establish operational validity or causality.")


if __name__ == "__main__":
    run()
