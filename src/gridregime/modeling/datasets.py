"""Load immutable feature snapshots and episode metadata without fetching source data."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import pandas as pd
from .contracts import FeatureDataset, FROZEN_FEATURES


def load_feature_snapshot(path: str | Path, *, expected_sha256: str | None = None) -> dict:
    path = Path(path)
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("Feature snapshot SHA-256 mismatch")
    payload = json.loads(raw)
    if payload.get("feature_version") != "frozen-v1" or payload.get("status") != "features-only-not-a-risk-prediction":
        raise ValueError("Unexpected feature snapshot version or status")
    if set(payload.get("features", {})) != set(FROZEN_FEATURES):
        raise ValueError("Incomplete frozen-v1 feature snapshot")
    return payload


def load_feature_sequence(paths, *, expected_hashes=None, episode_id=None) -> FeatureDataset:
    paths = list(paths)
    if not paths:
        raise ValueError("No feature snapshots supplied")
    if expected_hashes is not None and len(expected_hashes) != len(paths):
        raise ValueError("Expected hash count differs from snapshot count")
    snapshots = [load_feature_snapshot(p, expected_sha256=None if expected_hashes is None else expected_hashes[i]) for i,p in enumerate(paths)]
    baselines = {p["baseline_sha256"] for p in snapshots}
    authorities = {p["ba"] for p in snapshots}
    if len(baselines) != 1 or len(authorities) != 1:
        raise ValueError("Mixed baselines or balancing authorities")
    rows = [{"timestamp_utc": p["as_of"], "ba": p["ba"], **p["features"]} for p in snapshots]
    frame = pd.DataFrame(rows)
    times = pd.to_datetime(frame["timestamp_utc"], utc=True)
    if times.duplicated().any():
        raise ValueError("Duplicate feature observation timestamps")
    frame["timestamp_utc"] = times
    frame = frame.sort_values("timestamp_utc").reset_index(drop=True)
    # This digest identifies the ordered set of underlying source versions.
    combined = hashlib.sha256("\n".join(p["source_sha256"] for p in sorted(snapshots, key=lambda x:x["as_of"])).encode()).hexdigest()
    return FeatureDataset(frame=frame, ba=next(iter(authorities)), source_sha256=combined,
        baseline_sha256=next(iter(baselines)), episode_id=episode_id,
        publication_time_verified=False)


def load_episode_catalog(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={"episode_id": "string", "event_id": "string"})
    required = {"episode_id", "event_id", "severity", "window_start", "event_end"}
    if not required.issubset(frame.columns):
        raise ValueError("Episode catalog missing required fields")
    if frame[list(required)].isna().any().any():
        raise ValueError("Episode catalog has missing required fields")
    if frame["event_id"].duplicated().any() or not frame["severity"].isin(["S1","S2","S3"]).all():
        raise ValueError("Duplicate event IDs or unknown severity")
    start = pd.to_datetime(frame["window_start"], utc=True)
    end = pd.to_datetime(frame["event_end"], utc=True)
    if (start > end).any():
        raise ValueError("Episode window ends before start")
    for episode, group in frame.groupby("episode_id"):
        if group["severity"].nunique() != 1:
            raise ValueError(f"Conflicting severity for episode {episode}")
    return frame
