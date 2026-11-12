"""Run the OAF acquisition-to-feature agents as supervised Redis consumers.

Requires OpenAgentFabric pinned to the commit in CI. Example:
  python -m gridregime.oaf.run_workers --baseline-path data/baseline.parquet \
      --artifact-dir data/derived/oaf
Run schedule_once separately to enqueue acquisition cycles.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from shared.correlation.registry import CorrelationRegistry
from shared.eventbus.redis import RedisEventBus

from gridregime.oaf.baseline_manifest import verify_baseline_manifest
from gridregime.oaf.acquisition_coordinator import AcquisitionCoordinatorAgent
from gridregime.oaf.acquisition_quality import AcquisitionQualityAgent
from gridregime.oaf.acquisition_status import AcquisitionCycleStatusAgent
from gridregime.oaf.acquisition_feature_bridge import AcquisitionFeatureBridgeAgent
from gridregime.oaf.eia930_agent import EIA930AcquisitionAgent
from gridregime.oaf.feature_agent import PointInTimeFeatureAgent
from gridregime.oaf.pjm_live_agent import PJMLiveAcquisitionAgent


def build_agents(*, bus, registry, baseline_path: Path, artifact_dir: Path):
    """Construct independent OAF consumers sharing a durable event bus."""
    if not baseline_path.is_file():
        raise FileNotFoundError(f"Frozen baseline not found: {baseline_path}")
    common = {"event_bus": bus, "correlation_registry": registry}
    return [
        AcquisitionCoordinatorAgent(**common),
        EIA930AcquisitionAgent(output_dir=artifact_dir / "eia930", **common),
        AcquisitionQualityAgent(**common),
        PJMLiveAcquisitionAgent(output_dir=artifact_dir / "pjm-live", **common),
        AcquisitionCycleStatusAgent(**common),
        AcquisitionFeatureBridgeAgent(baseline_path=baseline_path, **common),
        PointInTimeFeatureAgent(
            baseline_path=baseline_path, output_dir=artifact_dir / "features", **common,
        ),
    ]


async def run(*, redis_url: str, baseline_path: Path, artifact_dir: Path,
              baseline_manifest: Path | None = None):
    if sys.version_info < (3, 11):
        raise RuntimeError('OAF worker runner requires Python 3.11 or later')
    if baseline_manifest is None:
        raise ValueError('Production worker requires --baseline-manifest')
    verify_baseline_manifest(baseline_path=baseline_path, manifest_path=baseline_manifest)
    bus = RedisEventBus(redis_url=redis_url)
    try:
        registry = CorrelationRegistry(bus.redis)
        agents = build_agents(
            bus=bus, registry=registry,
            baseline_path=baseline_path, artifact_dir=artifact_dir,
        )
        # TaskGroup propagates worker failure and cancels the other workers.
        # OAF BaseAgent.run owns pending recovery and atomic event commits.
        async with asyncio.TaskGroup() as group:
            for agent in agents:
                group.create_task(agent.run(), name=str(agent.name))
    finally:
        await bus.redis.aclose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--redis-url", default="redis://localhost:6379/0")
    parser.add_argument("--baseline-path", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--baseline-manifest", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run(
            redis_url=args.redis_url, baseline_path=args.baseline_path,
            artifact_dir=args.artifact_dir,
            baseline_manifest=args.baseline_manifest,
        ))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
