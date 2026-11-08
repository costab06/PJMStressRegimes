"""Live PJM acquisition adapter contract tests (offline, injected client)."""
import pandas as pd
import pytest
from uuid import uuid4

from shared.eventbus.events import EventEnvelope
from gridregime.oaf.pjm_live_agent import (
    persist_live_pjm, PJMLiveAcquisitionAgent, REQUESTED, FETCHED,
)


def sample(start, end):
    return pd.DataFrame([{
        "Publish Time": pd.Timestamp("2026-11-07T15:00Z"),
        "Procedure": "Cold Weather Alert",
        "Region": "RTO",
    }])


def test_live_artifact_provenance_and_determinism(tmp_path):
    args = dict(
        start="2026-11-07T14:00Z", end="2026-11-07T16:00Z",
        output_dir=tmp_path, fetcher=sample,
        fetched_at="2026-11-07T17:00Z",
    )
    a = persist_live_pjm(**args)
    b = persist_live_pjm(**args)
    assert a == b
    assert a["record_count"] == 1
    assert a["coverage_status"] == "unverified"
    assert not a["publication_time_verified"]
    assert not a["no_emergency_claim"]


def test_empty_feed_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="ambiguous"):
        persist_live_pjm(
            start="2026-11-07T14:00Z", end="2026-11-07T16:00Z",
            output_dir=tmp_path, fetcher=lambda *_: pd.DataFrame(),
        )


def test_naive_window_rejected(tmp_path):
    with pytest.raises(ValueError, match="offset-aware"):
        persist_live_pjm(
            start="2026-11-07T14:00", end="2026-11-07T16:00Z",
            output_dir=tmp_path, fetcher=sample,
        )


@pytest.mark.asyncio
async def test_live_agent_event_lineage(tmp_path):
    agent = object.__new__(PJMLiveAcquisitionAgent)
    agent.name = "grid-pjm-live"
    agent.output_dir = tmp_path
    agent.fetcher = sample
    event = EventEnvelope(
        event_type=REQUESTED, source_agent="test",
        correlation_id=uuid4(),
        payload={"start": "2026-11-07T14:00Z", "end": "2026-11-07T16:00Z"},
    )
    result = await agent.handle_event(event)
    assert len(result) == 1
    assert result[0].event_type == FETCHED
    assert result[0].correlation_id == event.correlation_id
    assert result[0].causation_id == event.event_id


@pytest.mark.asyncio
async def test_coordinator_dispatches_live_pjm_when_requested():
    from gridregime.oaf.acquisition_coordinator import AcquisitionCoordinatorAgent
    agent = object.__new__(AcquisitionCoordinatorAgent)
    agent.name = "grid-acquisition-coordinator"
    event = EventEnvelope(
        event_type="grid.acquisition.cycle.requested", source_agent="test",
        payload={"ba": "PJM", "as_of": "2026-11-07T17:00Z",
                 "require_pjm": True},
    )
    events = await agent.handle_event(event)
    assert [e.event_type for e in events] == [
        "grid.eia930.requested", "grid.pjm.live.requested",
        "grid.acquisition.cycle.dispatched",
    ]
    assert events[1].payload["end"] == "2026-11-07T15:00:00+00:00"
    assert events[2].payload["require_pjm"] is True
