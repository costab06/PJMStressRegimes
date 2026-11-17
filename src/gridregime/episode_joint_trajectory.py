"""Descriptive episode-level comparison of frozen-v1 PJM feature trajectories.

Uses the existing episode-deduplicated feature table. This is an exploratory
analysis, not a trained classifier or an estimate of predictive performance.
S2 first-alert and S3 emergency-action anchors are operationally different.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import numpy as np
import pandas as pd
from gridregime.episode_timeseries_audit import FEATURES, episode_anchors


def compare_episodes(hourly: pd.DataFrame, events: pd.DataFrame,
                     hours: int = 24, joint_threshold: float = 4.0):
    if hours < 2 or joint_threshold <= 0:
        raise ValueError("invalid_window_or_threshold")
    required = {"timestamp_utc", "episode_id", "severity", *FEATURES}
    if required - set(hourly):
        raise ValueError(f"missing_columns:{sorted(required-set(hourly))}")
    df = hourly.copy()
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    if df["timestamp_utc"].isna().any():
        raise ValueError("invalid_timestamp")
    if df.duplicated(["episode_id", "timestamp_utc"]).any():
        raise ValueError("duplicate_episode_timestamp")
    for col in FEATURES:
        df[col] = pd.to_numeric(df[col], errors="raise")
    anchors = episode_anchors(events)
    records = []
    for a in anchors.to_dict("records"):
        eid, sev, anchor = a["episode_id"], a["severity"], a["anchor_utc"]
        sub = df[df["episode_id"] == eid].set_index("timestamp_utc").sort_index()
        if not sub.empty and (sub["severity"] != sev).any():
            raise ValueError(f"severity_mismatch:{eid}")
        row = {"episode_id": eid, "severity": sev,
               "anchor_type": a["anchor_type"],
               "anchor_utc": anchor.isoformat() if pd.notna(anchor) else None,
               "window_hours": hours, "joint_threshold": joint_threshold}
        if pd.isna(anchor):
            row["status"] = "missing_anchor"
            records.append(row)
            continue
        end = anchor.floor("h") - pd.Timedelta(hours=1)
        idx = pd.date_range(end=end, periods=hours, freq="h", tz="UTC")
        window = sub.reindex(idx)[list(FEATURES)]
        row["complete_hours"] = int(window.notna().all(axis=1).sum())
        if row["complete_hours"] != hours:
            row["status"] = "incomplete"
            records.append(row)
            continue
        x = window.to_numpy(dtype=float)
        if not np.isfinite(x).all():
            row["status"] = "incomplete"
            records.append(row)
            continue
        joint = np.sqrt(np.square(x).sum(axis=1))
        above = joint >= joint_threshold
        run = max_run = 0
        for flag in above:
            run = run + 1 if flag else 0
            max_run = max(max_run, run)
        row.update(status="complete", joint_peak=float(joint.max()),
                   joint_mean=float(joint.mean()),
                   joint_start=float(joint[0]), joint_end=float(joint[-1]),
                   joint_delta=float(joint[-1] - joint[0]),
                   joint_hours_above_threshold=int(above.sum()),
                   joint_longest_run_hours=int(max_run),
                   joint_last6h_mean=float(joint[-6:].mean()),
                   joint_first6h_mean=float(joint[:6].mean()))
        for i, feature in enumerate(FEATURES):
            vals = x[:, i]
            row[f"{feature}_peak_abs"] = float(np.abs(vals).max())
            row[f"{feature}_delta"] = float(vals[-1] - vals[0])
        records.append(row)
    return pd.DataFrame.from_records(records)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--hourly", type=Path,
                   default=Path("data/processed/episode_features_unique.parquet"))
    p.add_argument("--events", type=Path, default=Path("metadata/events.csv"))
    p.add_argument("--hours", type=int, default=24)
    p.add_argument("--joint-threshold", type=float, default=4.0)
    p.add_argument("--output", type=Path,
                   default=Path("results/episode_joint_trajectory_v1/episode_comparison.csv"))
    args = p.parse_args()
    hourly = pd.read_parquet(args.hourly) if args.hourly.suffix == ".parquet" else pd.read_csv(args.hourly)
    result = compare_episodes(hourly, pd.read_csv(args.events), args.hours, args.joint_threshold)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    print(result[["episode_id", "severity", "status", "joint_peak",
                  "joint_delta", "joint_hours_above_threshold",
                  "joint_longest_run_hours"]].to_string(index=False))
    print(f"Saved {args.output}")
    print("CAVEAT: S2 uses first alert; S3 uses emergency action. S3 first-alert times are absent from events.csv.")


if __name__ == "__main__":
    main()
