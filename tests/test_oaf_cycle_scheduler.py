"""Scheduler and quality unit tests."""
import json
from uuid import UUID

import pandas as pd
import pytest
from shared.correlation.registry import CorrelationRegistry
from gridregime.oaf.cycle_scheduler import submit_cycle
from gridregime.oaf.acquisition_quality import assess_eia_artifact


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.events = []

    async def set(self, key, value, nx=False):
        if nx and key in self.values:
            return None
        self.values[key] = value
        return True

    async def get(self, key):
        return self.values.get(key)

    async def eval(self, script, nkeys, key, stream, event_id, encoded):
        existing = self.values.get(key)
        if existing:
            if existing != event_id:
                raise ValueError("identity conflict")
            return [0, existing]
        self.events.append((stream, json.loads(encoded)))
        self.values[key] = event_id
        return [1, event_id]


@pytest.mark.asyncio
async def test_scheduler_replay_is_idempotent():
    redis = FakeRedis()
    registry = CorrelationRegistry(redis)
    args = dict(
        redis=redis, correlation_registry=registry, ba="PJM",
        as_of="2026-11-07T17:00Z",
    )
    first = await submit_cycle(**args)
    again = await submit_cycle(**args)
    assert first["published"] is True
    assert again["published"] is False
    assert first["correlation_id"] == again["correlation_id"]
    assert len(redis.events) == 1
    event = redis.events[0][1]
    assert event["correlation_id"] == first["correlation_id"]
    assert event["event_type"] == "grid.acquisition.cycle.requested"


def write_source(tmp_path, end="2026-11-07T15:00Z"):
    path = tmp_path / "eia.csv"
    times = pd.date_range("2026-11-07T12:00Z", end, freq="h")
    pd.DataFrame({
        "timestamp_utc": times, "ba": ["PJM"] * len(times),
        "demand_mwh": [100000] * len(times),
        "forecast_mwh": [99000] * len(times),
        "interchange_mwh": [1000] * len(times),
    }).to_csv(path, index=False)
    return path


def test_quality_current_but_publication_unverified(tmp_path):
    result = assess_eia_artifact(
        artifact_path=write_source(tmp_path),
        end="2026-11-07T15:00Z", ba="PJM",
        checked_at="2026-11-07T17:00Z",
    )
    assert result["status"] == "observations-current-publication-unverified"
    assert result["source_publication_time_verified"] is False


def test_quality_stale(tmp_path):
    result = assess_eia_artifact(
        artifact_path=write_source(tmp_path),
        end="2026-11-07T15:00Z", ba="PJM",
        checked_at="2026-11-08T17:00Z",
    )
    assert result["status"] == "stale"


def test_quality_incomplete(tmp_path):
    result = assess_eia_artifact(
        artifact_path=write_source(tmp_path, "2026-11-07T14:00Z"),
        end="2026-11-07T15:00Z", ba="PJM",
        checked_at="2026-11-07T17:00Z",
    )
    assert result["status"] == "incomplete-window"


def test_quality_reject_duplicate(tmp_path):
    path = write_source(tmp_path)
    df = pd.read_csv(path)
    pd.concat([df, df.iloc[-1:]]).to_csv(path, index=False)
    with pytest.raises(ValueError, match="Duplicate"):
        assess_eia_artifact(
            artifact_path=path, end="2026-11-07T15:00Z", ba="PJM",
            checked_at="2026-11-07T17:00Z",
        )


@pytest.mark.asyncio
async def test_scheduler_require_pjm_propagates_to_plan_and_identity():
    redis = FakeRedis()
    registry = CorrelationRegistry(redis)
    args = dict(redis=redis, correlation_registry=registry, ba="PJM",
                as_of="2026-11-07T17:00Z")
    no_pjm = await submit_cycle(**args)
    with_pjm = await submit_cycle(**args, require_pjm=True)
    assert with_pjm["plan"]["require_pjm"] is True
    assert with_pjm["correlation_id"] != no_pjm["correlation_id"]
    assert redis.events[1][1]["payload"]["require_pjm"] is True
