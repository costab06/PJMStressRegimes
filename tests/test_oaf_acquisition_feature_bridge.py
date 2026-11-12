"""Offline OAF bridge contract tests with a Redis-like atomic hash."""
import hashlib
from uuid import uuid4

import pytest
from shared.eventbus.events import EventEnvelope

from gridregime.oaf.acquisition_feature_bridge import AcquisitionFeatureBridgeAgent
from gridregime.oaf.acquisition_status import DISPATCHED, STATUS_CHANGED
from gridregime.oaf.eia930_agent import FETCHED as EIA_FETCHED
from gridregime.oaf.feature_agent import REQUESTED as FEATURE_REQUESTED


class FakeRedis:
    def __init__(self):
        self.data = {}

    async def eval(self, script, count, key, field, encoded):
        fields = self.data.setdefault(key, {})
        if field == "dispatch" and field in fields and fields[field] != encoded:
            raise ValueError("CONFLICTING_CYCLE_DISPATCH")
        fields[field] = encoded
        return [v.encode() for pair in fields.items() for v in pair]


class Bus:
    def __init__(self):
        self.redis = FakeRedis()


def fixtures(tmp_path):
    source = tmp_path / "eia.csv"
    baseline = tmp_path / "baseline.parquet"
    source.write_bytes(b"frozen-source")
    baseline.write_bytes(b"frozen-baseline")
    dispatch = {
        "ba": "PJM", "start": "2022-12-19T05",
        "end": "2022-12-20T04", "as_of": "2022-12-20T06:00Z",
        "publication_lag_hours": 2, "require_pjm": False,
    }
    fetched = {
        "ba": "PJM", "start": dispatch["start"], "end": dispatch["end"],
        "artifact_path": str(source),
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }
    status = {
        "status": "observation-ready-publication-unverified",
        "ready_for_predictive_inference": False,
        "sources": {"eia930": "observations-current-publication-unverified"},
    }
    return baseline, {
        DISPATCHED: dispatch, EIA_FETCHED: fetched, STATUS_CHANGED: status,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("order", [
    (DISPATCHED, EIA_FETCHED, STATUS_CHANGED),
    (STATUS_CHANGED, EIA_FETCHED, DISPATCHED),
    (EIA_FETCHED, DISPATCHED, STATUS_CHANGED),
])
async def test_bridge_joins_events_regardless_of_arrival_order(tmp_path, order):
    baseline, payloads = fixtures(tmp_path)
    agent = object.__new__(AcquisitionFeatureBridgeAgent)
    agent.name = "grid-acquisition-feature-bridge"
    agent.baseline_path = baseline
    agent.event_bus = Bus()
    cid = uuid4()
    results = []
    for kind in order:
        event = EventEnvelope(
            event_type=kind, source_agent="test",
            correlation_id=cid, payload=payloads[kind],
        )
        results.extend(await agent.handle_event(event))
    assert len(results) == 1
    result = results[0]
    assert result.event_type == FEATURE_REQUESTED
    assert result.correlation_id == cid
    assert result.payload["as_of"] == "2022-12-20T04:00:00+00:00"
    assert result.payload["decision_as_of"] == "2022-12-20T06:00:00+00:00"
    assert result.payload["ready_for_predictive_inference"] is False


@pytest.mark.asyncio
async def test_bridge_does_not_request_features_for_unready_cycle(tmp_path):
    baseline, payloads = fixtures(tmp_path)
    payloads[STATUS_CHANGED]["status"] = "pending-evidence"
    agent = object.__new__(AcquisitionFeatureBridgeAgent)
    agent.name = "grid-acquisition-feature-bridge"
    agent.baseline_path = baseline
    agent.event_bus = Bus()
    cid = uuid4()
    for kind in (DISPATCHED, EIA_FETCHED, STATUS_CHANGED):
        results = await agent.handle_event(EventEnvelope(
            event_type=kind, source_agent="test",
            correlation_id=cid, payload=payloads[kind],
        ))
        assert results == []


@pytest.mark.asyncio
async def test_bridge_rejects_conflicting_dispatch_replay(tmp_path):
    baseline, payloads = fixtures(tmp_path)
    agent = object.__new__(AcquisitionFeatureBridgeAgent)
    agent.name = "grid-acquisition-feature-bridge"
    agent.baseline_path = baseline
    agent.event_bus = Bus()
    cid = uuid4()
    first = EventEnvelope(event_type=DISPATCHED, source_agent="test",
                          correlation_id=cid, payload=payloads[DISPATCHED])
    assert await agent.handle_event(first) == []
    changed = dict(payloads[DISPATCHED], require_pjm=True)
    with pytest.raises(ValueError, match="CONFLICTING_CYCLE_DISPATCH"):
        await agent.handle_event(EventEnvelope(
            event_type=DISPATCHED, source_agent="test",
            correlation_id=cid, payload=changed,
        ))
