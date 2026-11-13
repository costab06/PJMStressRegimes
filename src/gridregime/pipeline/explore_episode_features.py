"""Episode-level exploratory analysis of frozen-v1 PJM feature windows.

Run: python -m gridregime.pipeline.explore_episode_features
All outputs are descriptive, not predictive or statistically independent hourly tests.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
FEATURES = ("load_z", "fe_z", "ramp3_z", "ic_z")


def run() -> pd.DataFrame:
    catalog = pd.read_csv(ROOT / "metadata/events.csv")
    manifest = json.loads((ROOT / "data/processed/event_features_manifest.json").read_text())
    known = {x["event_id"] for x in manifest["events"]}
    if set(catalog["event_id"]) != known:
        raise ValueError("Feature manifest and event catalog disagree")
    output = ROOT / "results/tables"
    output.mkdir(parents=True, exist_ok=True)
    episodes = []
    hourly_frames = []
    for episode_id, group in catalog.groupby("episode_id", sort=True):
        labels = group["severity"].dropna().unique()
        if len(labels) != 1:
            raise ValueError(f"{episode_id}: conflicting severity labels {labels}")
        frames = []
        for event_id in group["event_id"]:
            path = ROOT / "data/processed/event_features" / f"{event_id}.parquet"
            frame = pd.read_parquet(path)
            frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
            frames.append(frame)
        combined = pd.concat(frames, ignore_index=True)
        # Compare duplicated timestamps rather than arbitrarily selecting a
        # potentially conflicting revision from overlapping event windows.
        for timestamp, same_hour in combined.groupby("timestamp_utc"):
            if len(same_hour) > 1:
                vals = same_hour[list(FEATURES)].to_numpy(dtype=float)
                first = vals[0]
                if not np.allclose(vals, first, rtol=1e-10, atol=1e-10, equal_nan=True):
                    # First three hours can lack ramp in one window but not
                    # another. Prefer the defined value only when other
                    # overlapping feature values are identical.
                    for col in FEATURES:
                        observed = same_hour[col].dropna().to_numpy(dtype=float)
                        if len(observed) > 1 and not np.allclose(observed, observed[0], rtol=1e-10, atol=1e-10):
                            raise ValueError(f"{episode_id}: conflicting {col} at {timestamp}")
        # Keep the first non-null value for each feature. At overlapping window
        # boundaries, ramp may be undefined in one window but defined in another.
        hourly = combined.groupby("timestamp_utc", as_index=False).agg({
            **{col: "first" for col in FEATURES},
        }).sort_values("timestamp_utc")
        if hourly["timestamp_utc"].duplicated().any():
            raise ValueError(f"{episode_id}: duplicate timestamps after consolidation")
        complete = hourly.dropna(subset=list(FEATURES)).copy()
        if complete.empty:
            raise ValueError(f"{episode_id}: no complete feature hours")
        complete["episode_id"] = episode_id
        complete["severity"] = labels[0]
        hourly_frames.append(complete)
        z = complete[list(FEATURES)].to_numpy(dtype=float)
        # This is a descriptive measure of joint configuration, not a
        # calibrated probability, risk score, or inferential statistic.
        joint = np.linalg.norm(z, axis=1)
        row = {
            "episode_id": episode_id,
            "severity": labels[0],
            "event_rows": len(group),
            "unique_hours": len(hourly),
            "complete_feature_hours": len(complete),
            "joint_l2_median": float(np.median(joint)),
            "joint_l2_p95": float(np.quantile(joint, 0.95)),
            "joint_l2_max": float(joint.max()),
        }
        for col in FEATURES:
            x = complete[col].to_numpy(dtype=float)
            row[f"{col}_median"] = float(np.median(x))
            row[f"{col}_p95_abs"] = float(np.quantile(np.abs(x), 0.95))
            row[f"{col}_max_abs"] = float(np.abs(x).max())
            row[f"{col}_delta_p95_abs"] = float(np.quantile(np.abs(np.diff(x)), 0.95)) if len(x) > 1 else np.nan
        episodes.append(row)
    table = pd.DataFrame(episodes).sort_values(["severity", "episode_id"])
    table.to_csv(output / "episode_feature_summary.csv", index=False)
    hourly = pd.concat(hourly_frames, ignore_index=True)
    hourly.to_parquet(ROOT / "data/processed/episode_features_unique.parquet", index=False)
    print(table[["episode_id", "severity", "event_rows", "unique_hours",
                 "complete_feature_hours", "joint_l2_median", "joint_l2_p95"]].to_string(index=False))
    print("\nEpisode counts by severity:")
    print(table.groupby("severity").size().to_string())
    print("\nSaved results/tables/episode_feature_summary.csv")
    print("Saved data/processed/episode_features_unique.parquet")
    print("\nNOTE: Joint L2 is descriptive only; feature correlations and temporal")
    print("dependence make it unsuitable as a calibrated stress probability.")
    return table


if __name__ == "__main__":
    run()
