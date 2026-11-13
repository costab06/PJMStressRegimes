"""Real Redis/OAF pending-message recovery test.

A consumer claims a message and exits without ACK. A replacement agent
reclaims that pending message and atomically commits its downstream event.
"""
import asyncio
import os
from uuid import uuid4

import pytest

from shared.agent.base import BaseAgent
from shared.correlation.registry import CorrelationRegistry
from shared.eventbus.events import EventEnvelope
from shared.eventbus.redis import RedisEventBus


class RecoveryProbe(BaseAgent):
    def __init__(self, *, event_bus, correlation_registry, stream):
        super().__init__(
            name=f"grid-recovery-probe-{stream}",
            event_bus=event_bus,
            correlation_registry=correlation_registry,
            subscribed_event_types={"grid.test.recovery.requested"},
            stream=stream,
            min_idle_ms=0,
        )

    async def handle_event(self, event):
        return [EventEnvelope(
            event_type="grid.test.recovery.completed",
            source_agent=str(self.name),
            correlation_id=event.correlation_id,
            causation_id=event.event_id,
            payload={"recovered": True},
        )]


@pytest.mark.asyncio
async def test_abandoned_pending_event_is_recovered_and_committed():
    url = os.environ.get("OAF_TEST_REDIS_URL")
    if not url:
        pytest.skip("Redis integration URL is not configured")
    bus = RedisEventBus(redis_url=url)
    stream = f"grid.test.recovery.{uuid4().hex}"
    registry = CorrelationRegistry(bus.redis)
    probe = RecoveryProbe(event_bus=bus, correlation_registry=registry, stream=stream)
    cid = uuid4()
    try:
        # The registry must contain a live correlation for OAF's fail-closed
        # processing contract. Reuse the same public API as the scheduler.
        from gridregime.oaf.cycle_scheduler import submit_cycle
        result = await submit_cycle(
            redis=bus.redis, correlation_registry=registry,
            ba="PJM", as_of="2022-12-20T06:00Z",
            lookback_hours=4, publication_lag_hours=2,
        )
        # Use the scheduler's registered correlation; do not create an
        # unregistered synthetic correlation.
        from uuid import UUID
        cid = UUID(str(result["correlation_id"]))
        event = EventEnvelope(
            event_type="grid.test.recovery.requested",
            source_agent="test", correlation_id=cid,
            payload={"probe": True},
        )
        await bus._ensure_group(stream, probe.group)
        message_id = await bus.publish(stream, event)
        claimed = await bus.redis.xreadgroup(
            groupname=probe.group, consumername="crashed-worker",
            streams={stream: ">"}, count=1,
        )
        assert claimed and claimed[0][1][0][0] == message_id

        # Replacement worker starts with a different consumer identity and
        # processes the pending record through OAF's recovery implementation.
        probe._running = True
        try:
            await probe._recover_pending_once()
        finally:
            probe.stop()
        terminal = await bus.get_terminal_state(stream, probe.group, event.event_id)
        assert terminal == 'committed'
        records = await bus.redis.xrange(stream)
        completed = [EventEnvelope.model_validate_json(fields['event'])
                     for _, fields in records
                     if EventEnvelope.model_validate_json(fields['event']).event_type
                     == 'grid.test.recovery.completed']
        assert len(completed) == 1
        assert completed[0].correlation_id == cid
        assert await bus.redis.xpending_range(stream, probe.group, '-', '+', 10) == []
    finally:
        await bus.redis.delete(stream)
        await bus.redis.aclose()



@pytest.mark.asyncio
async def test_restarted_worker_recovers_pending_event_without_duplicate_publication():
    """Exercise BaseAgent.run rather than invoking the recovery helper directly."""
    url = os.environ.get("OAF_TEST_REDIS_URL")
    if not url:
        pytest.skip("Redis integration URL is not configured")
    from uuid import UUID
    from gridregime.oaf.cycle_scheduler import submit_cycle

    bus = RedisEventBus(redis_url=url)
    stream = f"grid.test.restart.{uuid4().hex}"
    registry = CorrelationRegistry(bus.redis)
    first = RecoveryProbe(event_bus=bus, correlation_registry=registry, stream=stream)
    restarted = RecoveryProbe(event_bus=bus, correlation_registry=registry, stream=stream)
    task = None
    try:
        result = await submit_cycle(
            redis=bus.redis, correlation_registry=registry,
            ba="PJM", as_of="2022-12-20T07:00Z",
            lookback_hours=4, publication_lag_hours=2,
        )
        cid = UUID(str(result["correlation_id"]))
        event = EventEnvelope(
            event_type="grid.test.recovery.requested",
            source_agent="test", correlation_id=cid,
            payload={"probe": "restart"},
        )
        await bus._ensure_group(stream, first.group)
        message_id = await bus.publish(stream, event)
        claimed = await bus.redis.xreadgroup(
            groupname=first.group, consumername=first.consumer,
            streams={stream: ">"}, count=1,
        )
        assert claimed and str(claimed[0][1][0][0]) == message_id

        # The original consumer is gone; run the replacement's normal
        # lifecycle and allow its startup recovery to reclaim the message.
        task = asyncio.create_task(restarted.run())
        async def wait_for_commit():
            for _ in range(100):
                if await bus.get_terminal_state(stream, restarted.group, event.event_id) == "committed":
                    return
                await asyncio.sleep(0.05)
            raise AssertionError("Replacement worker did not commit pending event")
        await asyncio.wait_for(wait_for_commit(), timeout=10)

        records = await bus.redis.xrange(stream)
        completed = [
            parsed for _, fields in records
            if (parsed := EventEnvelope.model_validate_json(fields["event"])).event_type
            == "grid.test.recovery.completed"
        ]
        assert len(completed) == 1
        assert completed[0].correlation_id == cid
        assert await bus.redis.xpending_range(stream, restarted.group, "-", "+", 10) == []

        # Replay the original event ID: OAF's durable step/terminal record
        # must prevent a second downstream completion.
        await bus.publish(stream, event)
        await asyncio.sleep(0.25)
        records = await bus.redis.xrange(stream)
        completed = [
            parsed for _, fields in records
            if (parsed := EventEnvelope.model_validate_json(fields["event"])).event_type
            == "grid.test.recovery.completed"
        ]
        assert len(completed) == 1
    finally:
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await bus.redis.delete(stream)
        await bus.redis.aclose()
