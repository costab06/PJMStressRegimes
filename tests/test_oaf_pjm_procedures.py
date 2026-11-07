"""Archived PJM operational procedure adapter tests."""
import pandas as pd
import pytest
from uuid import uuid4

from shared.eventbus.events import EventEnvelope
from gridregime.oaf.pjm_procedures_agent import (
    PJMProceduresAcquisitionAgent, REQUESTED, FETCHED, persist_pjm_procedures,
)


def source(tmp_path, rows=None):
    p = tmp_path / "pjm.csv"
    pd.DataFrame(rows if rows is not None else [
        {"timestamp_et": "2026-11-07T10:00:00-05:00",
         "procedure_type": "Emergency Procedure",
         "description": "Test archival record"},
        {"timestamp_et": "2026-11-08T10:00:00-05:00",
         "procedure_type": "Other",
         "description": "Outside window"},
    ]).to_csv(p, index=False)
    return p


def test_archived_window_deterministic(tmp_path):
    p = source(tmp_path)
    kwargs = dict(
        start="2026-11-07T14:00Z", end="2026-11-07T16:00Z",
        source_path=p, output_dir=tmp_path / "artifacts",
        source_name="test-archival-export",
    )
    first = persist_pjm_procedures(**kwargs)
    again = persist_pjm_procedures(**kwargs)
    assert first == again
    assert first["record_count"] == 1
    assert first["coverage_status"] == "unverified"
    assert first["publication_time_verified"] is False
    assert first["no_emergency_claim"] is False
    assert pd.read_csv(first["artifact_path"]).shape[0] == 1


def test_empty_window_is_not_no_emergency_evidence(tmp_path):
    result = persist_pjm_procedures(
        start="2026-11-01T00:00Z", end="2026-11-01T01:00Z",
        source_path=source(tmp_path), output_dir=tmp_path / "out",
        source_name="archived-export",
    )
    assert result["record_count"] == 0
    assert result["no_emergency_claim"] is False


def test_naive_timestamp_rejected(tmp_path):
    p = source(tmp_path, [
        {"timestamp_et": "2026-11-07 10:00:00",
         "procedure_type": "Emergency", "description": "Bad time"},
    ])
    with pytest.raises(ValueError, match="offset"):
        persist_pjm_procedures(
            start="2026-11-07T14:00Z", end="2026-11-07T16:00Z",
            source_path=p, output_dir=tmp_path / "out",
            source_name="archived-export",
        )


@pytest.mark.asyncio
async def test_agent_preserves_causation(tmp_path):
    p = source(tmp_path)
    agent = object.__new__(PJMProceduresAcquisitionAgent)
    agent.name = "grid-pjm-procedures"
    agent.output_dir = tmp_path / "out"
    request = EventEnvelope(
        event_type=REQUESTED, source_agent="test",
        correlation_id=uuid4(),
        payload={
            "start": "2026-11-07T14:00Z",
            "end": "2026-11-07T16:00Z",
            "source_path": str(p), "source_name": "test-export",
        },
    )
    events = await agent.handle_event(request)
    assert len(events) == 1
    assert events[0].event_type == FETCHED
    assert events[0].correlation_id == request.correlation_id
    assert events[0].causation_id == request.event_id
