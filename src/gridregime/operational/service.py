"""Deterministic domain logic; invoke from OAF agents, scheduled jobs or replay.

This simple L2 detector is an illustrative baseline, NOT a calibrated operational
alarm. It must not be deployed without calibration and an explicit promotion gate.
"""
from __future__ import annotations
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
from json import dumps
from math import sqrt
from .contracts import FeatureSnapshot, StressSignal, TrainingCandidate, FEATURES, utc


def evaluate_stress(snapshot: FeatureSnapshot, *, model_id: str = "joint-l2-baseline", model_version: str = "unvalidated-v1", threshold: float = 4.0, decision_as_of: str | None = None) -> StressSignal:
    if threshold <= 0:
        raise ValueError("threshold must be positive")
    decision = decision_as_of or datetime.now(timezone.utc).isoformat()
    if utc(decision) < utc(snapshot.observation_as_of):
        raise ValueError("decision predates observation")
    score = sqrt(sum(snapshot.values[k] ** 2 for k in FEATURES))
    return StressSignal(observation_as_of=snapshot.observation_as_of, decision_as_of=decision, model_id=model_id, model_version=model_version, feature_version=snapshot.feature_version, source_sha256=snapshot.source_sha256, score=score, state="elevated" if score >= threshold else "normal", evidence=dict(snapshot.values), publication_time_verified=snapshot.publication_time_verified)


def candidate_from_training(*, model_id: str, model_version: str, feature_version: str, artifact: bytes, evaluation: dict, trained_as_of: str) -> TrainingCandidate:
    """Create an immutable candidate descriptor; does not approve or deploy it."""
    return TrainingCandidate(model_id=model_id, model_version=model_version, feature_version=feature_version, artifact_sha256=sha256(artifact).hexdigest(), trained_as_of=trained_as_of, evaluation=evaluation)
