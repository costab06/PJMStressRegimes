"""Show real OpenAgentFabric event envelopes around the July 2026 EIA adapter.

This is an *in-process handler walkthrough*: no Redis, workers, retry or
recovery is exercised. It demonstrates the OAF BaseAgent contracts and
correlation/causation lineage using a local historical EIA parquet.
Run: python -m gridregime.oaf_demo (OpenAgentFabric must be installed).
"""
from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pandas as pd

from gridregime.demo import SOURCE, OUTPUT, validate
from gridregime.oaf.acquisition_coordinator import (
    AcquisitionCoordinatorAgent, CYCLE_REQUESTED, EIA_REQUESTED,
)
from gridregime.oaf.eia930_agent import EIA930AcquisitionAgent
from shared.eventbus.events import EventEnvelope


def local_fetch(ba: str, start: str, end: str) -> pd.DataFrame:
    """Replace the network fetcher with a pinned historical local snapshot."""
    if ba != "PJM":
        raise ValueError("Only PJM is supported by the example")
    raw = pd.read_parquet(SOURCE)
    data = validate(raw)
    begin, finish = pd.Timestamp(start), pd.Timestamp(end)
    begin = begin.tz_localize("UTC") if begin.tzinfo is None else begin.tz_convert("UTC")
    finish = finish.tz_localize("UTC") if finish.tzinfo is None else finish.tz_convert("UTC")
    selected = data.loc[data["timestamp_utc"].between(begin, finish)].copy()
    selected["ba"] = ba
    return selected


async def main() -> None:
    # The BaseAgent subclasses are real OAF adapters. Here we call only their
    # pure handlers, bypassing the Redis-backed runtime intentionally.
    coordinator = object.__new__(AcquisitionCoordinatorAgent)
    coordinator.name = "grid-acquisition-coordinator"
    acquirer = object.__new__(EIA930AcquisitionAgent)
    acquirer.name = "grid-eia930"
    acquirer.output_dir = OUTPUT / "oaf_artifacts"
    acquirer.fetcher = local_fetch

    request = EventEnvelope(
        event_type=CYCLE_REQUESTED,
        source_agent="architecture-demo",
        correlation_id=uuid4(),
        payload={
            "ba": "PJM",
            "as_of": "2026-07-03T00:00:00Z",
            "lookback_hours": 24,
            "publication_lag_hours": 0,
        },
    )
    dispatched = await coordinator.handle_event(request)
    acquisition = next(e for e in dispatched if e.event_type == EIA_REQUESTED)
    completed = (await acquirer.handle_event(acquisition))[0]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    trace = {
        "scope": "OAF handler walkthrough; NOT a Redis worker/recovery demonstration",
        "events": [
            {
                "type": event.event_type,
                "event_id": str(event.event_id),
                "correlation_id": str(event.correlation_id),
                "causation_id": str(event.causation_id) if event.causation_id else None,
            }
            for event in (request, acquisition, completed)
        ],
        "artifact_sha256": completed.payload["sha256"],
        "artifact_rows": completed.payload["row_count"],
        "publication_time_verified": False,
    }
    dest = OUTPUT / "oaf_event_trace.json"
    dest.write_text(json.dumps(trace, indent=2) + "\n")
    print(json.dumps(trace, indent=2))
    print(f"\nSaved {dest}")


if __name__ == "__main__":
    asyncio.run(main())
