"""Conservative, event-driven acquisition cycle status aggregation.

The aggregator consumes dispatch, EIA quality, and PJM completion events.
A cycle is complete only when *all* required sources report acceptable
evidence. Unknown or stale data never silently becomes a successful cycle.

Status is an OAF event; no in-memory cross-message state is trusted.
"""
from __future__ import annotations

import json

from shared.agent.base import BaseAgent
from shared.eventbus.events import EventEnvelope

DISPATCHED = "grid.acquisition.cycle.dispatched"
EIA_ASSESSED = "grid.acquisition.quality.assessed"
PJM_FETCHED = "grid.pjm.procedures.fetched"\nPJM_LIVE_FETCHED = "grid.pjm.live.fetched"
STATUS_CHANGED = "grid.acquisition.cycle.status"


def evaluate_cycle(*, dispatch: dict | None, eia: dict | None,
                   pjm: dict | None, require_pjm: bool = False) -> dict:
    """Pure policy: report incomplete until all required evidence is present."""
    required = ["eia930"] + (["pjm_procedures"] if require_pjm else [])
    sources = {
        "eia930": "missing" if eia is None else eia.get("status", "unknown"),
        "pjm_procedures": "not-required" if not require_pjm else (
            "missing" if pjm is None else pjm.get("coverage_status", "unknown")
        ),
    }
    eia_ok = sources["eia930"] == "observations-current-publication-unverified"
    # PJM archived-file coverage is always unverified, so cannot satisfy a
    # required live source. A verified live adapter can later report verified.
    pjm_ok = not require_pjm or sources["pjm_procedures"] == "verified"
    if dispatch is None:
        status = "pending-dispatch"
    elif eia_ok and pjm_ok:
        status = "observation-ready-publication-unverified"
    elif any(x in ("stale", "invalid-future-observation", "incomplete-window")
             for x in sources.values()):
        status = "degraded"
    else:
        status = "pending-evidence"
    return {
        "status": status, "sources": sources, "required_sources": required,
        "publication_time_verified": False,
        "ready_for_predictive_inference": False,
    }


class AcquisitionCycleStatusAgent(BaseAgent):
    """Use Redis as durable aggregation state, not process-local dictionaries.

    State keys are keyed by OAF correlation ID. A Lua script performs a
    single-event update atomically, so replay cannot remove other evidence.
    This status event is a snapshot, not an exactly-once transition feed.
    """

    def __init__(self, **kwargs):
        super().__init__(
            name="grid-acquisition-status",
            subscribed_event_types={DISPATCHED, EIA_ASSESSED, PJM_FETCHED, PJM_LIVE_FETCHED},
            **kwargs,
        )

    async def handle_event(self, event: EventEnvelope) -> list[EventEnvelope]:
        if not isinstance(event.payload, dict):
            raise ValueError("Expected acquisition evidence")
        field = {
            DISPATCHED: "dispatch",
            EIA_ASSESSED: "eia",
            PJM_FETCHED: "pjm",\n            PJM_LIVE_FETCHED: "pjm",
        }.get(event.event_type)
        if field is None:
            raise ValueError("Unsupported evidence event")
        key = f"grid:cycle:evidence:{event.correlation_id}"
        # Avoid lost updates when several agents finish simultaneously.
        script = """
        redis.call('HSET', KEYS[1], ARGV[1], ARGV[2])
        return redis.call('HGETALL', KEYS[1])
        """
        raw = await self.event_bus.redis.eval(
            script, 1, key, field, json.dumps(event.payload, sort_keys=True),
        )
        decoded = {
            (k.decode() if isinstance(k, bytes) else k):
            json.loads(v.decode() if isinstance(v, bytes) else v)
            for k, v in zip(raw[::2], raw[1::2])
        }
        result = evaluate_cycle(
            dispatch=decoded.get("dispatch"),
            eia=decoded.get("eia"),
            pjm=decoded.get("pjm"),
            require_pjm=bool(decoded.get("dispatch", {}).get("require_pjm", False)),
        )
        return [EventEnvelope(
            event_type=STATUS_CHANGED,
            source_agent=str(self.name),
            correlation_id=event.correlation_id,
            causation_id=event.event_id,
            payload=result,
        )]
