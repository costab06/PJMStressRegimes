"""OpenAgentFabric adapter for existing EIA-930 acquisition.

Requires OpenAgentFabric's `framework` directory on PYTHONPATH (or installed).
The scientific ingestion implementation remains in gridregime.ingest.eia930.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Callable

import pandas as pd
from shared.agent.base import BaseAgent
from shared.eventbus.events import EventEnvelope

from gridregime.ingest.eia930 import fetch_window
from gridregime.oaf.eia_revision_ledger import record_snapshot

REQUESTED = "grid.eia930.requested"
FETCHED = "grid.eia930.fetched"
REQUIRED = ("timestamp_utc", "ba", "demand_mwh", "forecast_mwh", "interchange_mwh")


def persist_eia_window(
    *,
    ba: str,
    start: str,
    end: str,
    output_dir: Path,
    fetcher: Callable = fetch_window,
) -> dict:
    """Run the existing fetcher and publish a validated, content-addressed artifact.

    An identical canonical CSV produces the same path. A temporary file is
    atomically replaced, avoiding partially visible published artifacts.
    """
    if not ba or not start or not end:
        raise ValueError("ba, start and end are required")
    frame = fetcher(ba, start, end)
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError("EIA-930 fetch returned no rows")
    missing = [column for column in REQUIRED if column not in frame.columns]
    if missing:
        raise ValueError(f"EIA-930 missing required columns: {missing}")
    if frame[list(REQUIRED)].isna().any().any():
        raise ValueError("EIA-930 required columns contain nulls")
    if not frame["ba"].eq(ba).all():
        raise ValueError("EIA-930 result contains an unexpected balancing authority")
    timestamps = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="raise")
    if timestamps.duplicated().any():
        raise ValueError("EIA-930 result contains duplicate UTC timestamps")
    # The EIA fetcher can warn and continue after an upstream series failure.
    # Do not mistake a partially retrieved hourly window for a complete one.
    t0 = pd.Timestamp(start)
    t1 = pd.Timestamp(end)
    t0 = t0.tz_localize("UTC") if t0.tzinfo is None else t0.tz_convert("UTC")
    t1 = t1.tz_localize("UTC") if t1.tzinfo is None else t1.tz_convert("UTC")
    if t1 < t0 or t0 != t0.floor("h") or t1 != t1.floor("h"):
        raise ValueError("EIA-930 requires an ordered, whole-hour UTC window")
    expected = pd.date_range(t0, t1, freq="h")
    actual = pd.DatetimeIndex(timestamps).sort_values()
    if not actual.equals(expected):
        missing_hours = expected.difference(actual)
        unexpected_hours = actual.difference(expected)
        raise ValueError(
            "EIA-930 hourly coverage mismatch: "
            f"{len(missing_hours)} missing, {len(unexpected_hours)} unexpected hours"
        )
    frame = frame.assign(timestamp_utc=timestamps).sort_values("timestamp_utc")
    data = frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"eia930-{digest}.csv"
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError("Existing content-addressed artifact has incorrect checksum")
    else:
        import tempfile
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=output_dir, prefix=".eia930-", delete=False
            ) as temp:
                temp.write(data)
                temp_path = Path(temp.name)
            os.replace(temp_path, target)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
    # Deterministic provenance sidecar: the observation snapshot is identifiable,
    # but EIA publication and revision timestamps have not been established.
    # Never equate retrieval or observation time with source availability.
    provenance = {
        "schema_version": 1,
        "source": "eia930",
        "ba": ba,
        "window_start_utc": t0.isoformat(),
        "window_end_utc": t1.isoformat(),
        "artifact_sha256": digest,
        "row_count": len(frame),
        "publication_time_verified": False,
        "revision_history_verified": False,
    }
    sidecar = output_dir / f"eia930-{digest}.provenance.json"
    encoded = (json.dumps(provenance, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if sidecar.exists():
        if sidecar.read_bytes() != encoded:
            raise ValueError("Existing EIA provenance sidecar differs from snapshot")
    else:
        import tempfile
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=output_dir,
                                             prefix=".eia930-provenance-", delete=False) as temp:
                temp.write(encoded)
                temp_path = Path(temp.name)
            os.replace(temp_path, sidecar)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
    revision = record_snapshot(
        ledger_dir=output_dir / "revisions", ba=ba,
        start=t0.isoformat(), end=t1.isoformat(), sha256=digest,
        observed_at=pd.Timestamp.now(tz="UTC").isoformat(),
    )
    return {
        "revision_record": revision,
        "provenance_path": str(sidecar),
        "publication_time_verified": False,
        "revision_history_verified": False,
        "ba": ba,
        "start": start,
        "end": end,
        "artifact_path": str(target),
        "sha256": digest,
        "row_count": len(frame),
    }


class EIA930AcquisitionAgent(BaseAgent):
    """OAF event adapter; delegates all EIA logic to the existing fetcher."""

    def __init__(
        self, *, output_dir: str | Path, fetcher: Callable = fetch_window, **kwargs
    ):
        super().__init__(
            name="grid-eia930",
            subscribed_event_types={REQUESTED},
            completion_event_type=FETCHED,
            **kwargs,
        )
        self.output_dir = Path(output_dir)
        self.fetcher = fetcher

    async def handle_event(self, event: EventEnvelope) -> list[EventEnvelope]:
        if event.event_type != REQUESTED:
            raise ValueError(f"Unexpected event type: {event.event_type}")
        payload = event.payload
        if not isinstance(payload, dict):
            raise ValueError("Expected dict payload")
        result = await asyncio.to_thread(
            persist_eia_window,
            ba=payload["ba"],
            start=payload["start"],
            end=payload["end"],
            output_dir=self.output_dir,
            fetcher=self.fetcher,
        )
        return [
            EventEnvelope(
                event_type=FETCHED,
                source_agent=str(self.name),
                correlation_id=event.correlation_id,
                causation_id=event.event_id,
                payload=result,
            )
        ]
