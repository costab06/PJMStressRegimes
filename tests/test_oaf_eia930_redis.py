"""Redis-backed end-to-end EIA-930 agent test.

Runs only when OAF_TEST_REDIS_URL is configured. Uses isolated stream names.
"""
import os
from datetime import datetime, timezone
from uuid import uuid4

import pandas as pd
import pytest

pytest.importorskip("shared.agent.base")
from shared.correlation.registry import CorrelationRegistry
from shared.eventbus.events import EventEnvelope
from shared.eventbus.redis import RedisEventBus
from shared.workflow.registry import StepRegistry, StepCommit

from gridregime.oaf.eia930_agent import EIA930AcquisitionAgent, FETCHED, REQUESTED


@pytest.mark.asyncio
async def test_eia930_redis_round_trip_and_replay(tmp_path):
    url = os.environ.get("OAF_TEST_REDIS_URL")
    if not url:
        pytest.skip("Set OAF_TEST_REDIS_URL for Redis integration")
    bus = RedisEventBus(url)
    await bus.redis.ping()
    suffix = uuid4().hex
    stream = f"test.grid.eia930.{suffix}"
    agent = EIA930AcquisitionAgent(
        output_dir=tmp_path,
        event_bus=bus,
        correlation_registry=CorrelationRegistry(bus.redis),
        stream=stream,
        consumer=f"worker-{suffix}",
        fetcher=lambda ba, start, end: pd.DataFrame({
            "timestamp_utc": pd.to_datetime(["2022-12-20T00:00Z", "2022-12-20T01:00Z"]),
            "ba": ["PJM", "PJM"],
            "demand_mwh": [100.0, 101.0],
            "forecast_mwh": [99.0, 100.0],
            "interchange_mwh": [-2.0, -3.0],
        }),
    )
    registry = agent.correlation_registry
    record = await registry.create(
        "grid.eia930.test",
        datetime.now(timezone.utc),
        {"episode_id": suffix},
    )
    source = EventEnvelope(
        event_type=REQUESTED,
        source_agent="grid-coordinator",
        correlation_id=record.correlation_id,
        payload={"ba": "PJM", "start": "2022-12-20T00", "end": "2022-12-20T01"},
    )
    message_id = None
    try:
        await bus.publish(stream, source)
        async for message_id, received in bus.subscribe(
            stream, agent.group, agent.consumer, count=1, block_ms=1000
        ):
            assert received.event_id == source.event_id
            break
        assert message_id is not None
        await agent.process_message(message_id, source)
        assert await bus.get_terminal_state(stream, agent.group, source.event_id) == "committed"
        events = await bus.redis.xrange(stream)
        assert len(events) == 2
        completed = EventEnvelope.model_validate_json(events[1][1].get("event", events[1][1].get(b"event")))
        assert completed.event_type == FETCHED
        assert completed.correlation_id == source.correlation_id
        assert completed.causation_id == source.event_id
        assert completed.payload["row_count"] == 2
        assert len(list(tmp_path.glob("eia930-*.csv"))) == 1
        # A repeated terminal commit must not publish another completion.
        assert not await bus.commit(
            stream, agent.group, message_id, source.event_id, [],
            consumer=agent.consumer, step_commit=StepCommit(
                source.correlation_id, str(agent.name), str(source.event_id),
                "already-committed", "already-committed", {"event_id": str(source.event_id)},
            ),
        )
        assert len(await bus.redis.xrange(stream)) == 2
    finally:
        await bus.redis.delete(
            stream,
            f"oaf:terminal:{stream}:{agent.group}:{source.event_id}",
            bus._attempt_key(stream, agent.group, message_id) if message_id else f"unused:{suffix}",
            StepRegistry(bus.redis).key(source.correlation_id, str(agent.name), str(source.event_id)),
        )
        await registry.delete(record.correlation_id)
        await bus.close()


