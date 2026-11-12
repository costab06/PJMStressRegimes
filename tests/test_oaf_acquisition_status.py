"""Acquisition cycle readiness is conservative and evidence-driven."""
import pytest
from gridregime.oaf.acquisition_status import evaluate_cycle


def test_missing_evidence_is_pending():
    result = evaluate_cycle(dispatch={"ba": "PJM"}, eia=None, pjm=None)
    assert result["status"] == "pending-evidence"
    assert not result["ready_for_predictive_inference"]


def test_stale_eia_is_degraded():
    result = evaluate_cycle(
        dispatch={"ba": "PJM"}, eia={"status": "stale"}, pjm=None,
    )
    assert result["status"] == "degraded"


def test_current_eia_still_not_publication_verified():
    result = evaluate_cycle(
        dispatch={"ba": "PJM"},
        eia={"status": "observations-current-publication-unverified"},
        pjm=None,
    )
    assert result["status"] == "observation-ready-publication-unverified"
    assert not result["publication_time_verified"]
    assert not result["ready_for_predictive_inference"]


def test_archival_pjm_does_not_satisfy_required_live_source():
    result = evaluate_cycle(
        dispatch={"ba": "PJM"},
        eia={"status": "observations-current-publication-unverified"},
        pjm={"coverage_status": "unverified"},
        require_pjm=True,
    )
    assert result["status"] == "pending-evidence"
    assert result["sources"]["pjm_procedures"] == "unverified"


@pytest.mark.asyncio
async def test_status_preserves_archived_and_live_pjm_evidence():
    from uuid import uuid4
    from shared.eventbus.events import EventEnvelope
    from gridregime.oaf.acquisition_status import (
        AcquisitionCycleStatusAgent, PJM_FETCHED, PJM_LIVE_FETCHED,
    )

    class Redis:
        def __init__(self):
            self.hashes = {}

        async def eval(self, script, nkeys, key, field, value):
            import json
            state = self.hashes.setdefault(key, {})
            if field in state and state[field] != value:
                raise ValueError("CONFLICTING_CYCLE_EVIDENCE")
            state[field] = value
            return [part.encode() for pair in state.items() for part in pair]

    class Bus:
        redis = Redis()

    agent = object.__new__(AcquisitionCycleStatusAgent)
    agent.name = "grid-acquisition-status"
    agent.event_bus = Bus()
    cid = uuid4()
    for kind in (PJM_LIVE_FETCHED, PJM_FETCHED):
        await agent.handle_event(EventEnvelope(
            event_type=kind, source_agent="test", correlation_id=cid,
            payload={"coverage_status": "unverified", "source": kind},
        ))
    state = agent.event_bus.redis.hashes[f"grid:cycle:evidence:{cid}"]
    assert "pjm_live" in state
    assert "pjm_archive" in state
    assert state["pjm_live"] != state["pjm_archive"]


@pytest.mark.asyncio
async def test_status_rejects_conflicting_eia_evidence(tmp_path):
    from uuid import uuid4
    from shared.eventbus.events import EventEnvelope
    from gridregime.oaf.acquisition_status import AcquisitionCycleStatusAgent, EIA_ASSESSED

    class Redis:
        def __init__(self):
            self.values = {}

        async def eval(self, script, nkeys, key, field, value):
            state = self.values.setdefault(key, {})
            if field in state and state[field] != value:
                raise ValueError("CONFLICTING_CYCLE_EVIDENCE")
            state[field] = value
            return [part.encode() for pair in state.items() for part in pair]

    class Bus:
        redis = Redis()

    agent = object.__new__(AcquisitionCycleStatusAgent)
    agent.name = "grid-acquisition-status"
    agent.event_bus = Bus()
    cid = uuid4()
    def event(status):
        return EventEnvelope(event_type=EIA_ASSESSED, source_agent="test",
                             correlation_id=cid, payload={"status": status})
    await agent.handle_event(event("stale"))
    await agent.handle_event(event("stale"))
    with pytest.raises(ValueError, match="CONFLICTING_CYCLE_EVIDENCE"):
        await agent.handle_event(event("observations-current-publication-unverified"))
