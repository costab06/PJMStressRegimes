"""Durable hourly cycle submission using OAF correlation and Redis Streams.

Call submit_cycle from an external recurring scheduler (cron, systemd, etc).
The Lua transaction atomically deduplicates and publishes the initial OAF
event, preventing duplicate cycles after process restart or network retry.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid5, NAMESPACE_URL

from shared.correlation.registry import CorrelationRegistry
from shared.eventbus.events import EventEnvelope

from gridregime.oaf.acquisition_coordinator import (
    CYCLE_REQUESTED, plan_acquisition_cycle,
)

# Keep keys for audit; pruning must be a deliberate retention policy.
PUBLISH_SCRIPT = """
local key = KEYS[1]
local stream = KEYS[2]
local event_id = ARGV[1]
local encoded = ARGV[2]
local old = redis.call('GET', key)
if old then
    if old ~= event_id then
        return redis.error_reply('CYCLE_IDENTITY_CONFLICT')
    end
    return {0, old}
end
redis.call('XADD', stream, '*', 'event', encoded)
redis.call('SET', key, event_id)
return {1, event_id}
"""


async def submit_cycle(
    *, redis, correlation_registry: CorrelationRegistry,
    ba: str, as_of: str, lookback_hours: int = 24,
    publication_lag_hours: int = 2, require_pjm: bool = False,
    stream: str = "oaf.events",
) -> dict:
    """Submit once per exact cycle configuration; returns whether newly queued.

    The correlation registry must live long enough for the full workflow.
    A scheduler must handle backfill and monitoring independently.
    """
    plan = plan_acquisition_cycle(
        ba=ba, as_of=as_of, lookback_hours=lookback_hours,
        publication_lag_hours=publication_lag_hours, require_pjm=require_pjm,
    )
    instant = datetime.fromisoformat(plan["as_of"])
    fields = {k: plan[k] for k in ("ba", "lookback_hours", "publication_lag_hours", "require_pjm")}
    correlation = await correlation_registry.create(
        trigger_type=CYCLE_REQUESTED,
        trigger_timestamp=instant,
        business_fields=fields,
    )
    event_id = uuid5(NAMESPACE_URL, f"pjm-cycle:{correlation.correlation_id}")
    event = EventEnvelope(
        event_id=event_id, event_type=CYCLE_REQUESTED,
        source_agent="grid-cycle-scheduler",
        correlation_id=correlation.correlation_id,
        payload={"ba": plan["ba"], "as_of": plan["as_of"],
                 "lookback_hours": lookback_hours,
                 "publication_lag_hours": publication_lag_hours,
                 "require_pjm": require_pjm},
    )
    key = f"grid:cycle:published:{correlation.correlation_id}"
    result = await redis.eval(
        PUBLISH_SCRIPT, 2, key, stream, str(event_id),
        event.model_dump_json(),
    )
    return {
        "published": bool(int(result[0])),
        "event_id": str(event_id),
        "correlation_id": str(correlation.correlation_id),
        "plan": plan,
    }
