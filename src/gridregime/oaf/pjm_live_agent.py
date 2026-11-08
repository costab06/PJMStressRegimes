"""Live PJM Emergency Procedures acquisition via gridstatus's public-data client.

PJM Emergency Procedures is distinct from the Data Miner 2 feed API.
The gridstatus adapter handles the PJM guest/XML retrieval protocol. This
module deliberately fails closed if the client, its output schema, or source
timestamps change. It never asserts that an empty response proves no alert.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd
from shared.agent.base import BaseAgent
from shared.eventbus.events import EventEnvelope

REQUESTED = "grid.pjm.live.requested"
FETCHED = "grid.pjm.live.fetched"


def gridstatus_fetch(start: str, end: str) -> pd.DataFrame:
    """Use documented gridstatus PJM.get_emergency_postings(date, end)."""
    try:
        import gridstatus
    except ImportError as exc:
        raise RuntimeError(
            "Install optional gridstatus package for live PJM acquisition"
        ) from exc
    return gridstatus.PJM().get_emergency_postings(
        date=pd.Timestamp(start), end=pd.Timestamp(end)
    )


def persist_live_pjm(
    *, start: str, end: str, output_dir: str | Path,
    fetcher: Callable = gridstatus_fetch,
    fetched_at: str | None = None,
) -> dict:
    t0, t1 = pd.Timestamp(start), pd.Timestamp(end)
    if t0.tzinfo is None or t1.tzinfo is None or t1 < t0:
        raise ValueError("Live PJM window requires offset-aware ordered times")
    t0, t1 = t0.tz_convert("UTC"), t1.tz_convert("UTC")
    checked = pd.Timestamp.now(tz="UTC") if fetched_at is None else pd.Timestamp(fetched_at)
    if checked.tzinfo is None:
        raise ValueError("fetched_at must be offset-aware")
    checked = checked.tz_convert("UTC")
    frame = fetcher(t0.isoformat(), t1.isoformat())
    if not isinstance(frame, pd.DataFrame):
        raise ValueError("PJM client must return a DataFrame")
    # Preserve the entire returned record schema rather than guessing which
    # columns are publish/cancel times across client versions.
    if len(set(frame.columns)) != len(frame.columns):
        raise ValueError("Duplicate PJM response columns")
    if frame.empty:
        raise ValueError(
            "Empty PJM response is ambiguous; cannot verify feed coverage"
        )
    if frame.isna().all(axis=1).any():
        raise ValueError("Blank PJM response records")
    canonical = frame.copy()
    for column in canonical.columns:
        canonical[column] = canonical[column].map(
            lambda x: x.isoformat() if isinstance(x, (datetime, pd.Timestamp))
            else x
        )
    canonical = canonical.astype(str).sort_values(list(canonical.columns))
    payload = canonical.to_csv(index=False, lineterminator="\n").encode()
    digest = hashlib.sha256(payload).hexdigest()
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"pjm-live-{digest}.csv"
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError("PJM artifact checksum mismatch")
    else:
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(dir=out, prefix=".pjm-live-", delete=False) as f:
                f.write(payload)
                tmp = Path(f.name)
            os.replace(tmp, target)
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
    return {
        "start_utc": t0.isoformat(), "end_utc": t1.isoformat(),
        "fetched_at_utc": checked.isoformat(), "sha256": digest,
        "artifact_path": str(target), "record_count": len(frame),
        "source": "pjm-emergency-procedures-via-gridstatus",
        "coverage_status": "unverified",
        "publication_time_verified": False,
        "no_emergency_claim": False,
    }


class PJMLiveAcquisitionAgent(BaseAgent):
    def __init__(self, *, output_dir: str | Path,
                 fetcher: Callable = gridstatus_fetch, **kwargs):
        super().__init__(
            name="grid-pjm-live", subscribed_event_types={REQUESTED},
            completion_event_type=FETCHED, **kwargs,
        )
        self.output_dir = Path(output_dir)
        self.fetcher = fetcher

    async def handle_event(self, event: EventEnvelope) -> list[EventEnvelope]:
        if event.event_type != REQUESTED or not isinstance(event.payload, dict):
            raise ValueError("Expected PJM live request")
        p = event.payload
        result = await asyncio.to_thread(
            persist_live_pjm, start=p["start"], end=p["end"],
            output_dir=self.output_dir, fetcher=self.fetcher,
        )
        return [EventEnvelope(
            event_type=FETCHED, source_agent=str(self.name),
            correlation_id=event.correlation_id, causation_id=event.event_id,
            payload=result,
        )]
