"""OAF event adapters for GridRegime training and operational inference.

Matches SECAgents' BaseAgent/EventEnvelope pattern. Scheduler/event bus and
runtime worker registration belong to deployment, not these handlers.
"""
from __future__ import annotations
import asyncio
from dataclasses import asdict
from pathlib import Path
from shared.agent.base import BaseAgent
from shared.eventbus.events import EventEnvelope
from .artifacts import read_snapshots
from .lifecycle import train_reference_model, infer_active

TRAIN_REQUESTED = 'grid.model.training.requested'
TRAIN_CANDIDATE = 'grid.model.training.candidate'
INFER_REQUESTED = 'grid.model.inference.requested'
STRESS_SIGNAL = 'grid.stress.signal'


def _reply(agent, event, kind, payload):
    return EventEnvelope(event_type=kind, source_agent=str(agent.name),
        correlation_id=event.correlation_id, causation_id=event.event_id, payload=payload)


class GridTrainingAgent(BaseAgent):
    def __init__(self, *, artifact_dir: str | Path, input_dir: str | Path | None = None, **kwargs):
        super().__init__(name='grid-model-trainer', subscribed_event_types={TRAIN_REQUESTED},
                         completion_event_type=TRAIN_CANDIDATE, **kwargs)
        self.artifact_dir = Path(artifact_dir)
        self.input_dir = Path(input_dir) if input_dir is not None else None

    async def handle_event(self, event: EventEnvelope) -> list[EventEnvelope]:
        if event.event_type != TRAIN_REQUESTED or not isinstance(event.payload, dict):
            raise ValueError('invalid training request')
        p = event.payload
        snapshots = await asyncio.to_thread(read_snapshots, p['snapshot_path'],
                                            expected_sha256=p['snapshot_sha256'], allowed_root=self.input_dir)
        candidate = await asyncio.to_thread(train_reference_model, snapshots,
            artifact_dir=self.artifact_dir, model_version=p['model_version'],
            quantile=p.get('quantile', 0.95))
        return [_reply(self, event, TRAIN_CANDIDATE, asdict(candidate))]


class GridInferenceAgent(BaseAgent):
    def __init__(self, *, artifact_dir: str | Path, input_dir: str | Path | None = None, **kwargs):
        super().__init__(name='grid-model-inference', subscribed_event_types={INFER_REQUESTED},
                         completion_event_type=STRESS_SIGNAL, **kwargs)
        self.artifact_dir = Path(artifact_dir)
        self.input_dir = Path(input_dir) if input_dir is not None else None

    async def handle_event(self, event: EventEnvelope) -> list[EventEnvelope]:
        if event.event_type != INFER_REQUESTED or not isinstance(event.payload, dict):
            raise ValueError('invalid inference request')
        p = event.payload
        snapshots = await asyncio.to_thread(read_snapshots, p['snapshot_path'],
                                            expected_sha256=p['snapshot_sha256'], allowed_root=self.input_dir)
        if len(snapshots) != 1:
            raise ValueError('inference request must contain exactly one snapshot')
        signal = await asyncio.to_thread(infer_active, snapshots[0],
            artifact_dir=self.artifact_dir)
        return [_reply(self, event, STRESS_SIGNAL, asdict(signal))]
