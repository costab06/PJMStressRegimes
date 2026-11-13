"""Generate descriptive frozen-v1 features from validated event Parquets.

Run: python -m gridregime.pipeline.materialize_event_features
Does not make predictive or point-in-time availability claims.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from gridregime.features.seasonal import apply_zscore

ROOT = Path(__file__).resolve().parents[3]
FEATURES = ("load_z", "fe_z", "ramp3_z", "ic_z")
REQUIRED = ("timestamp_utc", "demand_mwh", "forecast_mwh", "interchange_mwh")


def run() -> dict:
    base_path = ROOT / "data/processed/baseline_2021_frozen_v1.parquet"
    prov_path = ROOT / "data/processed/baseline_2021_provenance.json"
    if not prov_path.is_file():
        raise FileNotFoundError("Run python -m gridregime.pipeline.freeze_reference_2021 first")
    prov = json.loads(prov_path.read_text())
    baseline_hash = hashlib.sha256(base_path.read_bytes()).hexdigest()
    if prov["baseline_sha256"] != baseline_hash:
        raise ValueError("Candidate baseline checksum differs from provenance")
    baseline = pd.read_parquet(base_path)
    events = pd.read_csv(ROOT / "metadata/events.csv")
    output = ROOT / "data/processed/event_features"
    output.mkdir(parents=True, exist_ok=True)
    summary = []
    for event_id in events["event_id"]:
        source = ROOT / "data/interim/eia930" / f"{event_id}.parquet"
        df = pd.read_parquet(source)
        if any(col not in df for col in REQUIRED):
            raise ValueError(f"{event_id}: missing required series")
        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
        df = df.sort_values("timestamp_utc").reset_index(drop=True)
        if df["timestamp_utc"].duplicated().any():
            raise ValueError(f"{event_id}: duplicate hours")
        if not df["timestamp_utc"].diff().iloc[1:].eq(pd.Timedelta(hours=1)).all():
            raise ValueError(f"{event_id}: non-contiguous hours")
        if df[list(REQUIRED[1:])].isna().any().any() or df["forecast_mwh"].le(0).any():
            raise ValueError(f"{event_id}: invalid required observations")
        # 't' is required by apply_zscore for ramp continuity. UTC hours
        # are used, not hours_to_event (which can have fractional offsets).
        df["t"] = (df["timestamp_utc"] - df["timestamp_utc"].iloc[0]).dt.total_seconds() / 3600
        scored = apply_zscore(df, baseline)
        # Three-hour ramp is undefined for the first three observations.
        if scored.loc[3:, list(FEATURES)].isna().any().any():
            raise ValueError(f"{event_id}: missing seasonal feature cells")
        values = scored.loc[3:, list(FEATURES)].to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise ValueError(f"{event_id}: non-finite frozen-v1 features")
        target = output / f"{event_id}.parquet"
        scored.to_parquet(target, index=False)
        summary.append({
            "event_id": event_id, "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "baseline_sha256": baseline_hash, "hours": len(scored),
            "complete_feature_hours": len(scored) - 3,
            "output": str(target.relative_to(ROOT)),
        })
        print(f"{event_id}: {len(scored) - 3}/{len(scored)} complete feature hours")
    manifest = {
        "schema_version": 1, "feature_version": "frozen-v1",
        "purpose": "descriptive research; not point-in-time predictive inference",
        "baseline_sha256": baseline_hash, "events": summary,
    }
    path = ROOT / "data/processed/event_features_manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"Manifest: {path} ({len(summary)} event windows)")
    return manifest


if __name__ == "__main__":
    run()
