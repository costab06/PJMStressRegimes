"""Acquisition cycle planning and OAF event dispatch.

A scheduler or operator publishes grid.acquisition.cycle.requested. This
coordinator validates an explicit completed UTC window and atomically emits
EIA acquisition work through OAF. It does not itself run a clock or imply
that missing upstream data is fresh.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd
from shared.agent.base import BaseAgent
from shared.eventbus.events import EventEnvelope

CYCLE_REQUESTED = "grid.acquisition.cycle.requested"
CYCLE_DISPATCHED = "grid.acquisition.cycle.dispatched"
EIA_REQUESTED = "grid.eia930.requested"
PJM_LIVE_REQUESTED = "grid.pjm.live.requested"


def plan_acquisition_cycle(
    *, ba: str, as_of: str, lookback_hours: int = 24,
    publication_lag_hours: int = 2, require_pjm: bool = False,
) -> dict[str, Any]:
    """Produce a deterministic, inclusive hourly window ending before as_of.

    The lag is a configurable operational assumption, NOT evidence of actual
    EIA publication freshness. Data completeness is checked by the EIA agent.
    """
    if not isinstance(require_pjm, bool):
        raise ValueError("require_pjm must be boolean")
    if not isinstance(ba, str) or not ba.strip():
        raise ValueError("A balancing authority is required")
    if not isinstance(lookback_hours, int) or isinstance(lookback_hours, bool) or not 4 <= lookback_hours <= 168:
        raise ValueError("lookback_hours must be an integer in [4, 168]")
    if not isinstance(publication_lag_hours, int) or isinstance(publication_lag_hours, bool) or not 0 <= publication_lag_hours <= 72:
        raise ValueError("publication_lag_hours must be an integer in [0, 72]")
    ts = pd.Timestamp(as_of)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    if ts != ts.floor("h"):
        raise ValueError("as_of must be an exact UTC hour")
    end = ts - pd.Timedelta(hours=publication_lag_hours)
    start = end - pd.Timedelta(hours=lookback_hours - 1)
    return {
        "ba": ba.strip(), "as_of": ts.isoformat(),
        "start": start.strftime("%Y-%m-%dT%H"),
        "end": end.strftime("%Y-%m-%dT%H"),
        "lookback_hours": lookback_hours,
        "publication_lag_hours": publication_lag_hours,
        "freshness_status": "unverified-pending-acquisition",
        "require_pjm": require_pjm,
    }


class AcquisitionCoordinatorAgent(BaseAgent):
    """OAF-backed durable dispatch of acquisition work.

    BaseAgent handles retry, recovery and atomic downstream event publication.
    A separate scheduler must submit the initial cycle request and register
    its correlation with OAF.
    """

    def __init__(self, **kwargs):
        super().__init__(
            name="grid-acquisition-coordinator",
            subscribed_event_types={CYCLE_REQUESTED},
            completion_event_type=CYCLE_DISPATCHED,
            **kwargs,
        )

    async def handle_event(self, event: EventEnvelope) -> list[EventEnvelope]:
        if event.event_type != CYCLE_REQUESTED or not isinstance(event.payload, dict):
            raise ValueError("Expected acquisition cycle request")
        plan = plan_acquisition_cycle(**event.payload)
        common = dict(source_agent=str(self.name),
                      correlation_id=event.correlation_id,
                      causation_id=event.event_id)
        events = [
            EventEnvelope(
                event_type=EIA_REQUESTED,
                payload={key: plan[key] for key in ("ba", "start", "end")},
                **common,
            ),
        ]
        if plan["require_pjm"]:
            events.append(EventEnvelope(
                event_type=PJM_LIVE_REQUESTED,
                payload={
                    "start": plan["start"] + ":00:00+00:00",
                    "end": plan["end"] + ":00:00+00:00",
                },
                **common,
            ))
        events.append(EventEnvelope(
            event_type=CYCLE_DISPATCHED, payload=plan, **common,
        ))
        return events
