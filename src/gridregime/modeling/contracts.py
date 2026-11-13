"""Immutable modeling contracts independent of ingestion, orchestration, and interpretation."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import math
import pandas as pd

FROZEN_FEATURES = ("load_z", "fe_z", "ramp3_z", "ic_z")


def _utc(value: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        raise ValueError("Timestamps must be timezone-aware")
    return ts.tz_convert("UTC")


@dataclass(frozen=True)
class FeatureDataset:
    """One continuous, hourly sequence of frozen-v1 observations."""
    frame: pd.DataFrame
    ba: str
    source_sha256: str
    baseline_sha256: str
    feature_version: str = "frozen-v1"
    episode_id: str | None = None
    publication_time_verified: bool = False

    def __post_init__(self) -> None:
        if self.feature_version != "frozen-v1" or not self.ba:
            raise ValueError("Unsupported feature version or empty balancing authority")
        for digest in (self.source_sha256, self.baseline_sha256):
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("SHA-256 must be 64 lowercase hex characters")
        required = ("timestamp_utc",) + FROZEN_FEATURES
        if self.frame.empty or any(c not in self.frame for c in required):
            raise ValueError("Missing frozen-v1 feature columns")
        times = pd.to_datetime(self.frame["timestamp_utc"], utc=False, errors="raise")
        if times.dt.tz is None:
            raise ValueError("Observation timestamps must be timezone-aware")
        times = times.dt.tz_convert("UTC")
        if times.duplicated().any() or not times.is_monotonic_increasing:
            raise ValueError("Observation timestamps must be strictly increasing")
        if (times != times.dt.floor("h")).any():
            raise ValueError("Observations must be aligned to UTC hours")
        if len(times) > 1 and not (times.diff().iloc[1:] == pd.Timedelta(hours=1)).all():
            raise ValueError("Sequence must contain contiguous hourly observations")
        numeric = self.frame.loc[:, FROZEN_FEATURES].apply(pd.to_numeric, errors="raise")
        if not numeric.notna().all().all() or not __import__("numpy").isfinite(numeric.to_numpy()).all():
            raise ValueError("Features must be finite and non-null")
        if "ba" in self.frame and not self.frame["ba"].eq(self.ba).all():
            raise ValueError("Frame balancing authority mismatch")
        object.__setattr__(self, "frame", self.frame.copy(deep=True))

    def matrix(self) -> pd.DataFrame:
        return self.frame.loc[:, FROZEN_FEATURES].copy()


@dataclass(frozen=True)
class ModelResult:
    model_id: str
    model_version: str
    result_type: str
    observation_as_of: str
    decision_as_of: str
    values: dict[str, Any]
    feature_version: str = "frozen-v1"
    predictive_validation_status: str = "not_established"

    def __post_init__(self) -> None:
        if not self.model_id or not self.model_version or not self.result_type:
            raise ValueError("Model identity and result type are required")
        if self.feature_version != "frozen-v1":
            raise ValueError("Unsupported feature version")
        if _utc(self.decision_as_of) < _utc(self.observation_as_of):
            raise ValueError("Decision time cannot precede observation time")
        if self.predictive_validation_status != "not_established":
            raise ValueError("Modeling infrastructure cannot assert predictive validation")
