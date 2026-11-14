"""Build exploratory multivariate anomaly features without fitting a detector.

Usage:
  python -m gridregime.pipeline.build_anomaly_features
Produces event feature Parquets and an audit manifest. Requires existing
frozen-v1 event feature materialization; does not mutate frozen-v1 files.
"""
from __future__ import annotations

import hashlib
import json
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
BASE = ("load_z", "fe_z", "ramp3_z", "ic_z")
VERSION = "anomaly-exploratory-v1"


def build_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Trailing-only features, with all history reset at hourly gaps."""
    frame = frame.copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    frame = frame.sort_values("timestamp_utc").reset_index(drop=True)
    if frame["timestamp_utc"].duplicated().any():
        raise ValueError("Duplicate timestamps")
    for name in BASE:
        if name not in frame:
            raise ValueError(f"Missing {name}")
    # No rolling operation may bridge missing hours.
    contiguous = frame["timestamp_utc"].diff().eq(pd.Timedelta(hours=1))
    segment = (~contiguous).cumsum()
    pieces = []
    for _, part in frame.groupby(segment, sort=True):
        part = part.copy()
        x = part[list(BASE)]
        for name in BASE:
            for lag in (1, 3, 6):
                part[f"{name}_diff{lag}h"] = part[name].diff(lag)
            part[f"{name}_diff2_1h"] = part[name].diff().diff()
            for hours in (6, 12, 24):
                part[f"{name}_std{hours}h"] = part[name].rolling(hours, min_periods=hours).std()
        joint = pd.Series(np.linalg.norm(x.to_numpy(dtype=float), axis=1), index=part.index)
        # Missing inputs must never produce an apparently valid joint magnitude.
        joint.loc[x.isna().any(axis=1)] = np.nan
        part["joint_l2"] = joint
        for hours in (6, 12, 24):
            part[f"joint_mean{hours}h"] = joint.rolling(hours, min_periods=hours).mean()
            above = (joint > 4.0).astype(float).where(joint.notna())
            part[f"joint_above4_count{hours}h"] = above.rolling(hours, min_periods=hours).sum()
        for a,b in combinations(BASE, 2):
            for hours in (12,24):
                part[f"corr_{a}_{b}_{hours}h"] = part[a].rolling(hours, min_periods=hours).corr(part[b])
        for a in ("load_z", "fe_z", "ramp3_z"):
            part[f"lagcorr_{a}_ic_z_24h"] = part[a].shift(1).rolling(24, min_periods=24).corr(part["ic_z"])
        pieces.append(part)
    return pd.concat(pieces, ignore_index=True)


def run() -> dict:
    catalog = pd.read_csv(ROOT / "metadata/events.csv")
    source_dir = ROOT / "data/processed/event_features"
    target_dir = ROOT / "data/processed/anomaly_features_v1"
    target_dir.mkdir(parents=True, exist_ok=True)
    spec = ROOT / "research_spec_anomaly_v1.yaml"
    entries = []
    feature_names = None
    for event_id in catalog["event_id"]:
        source = source_dir / f"{event_id}.parquet"
        if not source.exists():
            raise FileNotFoundError(f"{source}: run materialize_event_features first")
        raw = pd.read_parquet(source)
        enriched = build_features(raw)
        names = [c for c in enriched if c not in raw.columns]
        if feature_names is None:
            feature_names = names
        elif feature_names != names:
            raise ValueError(f"{event_id}: feature schema mismatch")
        # Early event-window rows lack historical context by construction.
        complete = enriched[list(BASE)+names].replace([np.inf,-np.inf],np.nan).notna().all(axis=1)
        if not complete.any():
            raise ValueError(f"{event_id}: no complete feature vectors")
        if not np.isfinite(enriched.loc[complete,list(BASE)+names].to_numpy(dtype=float)).all():
            raise ValueError(f"{event_id}: nonfinite complete features")
        dest = target_dir / f"{event_id}.parquet"
        enriched.to_parquet(dest,index=False)
        entries.append({"event_id":event_id,"rows":len(enriched),
                        "complete_rows":int(complete.sum()),
                        "first_complete_utc":enriched.loc[complete,"timestamp_utc"].iloc[0].isoformat(),
                        "source_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),
                        "output_sha256":hashlib.sha256(dest.read_bytes()).hexdigest()})
        print(f"{event_id}: {int(complete.sum())}/{len(enriched)} complete anomaly vectors")
    manifest={"version":VERSION,"status":"exploratory_post_hoc",
              "spec_sha256":hashlib.sha256(spec.read_bytes()).hexdigest(),
              "feature_columns":list(BASE)+feature_names,
              "feature_count":len(BASE)+len(feature_names),
              "events":entries,
              "warning":"Event-window warmup is incomplete; no detector fitted or evaluated. "
                        "Raw hourly values may be published after their observation hour."}
    out=target_dir/"manifest.json"
    out.write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
    print(f"\n{manifest['feature_count']} features; {len(entries)} event windows; manifest: {out}")
    return manifest


if __name__=="__main__":
    run()
