"""Redis-backed acquisition-to-frozen-feature integration test.

Uses a fixed historical decision time and explicit quality assessment clock.
Does not assert upstream publication-time availability or risk inference.
"""
import os
from uuid import uuid4

import pandas as pd
import pytest

pytest.importorskip("shared.agent.base")

from shared.eventbus.events import EventEnvelope
from gridregime.oaf.acquisition_coordinator import AcquisitionCoordinatorAgent, CYCLE_REQUESTED
from gridregime.oaf.eia930_agent import EIA930AcquisitionAgent
from gridregime.oaf.acquisition_quality import assess_eia_artifact, ASSESSED
from gridregime.oaf.acquisition_status import AcquisitionCycleStatusAgent, evaluate_cycle
from gridregime.oaf.acquisition_feature_bridge import AcquisitionFeatureBridgeAgent
from gridregime.oaf.feature_agent import PointInTimeFeatureAgent


class Bus:
    def __init__(self, redis):
        self.redis = redis


@pytest.mark.asyncio
async def test_redis_cycle_produces_reproducible_frozen_features(tmp_path):
    url = os.environ.get("OAF_TEST_REDIS_URL")
    if not url:
        pytest.skip("OAF_TEST_REDIS_URL not configured")
    from redis.asyncio import Redis

    redis = Redis.from_url(url)
    cid = uuid4()
    try:
        times = pd.date_range("2022-12-20T00:00Z", periods=5, freq="h")
        observations = pd.DataFrame({
            "timestamp_utc": times, "ba": ["PJM"] * 5,
            "demand_mwh": [100000., 101000., 102000., 103000., 104000.],
            "forecast_mwh": [99000., 99500., 100000., 100500., 101000.],
            "interchange_mwh": [1000., 1200., 1400., 1600., 1800.],
        })
        baseline = pd.DataFrame({
            "hour_of_day": list(range(5)), "month": [12] * 5,
            "demand_mean": [90000.] * 5, "demand_std": [5000.] * 5,
            "fe_mean": [0.] * 5, "fe_std": [2.] * 5,
            "ramp3_mean": [0.] * 5, "ramp3_std": [500.] * 5,
            "ic_mean": [0.] * 5, "ic_std": [1000.] * 5,
        })
        baseline_path = tmp_path / "baseline.parquet"
        baseline.to_parquet(baseline_path, index=False)

        coordinator = object.__new__(AcquisitionCoordinatorAgent)
        coordinator.name = "grid-acquisition-coordinator"
        cycle = EventEnvelope(
            event_type=CYCLE_REQUESTED, source_agent="test",
            correlation_id=cid,
            payload={"ba": "PJM", "as_of": "2022-12-20T06:00Z",
                     "lookback_hours": 5, "publication_lag_hours": 2},
        )
        eia_request, dispatch = await coordinator.handle_event(cycle)

        eia = object.__new__(EIA930AcquisitionAgent)
        eia.name = "grid-eia930"
        eia.output_dir = tmp_path / "eia"
        eia.fetcher = lambda ba, start, end: observations.copy()
        fetched = (await eia.handle_event(eia_request))[0]
        from gridregime.oaf.eia_revision_ledger import list_versions, assert_point_in_time_eligible
        versions = list_versions(
            ledger_dir=eia.output_dir / "revisions", ba="PJM",
            start="2022-12-20T00:00:00+00:00",
            end="2022-12-20T04:00:00+00:00",
        )
        assert len(versions) == 1
        assert versions[0]["sha256"] == fetched.payload["sha256"]
        with pytest.raises(ValueError, match="publication time is unverified"):
            assert_point_in_time_eligible(versions[0], "2022-12-20T06:00:00Z")

        assessed = assess_eia_artifact(
            artifact_path=fetched.payload["artifact_path"],
            end=fetched.payload["end"], ba="PJM",
            checked_at="2022-12-20T06:00Z",
        )
        status_agent = object.__new__(AcquisitionCycleStatusAgent)
        status_agent.name = "grid-acquisition-status"
        status_agent.event_bus = Bus(redis)
        await status_agent.handle_event(dispatch)
        status = (await status_agent.handle_event(EventEnvelope(
            event_type=ASSESSED, source_agent="test", correlation_id=cid,
            payload=assessed,
        )))[0]
        assert status.payload["status"] == "observation-ready-publication-unverified"
        assert not status.payload["ready_for_predictive_inference"]

        bridge = object.__new__(AcquisitionFeatureBridgeAgent)
        bridge.name = "grid-acquisition-feature-bridge"
        bridge.baseline_path = baseline_path
        bridge.event_bus = Bus(redis)
        assert await bridge.handle_event(dispatch) == []
        assert await bridge.handle_event(fetched) == []
        feature_request = (await bridge.handle_event(status))[0]

        feature_agent = object.__new__(PointInTimeFeatureAgent)
        feature_agent.name = "grid-features"
        feature_agent.baseline_path = baseline_path
        feature_agent.output_dir = tmp_path / "features"
        computed = (await feature_agent.handle_event(feature_request))[0]
        assert computed.payload["feature_version"] == "frozen-v1"
        assert computed.payload["decision_as_of"] == "2022-12-20T06:00:00+00:00"
        assert computed.payload["as_of"] == "2022-12-20T04:00:00+00:00"
        assert set(computed.payload["features"]) == {"load_z", "fe_z", "ramp3_z", "ic_z"}
        assert computed.payload["status"] == "features-only-not-a-risk-prediction"
        replay = (await feature_agent.handle_event(feature_request))[0]
        assert replay.payload["sha256"] == computed.payload["sha256"]
    finally:
        await redis.delete(f"grid:cycle:evidence:{cid}",
                           f"grid:cycle:feature-bridge:{cid}")
        await redis.aclose()
