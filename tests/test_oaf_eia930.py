"""Contract tests for the OpenAgentFabric EIA-930 adapter.

Run with OpenAgentFabric's framework directory on PYTHONPATH.
"""
import hashlib
from uuid import uuid4

import pandas as pd
import pytest

pytest.importorskip("shared.agent.base")
from shared.eventbus.events import EventEnvelope
from gridregime.oaf.eia930_agent import (
    EIA930AcquisitionAgent,
    FETCHED,
    REQUESTED,
    persist_eia_window,
)


def sample_frame():
    return pd.DataFrame({
        "timestamp_utc": pd.to_datetime(["2022-12-20T00:00Z", "2022-12-20T01:00Z"]),
        "ba": ["PJM", "PJM"],
        "demand_mwh": [100.0, 101.0],
        "forecast_mwh": [99.0, 100.0],
        "interchange_mwh": [-2.0, -3.0],
    })


def test_repeat_fetch_produces_identical_artifact(tmp_path):
    def fetcher(ba, start, end):
        return sample_frame()

    args = dict(
        ba="PJM", start="2022-12-20T00", end="2022-12-20T01",
        output_dir=tmp_path, fetcher=fetcher,
    )
    first = persist_eia_window(**args)
    second = persist_eia_window(**args)
    assert first == second
    assert len(list(tmp_path.glob("eia930-*.csv"))) == 1
    assert hashlib.sha256(
        (tmp_path / ("eia930-" + first["sha256"] + ".csv")).read_bytes()
    ).hexdigest() == first["sha256"]


def test_missing_required_series_fails_closed(tmp_path):
    def fetcher(ba, start, end):
        return sample_frame().drop(columns=["forecast_mwh"])
    with pytest.raises(ValueError, match="missing required columns"):
        persist_eia_window(
            ba="PJM", start="a", end="b", output_dir=tmp_path, fetcher=fetcher
        )


def test_null_required_series_fails_closed(tmp_path):
    def fetcher(ba, start, end):
        frame = sample_frame()
        frame.loc[0, "forecast_mwh"] = float("nan")
        return frame
    with pytest.raises(ValueError, match="contain nulls"):
        persist_eia_window(
            ba="PJM", start="a", end="b", output_dir=tmp_path, fetcher=fetcher
        )


@pytest.mark.asyncio
async def test_oaf_envelope_preserves_correlation_and_causation(tmp_path):
    agent = object.__new__(EIA930AcquisitionAgent)
    agent.name = "grid-eia930"
    agent.output_dir = tmp_path
    agent.fetcher = lambda ba, start, end: sample_frame()
    request = EventEnvelope(
        event_type=REQUESTED,
        source_agent="grid-coordinator",
        correlation_id=uuid4(),
        payload={"ba": "PJM", "start": "2022-12-20T00", "end": "2022-12-20T01"},
    )
    output = await agent.handle_event(request)
    assert len(output) == 1
    assert output[0].event_type == FETCHED
    assert output[0].correlation_id == request.correlation_id
    assert output[0].causation_id == request.event_id
    assert output[0].payload["row_count"] == 2


def test_missing_hour_rejected(tmp_path):
    def fetcher(ba, start, end):
        return sample_frame().iloc[[0]].copy()
    with pytest.raises(ValueError, match="hourly coverage mismatch"):
        persist_eia_window(
            ba="PJM", start="2022-12-20T00", end="2022-12-20T01",
            output_dir=tmp_path, fetcher=fetcher,
        )


def test_extra_hour_rejected(tmp_path):
    def fetcher(ba, start, end):
        frame = sample_frame()
        extra = frame.iloc[[1]].copy()
        extra["timestamp_utc"] = pd.Timestamp("2022-12-20T02:00Z")
        return pd.concat([frame, extra], ignore_index=True)
    with pytest.raises(ValueError, match="hourly coverage mismatch"):
        persist_eia_window(
            ba="PJM", start="2022-12-20T00", end="2022-12-20T01",
            output_dir=tmp_path, fetcher=fetcher,
        )


def test_duplicate_hour_rejected(tmp_path):
    def fetcher(ba, start, end):
        frame = sample_frame()
        return pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate UTC timestamps"):
        persist_eia_window(
            ba="PJM", start="2022-12-20T00", end="2022-12-20T01",
            output_dir=tmp_path, fetcher=fetcher,
        )


def test_invalid_window_rejected(tmp_path):
    with pytest.raises(ValueError, match="ordered, whole-hour"):
        persist_eia_window(
            ba="PJM", start="2022-12-20T02", end="2022-12-20T01",
            output_dir=tmp_path, fetcher=lambda *args: sample_frame(),
        )


def test_artifact_preserves_standalone_fetch_values(tmp_path):
    """The wrapper must not alter the underlying scientific data values."""
    original = sample_frame()
    def fetcher(ba, start, end):
        return original.copy()
    result = persist_eia_window(
        ba="PJM", start="2022-12-20T00", end="2022-12-20T01",
        output_dir=tmp_path, fetcher=fetcher,
    )
    stored = pd.read_csv(result["artifact_path"])
    for column in ("demand_mwh", "forecast_mwh", "interchange_mwh"):
        assert stored[column].tolist() == original[column].tolist()
    assert pd.to_datetime(stored["timestamp_utc"], utc=True).tolist() == (
        original["timestamp_utc"].tolist()
    )


def test_unexpected_balancing_authority_rejected(tmp_path):
    def fetcher(ba, start, end):
        frame = sample_frame()
        frame.loc[0, "ba"] = "MISO"
        return frame
    with pytest.raises(ValueError, match="unexpected balancing authority"):
        persist_eia_window(
            ba="PJM", start="2022-12-20T00", end="2022-12-20T01",
            output_dir=tmp_path, fetcher=fetcher,
        )
