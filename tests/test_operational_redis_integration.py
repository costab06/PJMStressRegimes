"""Opt-in real Redis/OAF integration test.

Run: GRID_OAF_REDIS_TEST=1 python -m pytest tests/test_operational_redis_integration.py -q
Requires a reachable Redis and installed OpenAgentFabric. Uses an isolated stream.
"""
from __future__ import annotations
import asyncio
import dataclasses
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4
import pytest

pytestmark = pytest.mark.skipif(os.environ.get('GRID_OAF_REDIS_TEST') != '1',
                                reason='opt-in test requires a real Redis instance')


def _write(path, snapshots):
    data=json.dumps([dataclasses.asdict(s) for s in snapshots]).encode()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


@pytest.mark.asyncio
async def test_redis_training_promotion_inference(tmp_path):
    from shared.eventbus.redis import RedisEventBus
    from shared.correlation.registry import CorrelationRegistry
    from shared.eventbus.events import EventEnvelope
    from gridregime.operational import FeatureSnapshot
    from gridregime.operational.oaf_agents import GridTrainingAgent, GridInferenceAgent
    from gridregime.operational.lifecycle import promote_candidate
    from gridregime.operational.contracts import TrainingCandidate
    from datetime import datetime, timezone

    url=os.environ.get('REDIS_URL','redis://localhost:6380/0')
    stream='gridregime.integration.'+uuid4().hex
    bus=RedisEventBus(redis_url=url)
    tasks=[]
    try:
        await bus.redis.ping()
        registry=CorrelationRegistry(bus.redis)
        models=tmp_path/'models'
        trainer=GridTrainingAgent(event_bus=bus,correlation_registry=registry,
                                  artifact_dir=models,stream=stream,
                                  recovery_interval=0.2,min_idle_ms=0,heartbeat_interval=0.1)
        infer=GridInferenceAgent(event_bus=bus,correlation_registry=registry,
                                 artifact_dir=models,stream=stream,
                                 recovery_interval=0.2,min_idle_ms=0,heartbeat_interval=0.1)
        tasks=[asyncio.create_task(trainer.run()),asyncio.create_task(infer.run())]
        snapshots=[FeatureSnapshot(observation_as_of=f'2026-07-{i:02d}T00:00:00Z',
            feature_version='frozen-v1',source_sha256='a'*64,
            values={'load_z':float(i%5),'fe_z':1.,'ramp3_z':0.,'ic_z':0.}) for i in range(1,25)]
        training=tmp_path/'training.json'
        checksum=_write(training,snapshots)
        record=await registry.create(trigger_type='grid.model.training.requested',
            trigger_timestamp=datetime.now(timezone.utc),business_fields={'run':stream})
        await bus.publish(stream,EventEnvelope(event_type='grid.model.training.requested',
            source_agent='integration-test',correlation_id=record.correlation_id,
            payload={'snapshot_path':str(training),'snapshot_sha256':checksum,'model_version':'smoke-v1'}))

        async def await_event(kind, timeout=20):
            async def poll():
                while True:
                    rows=await bus.redis.xrange(stream)
                    for _,fields in rows:
                        event=EventEnvelope.model_validate_json(fields['event'])
                        if event.event_type==kind and event.correlation_id==record.correlation_id:
                            return event
                    await asyncio.sleep(0.1)
            return await asyncio.wait_for(poll(),timeout=timeout)

        candidate_event=await await_event('grid.model.training.candidate')
        assert candidate_event.causation_id is not None
        candidate=TrainingCandidate(**candidate_event.payload)
        assert candidate.approved is False
        # Test-only simulated external evaluation: production needs independent review.
        reviewed=dataclasses.replace(candidate,evaluation={**candidate.evaluation,
                                                             'independent_validation':'passed'})
        promote_candidate(reviewed,artifact_dir=models,approval=True)
        latest=tmp_path/'latest.json'
        latest_checksum=_write(latest,[snapshots[-1]])
        request=EventEnvelope(event_type='grid.model.inference.requested',
            source_agent='integration-test',correlation_id=record.correlation_id,
            payload={'snapshot_path':str(latest),'snapshot_sha256':latest_checksum})
        await bus.publish(stream,request)
        signal=await await_event('grid.stress.signal')
        assert signal.causation_id==request.event_id
        assert signal.payload['model_version']=='smoke-v1'
        assert signal.payload['predictive_validation_status']=='not_established'
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks,return_exceptions=True)
        # Keep the stream for post-failure inspection; TTL avoids indefinite test debris.
        await bus.redis.expire(stream,3600)
        await bus.close()
