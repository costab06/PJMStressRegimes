"""Point-in-time OAF feature adapter for the frozen four-variable research vector.

Only observations at or before as_of are accepted. The baseline is an immutable
input supplied by the caller; this agent never trains or updates it.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from shared.agent.base import BaseAgent
from shared.eventbus.events import EventEnvelope

from gridregime.features.seasonal import apply_zscore

REQUESTED = "grid.features.requested"
COMPUTED = "grid.features.computed"
FEATURES = ("load_z", "fe_z", "ramp3_z", "ic_z")
REQUIRED = ("timestamp_utc", "ba", "demand_mwh", "forecast_mwh", "interchange_mwh")


def compute_point_in_time_features(
    *, source_path: str | Path, baseline_path: str | Path,
    as_of: str, ba: str, output_dir: str | Path,
    decision_as_of: str | None = None,
) -> dict:
    """Compute features without observing anything after the decision timestamp.

    Require four contiguous hours so the 3-hour ramp is defined. Fail closed
    on incomplete inputs or unavailable baseline cells; never impute data.
    """
    asof = pd.Timestamp(as_of)
    asof = asof.tz_localize("UTC") if asof.tzinfo is None else asof.tz_convert("UTC")
    if asof != asof.floor("h"):
        raise ValueError("as_of must be a whole UTC hour")
    decision = asof if decision_as_of is None else pd.Timestamp(decision_as_of)
    decision = decision.tz_localize("UTC") if decision.tzinfo is None else decision.tz_convert("UTC")
    if decision != decision.floor("h") or decision < asof:
        raise ValueError("decision_as_of must be a whole UTC hour not before observation as_of")
    source_path, baseline_path = Path(source_path), Path(baseline_path)
    raw_bytes, baseline_bytes = source_path.read_bytes(), baseline_path.read_bytes()
    frame = pd.read_csv(source_path)
    if frame.empty or any(c not in frame for c in REQUIRED):
        raise ValueError("Missing required EIA-930 observations")
    if frame[list(REQUIRED)].isna().any().any() or not frame["ba"].eq(ba).all():
        raise ValueError("Null or incorrect balancing-authority observations")
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    if frame["timestamp_utc"].duplicated().any():
        raise ValueError("Duplicate observation timestamps")
    if (frame["timestamp_utc"] > asof).any():
        raise ValueError("Future observations would leak into prediction")
    frame = frame.sort_values("timestamp_utc").reset_index(drop=True)
    expected = pd.date_range(asof - pd.Timedelta(hours=3), asof, freq="h")
    if not pd.DatetimeIndex(frame["timestamp_utc"].tail(4)).equals(expected):
        raise ValueError("Missing contiguous four-hour feature window")
    if frame["forecast_mwh"].le(0).any():
        raise ValueError("Forecast must be positive")
    baseline = pd.read_parquet(baseline_path)
    frame["t"] = (frame["timestamp_utc"] - asof).dt.total_seconds() / 3600
    scored = apply_zscore(frame, baseline)
    latest = scored.iloc[-1]
    values = {key: float(latest[key]) for key in FEATURES}
    if not all(np.isfinite(v) for v in values.values()):
        raise ValueError("Feature computation produced non-finite values")
    report = {
        "as_of": asof.isoformat(), "decision_as_of": decision.isoformat(),
        "ba": ba, "feature_version": "frozen-v1",
        "features": values, "source_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "baseline_sha256": hashlib.sha256(baseline_bytes).hexdigest(),
        "status": "features-only-not-a-risk-prediction",
    }
    encoded = (json.dumps(report, sort_keys=True, allow_nan=False) + "\n").encode()
    digest = hashlib.sha256(encoded).hexdigest()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"features-{digest}.json"
    if target.exists():
        if target.read_bytes() != encoded:
            raise ValueError("Existing feature artifact checksum mismatch")
    else:
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=output_dir, delete=False) as f:
                f.write(encoded)
                tmp = Path(f.name)
            os.replace(tmp, target)
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
    return {**report, "artifact_path": str(target), "sha256": digest}


class PointInTimeFeatureAgent(BaseAgent):
    """Durable OAF event wrapper around the existing scientific calculations."""

    def __init__(self, *, output_dir: str | Path, baseline_path: str | Path, **kwargs):
        super().__init__(
            name="grid-features", subscribed_event_types={REQUESTED},
            completion_event_type=COMPUTED, **kwargs,
        )
        self.output_dir = Path(output_dir)
        self.baseline_path = Path(baseline_path)

    async def handle_event(self, event: EventEnvelope) -> list[EventEnvelope]:
        if event.event_type != REQUESTED or not isinstance(event.payload, dict):
            raise ValueError("Unexpected feature request")
        p = event.payload
        if "baseline_sha256" not in p or "source_sha256" not in p:
            raise ValueError("Feature request requires pinned source and baseline hashes")
        if "baseline_path" in p and Path(p["baseline_path"]).resolve() != self.baseline_path.resolve():
            raise ValueError("Feature request baseline path differs from worker configuration")
        if "baseline_sha256" in p:
            actual_baseline_hash = hashlib.sha256(self.baseline_path.read_bytes()).hexdigest()
            if actual_baseline_hash != p["baseline_sha256"]:
                raise ValueError("Frozen baseline checksum mismatch")
        if "source_sha256" in p:
            actual_source_hash = hashlib.sha256(Path(p["artifact_path"]).read_bytes()).hexdigest()
            if actual_source_hash != p["source_sha256"]:
                raise ValueError("Source artifact checksum mismatch")
        result = await asyncio.to_thread(
            compute_point_in_time_features,
            source_path=p["artifact_path"], baseline_path=self.baseline_path,
            as_of=p["as_of"], decision_as_of=p.get("decision_as_of"),
            ba=p["ba"], output_dir=self.output_dir,
        )
        return [EventEnvelope(
            event_type=COMPUTED, source_agent=str(self.name),
            correlation_id=event.correlation_id, causation_id=event.event_id,
            payload=result,
        )]
