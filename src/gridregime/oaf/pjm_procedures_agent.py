"""OAF adapter for archived PJM emergency-procedure records.

The upstream PJM Dataminer2 live fetcher is not yet implemented. This agent
accepts an explicitly supplied archived CSV and refuses to claim live
acquisition. It validates provenance, timestamps and the requested window,
then publishes a content-addressed evidence artifact.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
from pathlib import Path

import pandas as pd
from shared.agent.base import BaseAgent
from shared.eventbus.events import EventEnvelope

REQUESTED = "grid.pjm.procedures.requested"
FETCHED = "grid.pjm.procedures.fetched"
REQUIRED = ("timestamp_et", "procedure_type", "description")


def persist_pjm_procedures(
    *, start: str, end: str, source_path: str | Path,
    output_dir: str | Path, source_name: str,
) -> dict:
    """Validate a local archival extract; never infer an absence of emergencies.

    Input timestamps must include UTC offsets, including across DST transitions.
    An empty window is recorded as unknown, not proof of no PJM notices.
    """
    if not source_name or not source_name.strip():
        raise ValueError("An explicit source_name is required")
    source = Path(source_path)
    if not source.is_file():
        raise FileNotFoundError(source)
    raw = source.read_bytes()
    source_sha = hashlib.sha256(raw).hexdigest()
    frame = pd.read_csv(source)
    missing = set(REQUIRED).difference(frame.columns)
    if missing:
        raise ValueError(f"Missing PJM procedure fields: {sorted(missing)}")
    t0, t1 = pd.Timestamp(start), pd.Timestamp(end)
    if t0.tzinfo is None or t1.tzinfo is None or t1 < t0:
        raise ValueError("start/end require timezone offsets and ascending order")
    t0, t1 = t0.tz_convert("UTC"), t1.tz_convert("UTC")
    if frame.empty:
        selected = frame.copy()
    else:
        if frame[list(REQUIRED)].isna().any().any():
            raise ValueError("PJM procedure records contain nulls")
        # Reject offset-naive strings; localization cannot resolve DST folds.
        if any(pd.Timestamp(x).tzinfo is None for x in frame["timestamp_et"]):
            raise ValueError("PJM timestamps require explicit UTC offsets")
        times = pd.to_datetime(frame["timestamp_et"], utc=True, errors="raise")
        if times.duplicated().any() and frame.duplicated(subset=list(REQUIRED)).any():
            raise ValueError("Duplicate PJM procedure records")
        selected = frame.loc[(times >= t0) & (times <= t1)].copy()
        selected["timestamp_utc"] = times.loc[selected.index].map(lambda t: t.isoformat())
        selected = selected.sort_values(["timestamp_utc", "procedure_type", "description"])
    payload = selected.to_csv(index=False, lineterminator="\n").encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"pjm-procedures-{digest}.csv"
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError("PJM artifact checksum mismatch")
    else:
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(dir=output_dir, prefix=".pjm-", delete=False) as f:
                f.write(payload)
                tmp = Path(f.name)
            os.replace(tmp, target)
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
    return {
        "start_utc": t0.isoformat(), "end_utc": t1.isoformat(),
        "artifact_path": str(target), "sha256": digest,
        "source_path": str(source), "source_sha256": source_sha,
        "source_name": source_name.strip(), "record_count": len(selected),
        "acquisition_mode": "archived-local-file",
        "coverage_status": "unverified",
        "publication_time_verified": False,
        "no_emergency_claim": False,
    }


class PJMProceduresAcquisitionAgent(BaseAgent):
    def __init__(self, *, output_dir: str | Path, **kwargs):
        super().__init__(
            name="grid-pjm-procedures",
            subscribed_event_types={REQUESTED},
            completion_event_type=FETCHED, **kwargs,
        )
        self.output_dir = Path(output_dir)

    async def handle_event(self, event: EventEnvelope) -> list[EventEnvelope]:
        if event.event_type != REQUESTED or not isinstance(event.payload, dict):
            raise ValueError("Expected PJM procedures request")
        p = event.payload
        result = await asyncio.to_thread(
            persist_pjm_procedures,
            start=p["start"], end=p["end"],
            source_path=p["source_path"], source_name=p["source_name"],
            output_dir=self.output_dir,
        )
        return [EventEnvelope(
            event_type=FETCHED, source_agent=str(self.name),
            correlation_id=event.correlation_id, causation_id=event.event_id,
            payload=result,
        )]
