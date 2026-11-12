"""OAF orchestration bridge from acquisition evidence to frozen-v1 features.

The bridge is intentionally *not* a risk inference agent. It requires an
observation-ready acquisition status, checks source hashes and produces a
deterministic feature-request event. Redis holds correlation-scoped evidence;
OAF owns durable event publication and retries.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from shared.agent.base import BaseAgent
from shared.eventbus.events import EventEnvelope

from gridregime.oaf.acquisition_status import (
    DISPATCHED, STATUS_CHANGED,
)
from gridregime.oaf.eia930_agent import FETCHED as EIA_FETCHED
from gridregime.oaf.feature_agent import REQUESTED as FEATURES_REQUESTED
from gridregime.oaf.feature_request_planner import plan_feature_request

INPUT_FIELDS = {
    DISPATCHED: "dispatch",
    EIA_FETCHED: "eia_fetched",
    STATUS_CHANGED: "status",
}

# An atomic snapshot of the evidence after each event update. A deterministic
# event ID makes repeat proposals identifiable to downstream OAF processing.
UPDATE_AND_READ = """
local old = redis.call('HGET', KEYS[1], ARGV[1])
if old and old ~= ARGV[2] then
    return redis.error_reply('CONFLICTING_CYCLE_EVIDENCE')
end
redis.call('HSET', KEYS[1], ARGV[1], ARGV[2])
return redis.call('HGETALL', KEYS[1])
"""


class AcquisitionFeatureBridgeAgent(BaseAgent):
    """Emit a feature request once the cycle has sufficient observation evidence.

    The request's as_of is the observation endpoint; decision_as_of is the
    actual decision time. Neither proves upstream source publication timing.
    """

    def __init__(self, *, baseline_path: str | Path, **kwargs):
        super().__init__(
            name="grid-acquisition-feature-bridge",
            subscribed_event_types=set(INPUT_FIELDS),
            **kwargs,
        )
        self.baseline_path = Path(baseline_path)

    async def handle_event(self, event: EventEnvelope) -> list[EventEnvelope]:
        field = INPUT_FIELDS.get(event.event_type)
        if field is None or not isinstance(event.payload, dict):
            raise ValueError("Expected acquisition evidence event")
        key = f"grid:cycle:feature-bridge:{event.correlation_id}"
        raw = await self.event_bus.redis.eval(
            UPDATE_AND_READ, 1, key, field,
            json.dumps(event.payload, sort_keys=True),
        )
        decoded = {
            (k.decode() if isinstance(k, bytes) else k):
            json.loads(v.decode() if isinstance(v, bytes) else v)
            for k, v in zip(raw[::2], raw[1::2])
        }
        if not all(k in decoded for k in ("dispatch", "eia_fetched", "status")):
            return []
        status = decoded["status"]
        if status.get("status") != "observation-ready-publication-unverified":
            return []
        plan = await asyncio.to_thread(
            plan_feature_request,
            dispatch=decoded["dispatch"],
            eia_fetched=decoded["eia_fetched"],
            acquisition_status=status,
            baseline_path=self.baseline_path,
        )
        # OAF may redeliver an input event. Stable IDs make the resulting
        # feature request reproducible and identifiable across replay.
        event_id = uuid5(
            NAMESPACE_URL,
            f"grid-feature-request:{event.correlation_id}:{plan['source_sha256']}:{plan['baseline_sha256']}",
        )
        return [EventEnvelope(
            event_id=event_id,
            event_type=FEATURES_REQUESTED,
            source_agent=str(self.name),
            correlation_id=event.correlation_id,
            causation_id=event.event_id,
            payload=plan,
        )]