@pytest.mark.asyncio
async def test_failed_ingestion_retries_then_dead_letters(tmp_path):
    """A permanently incomplete source must not publish a success event."""
    url = os.environ.get("OAF_TEST_REDIS_URL")
    if not url:
        pytest.skip("Set OAF_TEST_REDIS_URL for Redis integration")
    bus = RedisEventBus(url)
    await bus.redis.ping()
    suffix = uuid4().hex
    stream = f"test.grid.failure.{suffix}"
    dlq = f"test.grid.failure.dlq.{suffix}"
    agent = EIA930AcquisitionAgent(
        output_dir=tmp_path,
        event_bus=bus,
        correlation_registry=CorrelationRegistry(bus.redis),
        stream=stream,
        consumer=f"worker-{suffix}",
        dlq_stream=dlq,
        max_attempts=2,
        fetcher=lambda ba, start, end: pd.DataFrame({
            "timestamp_utc": ["2022-12-20T00:00Z"],
            "ba": ["PJM"],
            "demand_mwh": [100.0],
            "forecast_mwh": [99.0],
            # interchange_mwh intentionally absent
        }),
    )
    record = await agent.correlation_registry.create(
        "grid.eia930.failure", datetime.now(timezone.utc), {"episode_id": suffix},
    )
    source = EventEnvelope(
        event_type=REQUESTED, source_agent="grid-coordinator",
        correlation_id=record.correlation_id,
        payload={"ba": "PJM", "start": "2022-12-20T00", "end": "2022-12-20T01"},
    )
    message_id = None
    try:
        await bus.publish(stream, source)
        async for message_id, _ in bus.subscribe(
            stream, agent.group, agent.consumer, count=1, block_ms=1000
        ):
            break
        assert message_id is not None
        await agent.process_message(message_id, source)
        assert await bus.get_terminal_state(stream, agent.group, source.event_id) is None
        assert len(await bus.redis.xrange(stream)) == 1
        await agent.process_message(message_id, source)
        assert await bus.get_terminal_state(stream, agent.group, source.event_id) == "dead_lettered"
        assert len(await bus.redis.xrange(stream)) == 1
        assert len(await bus.redis.xrange(dlq)) == 1
        assert not list(tmp_path.glob("eia930-*.csv"))
    finally:
        await bus.redis.delete(
            stream, dlq,
            f"oaf:terminal:{stream}:{agent.group}:{source.event_id}",
            bus._attempt_key(stream, agent.group, message_id) if message_id else f"unused:{suffix}",
            agent.step_registry.key(source.correlation_id, str(agent.name), str(source.event_id)),
        )
        await agent.correlation_registry.delete(record.correlation_id)
        await bus.close()


@pytest.mark.asyncio
async def test_abandoned_delivery_reclaimed_by_replacement_worker(tmp_path):
    """An unprocessed pending delivery can be recovered by another worker."""
    url = os.environ.get("OAF_TEST_REDIS_URL")
    if not url:
        pytest.skip("Set OAF_TEST_REDIS_URL for Redis integration")
    bus = RedisEventBus(url)
    await bus.redis.ping()
    suffix = uuid4().hex
    stream = f"test.grid.recovery.{suffix}"
    calls = []
    def fetcher(ba, start, end):
        calls.append((ba, start, end))
        return pd.DataFrame({
            "timestamp_utc": pd.to_datetime(["2022-12-20T00:00Z", "2022-12-20T01:00Z"]),
            "ba": ["PJM", "PJM"], "demand_mwh": [100.0, 101.0],
            "forecast_mwh": [99.0, 100.0], "interchange_mwh": [-2.0, -3.0],
        })
    registry = CorrelationRegistry(bus.redis)
    agent = EIA930AcquisitionAgent(
        output_dir=tmp_path, event_bus=bus, correlation_registry=registry,
        stream=stream, consumer=f"replacement-{suffix}", fetcher=fetcher,
    )
    record = await registry.create(
        "grid.eia930.recovery", datetime.now(timezone.utc), {"episode_id": suffix},
    )
    source = EventEnvelope(
        event_type=REQUESTED, source_agent="grid-coordinator",
        correlation_id=record.correlation_id,
        payload={"ba": "PJM", "start": "2022-12-20T00", "end": "2022-12-20T01"},
    )
    try:
        await bus.publish(stream, source)
        original_id = None
        async for original_id, _ in bus.subscribe(
            stream, agent.group, f"abandoned-{suffix}", count=1, block_ms=1000
        ):
            break
        assert original_id is not None
        # Simulate a worker crash after delivery but before processing.
        _, recovered = await bus.reclaim_pending_batch(
            stream, agent.group, agent.consumer, min_idle_ms=0,
        )
        assert len(recovered) == 1
        message_id, event = recovered[0]
        assert message_id == original_id
        await agent.process_message(message_id, event)
        assert await bus.get_terminal_state(stream, agent.group, source.event_id) == "committed"
        assert len(calls) == 1
        assert len(await bus.redis.xrange(stream)) == 2
        assert len(list(tmp_path.glob("eia930-*.csv"))) == 1
    finally:
        await bus.redis.delete(
            stream,
            f"oaf:terminal:{stream}:{agent.group}:{source.event_id}",
            agent.step_registry.key(source.correlation_id, str(agent.name), str(source.event_id)),
        )
        await registry.delete(record.correlation_id)
        await bus.close()
