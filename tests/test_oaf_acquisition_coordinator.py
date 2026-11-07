"""Acquisition coordinator unit tests; no Redis needed for planning."""
from uuid import uuid4

import pytest
from shared.eventbus.events import EventEnvelope
from gridregime.oaf.acquisition_coordinator import (
    AcquisitionCoordinatorAgent, CYCLE_REQUESTED, CYCLE_DISPATCHED,
    EIA_REQUESTED, plan_acquisition_cycle,
)


def test_inclusive_utc_window():
    p = plan_acquisition_cycle(
        ba="PJM", as_of="2026-11-07T12:00:00-05:00",
        lookback_hours=24, publication_lag_hours=2,
    )
    assert p["as_of"] == "2026-11-07T17:00:00+00:00"
    assert p["start"] == "2026-11-06T16"
    assert p["end"] == "2026-11-07T15"
    assert p["freshness_status"] == "unverified-pending-acquisition"
    assert p == plan_acquisition_cycle(
        ba="PJM", as_of="2026-11-07T17:00Z",
        lookback_hours=24, publication_lag_hours=2,
    )


@pytest.mark.parametrize("kwargs", [
    {"ba": "", "as_of": "2026-11-07T17:00Z"},
    {"ba": "PJM", "as_of": "2026-11-07T17:30Z"},
    {"ba": "PJM", "as_of": "2026-11-07T17:00Z", "lookback_hours": 3},
    {"ba": "PJM", "as_of": "2026-11-07T17:00Z", "lookback_hours": True},
    {"ba": "PJM", "as_of": "2026-11-07T17:00Z", "publication_lag_hours": -1},
])
def test_invalid_cycle_rejected(kwargs):
    with pytest.raises(ValueError):
        plan_acquisition_cycle(**kwargs)


@pytest.mark.asyncio
async def test_coordinator_emits_correlated_work():
    # Handler is pure; no Redis is required until BaseAgent.run/process_message.
    agent = object.__new__(AcquisitionCoordinatorAgent)
    agent.name = "grid-acquisition-coordinator"
    correlation = uuid4()
    request = EventEnvelope(
        event_type=CYCLE_REQUESTED, source_agent="test",
        correlation_id=correlation,
        payload={"ba": "PJM", "as_of": "2026-11-07T17:00Z"},
    )
    outputs = await agent.handle_event(request)
    assert [e.event_type for e in outputs] == [EIA_REQUESTED, CYCLE_DISPATCHED]
    assert all(e.correlation_id == correlation and e.causation_id == request.event_id for e in outputs)
    assert outputs[0].payload == {
        "ba": "PJM", "start": "2026-11-06T16", "end": "2026-11-07T15",
    }
    assert outputs[1].payload["freshness_status"] == "unverified-pending-acquisition"
