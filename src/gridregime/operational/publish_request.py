"""Publish checksum-verified artifact references to the OAF Redis event bus.

This is a producer, not a scheduler. Use a system timer/cron to invoke it.
"""
from __future__ import annotations
import argparse
import asyncio
import os
from shared.eventbus.events import EventEnvelope
from shared.correlation.registry import CorrelationRegistry
from datetime import datetime, timezone
from shared.eventbus.redis import RedisEventBus
from .requests import request_for_artifact


async def publish_request(*, kind: str, snapshots: str, model_version: str | None,
                          quantile: float, redis_url: str, stream: str):
    descriptor = request_for_artifact(kind=kind,path=snapshots,
                                      model_version=model_version,quantile=quantile)
    bus = RedisEventBus(redis_url=redis_url)
    try:
        await bus.redis.ping()
        registry = CorrelationRegistry(bus.redis)
        correlation = await registry.create(
            trigger_type=descriptor['event_type'],
            trigger_timestamp=datetime.now(timezone.utc),
            business_fields={'snapshot_sha256':descriptor['payload']['snapshot_sha256'],
                             'model_version':descriptor['payload'].get('model_version')},
        )
        event = EventEnvelope(event_type=descriptor['event_type'],
                              source_agent='grid-operational-producer',
                              correlation_id=correlation.correlation_id,
                              payload=descriptor['payload'])
        await bus.publish(stream, event)
        return event
    finally:
        await bus.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Publish a GridRegime request into OAF')
    parser.add_argument('kind',choices=['train','infer'])
    parser.add_argument('--snapshots',required=True)
    parser.add_argument('--model-version')
    parser.add_argument('--quantile',type=float,default=0.95)
    parser.add_argument('--redis-url',default=os.environ.get('REDIS_URL','redis://localhost:6380/0'))
    parser.add_argument('--stream',default=os.environ.get('OAF_STREAM','oaf.events'))
    args=parser.parse_args(argv)
    event=asyncio.run(publish_request(kind=args.kind,snapshots=args.snapshots,
        model_version=args.model_version,quantile=args.quantile,redis_url=args.redis_url,stream=args.stream))
    print(f'Published {event.event_type}: {event.event_id} correlation={event.correlation_id}')


if __name__=='__main__':
    main()
