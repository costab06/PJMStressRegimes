"""Run a real OpenAgentFabric Redis consumer, like SECAgents run_parser.

Example: python -m gridregime.operational.run_worker training
         python -m gridregime.operational.run_worker inference
"""
from __future__ import annotations
import argparse
import asyncio
import logging
import os
from pathlib import Path
from shared.correlation.registry import CorrelationRegistry
from shared.eventbus.redis import RedisEventBus
from .oaf_agents import GridTrainingAgent, GridInferenceAgent


async def run_worker(kind: str, *, redis_url: str, stream: str, artifact_dir: str) -> None:
    if kind not in {'training', 'inference'}:
        raise ValueError('kind must be training or inference')
    bus = RedisEventBus(redis_url=redis_url)
    try:
        await bus.redis.ping()
        registry = CorrelationRegistry(bus.redis)
        agent_class = GridTrainingAgent if kind == 'training' else GridInferenceAgent
        agent = agent_class(event_bus=bus, correlation_registry=registry,
                            artifact_dir=Path(artifact_dir), stream=stream)
        logging.info('Starting %s: stream=%s group=%s consumer=%s',kind,agent.stream,agent.group,agent.consumer)
        await agent.run()
    finally:
        await bus.close()


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description='Run a GridRegime OpenAgentFabric Redis worker')
    parser.add_argument('kind', choices=['training','inference'])
    parser.add_argument('--redis-url',default=os.environ.get('REDIS_URL','redis://localhost:6380/0'))
    parser.add_argument('--stream',default=os.environ.get('OAF_STREAM','oaf.events'))
    parser.add_argument('--artifact-dir',default=os.environ.get('GRID_MODEL_ARTIFACT_DIR','data/models'))
    args = parser.parse_args(argv)
    asyncio.run(run_worker(args.kind,redis_url=args.redis_url,stream=args.stream,artifact_dir=args.artifact_dir))


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    try:
        main()
    except KeyboardInterrupt:
        pass
