"""Transport-independent, auditable domain contracts shared by agents and CLI."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite

FEATURES = ("load_z", "fe_z", "ramp3_z", "ic_z")


def utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp must contain a timezone")
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class FeatureSnapshot:
    observation_as_of: str
    feature_version: str
    source_sha256: str
    values: dict[str, float]
    publication_time_verified: bool = False

    def __post_init__(self):
        utc(self.observation_as_of)
        if not self.feature_version or len(self.source_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.source_sha256):
            raise ValueError("invalid feature identity")
        if set(self.values) != set(FEATURES) or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and isfinite(v) for v in self.values.values()):
            raise ValueError("features must be the four finite frozen-v1 values")


@dataclass(frozen=True)
class TrainingCandidate:
    model_id: str
    model_version: str
    feature_version: str
    artifact_sha256: str
    trained_as_of: str
    evaluation: dict
    approved: bool = False

    def __post_init__(self):
        utc(self.trained_as_of)
        if not self.model_id or not self.model_version or not self.feature_version:
            raise ValueError("missing model identity")
        if len(self.artifact_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.artifact_sha256):
            raise ValueError("invalid artifact checksum")


@dataclass(frozen=True)
class StressSignal:
    observation_as_of: str
    decision_as_of: str
    model_id: str
    model_version: str
    feature_version: str
    source_sha256: str
    score: float
    state: str
    evidence: dict[str, float]
    publication_time_verified: bool
    predictive_validation_status: str = "not_established"

    def __post_init__(self):
        if utc(self.decision_as_of) < utc(self.observation_as_of):
            raise ValueError("decision predates observation")
        if self.state not in {"normal", "elevated"} or not isfinite(self.score):
            raise ValueError("invalid signal")
        if self.predictive_validation_status != "not_established":
            raise ValueError("cannot claim emergency predictive validation")
