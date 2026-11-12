"""Point-in-time feature adapter regression tests."""
import json

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from gridregime.features.seasonal import apply_zscore
from gridregime.oaf.feature_agent import compute_point_in_time_features


def inputs(tmp_path):
    ts = pd.date_range("2022-12-20T00:00Z", periods=5, freq="h")
    frame = pd.DataFrame({
        "timestamp_utc": ts, "ba": ["PJM"] * 5,
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
    src, base = tmp_path / "source.csv", tmp_path / "baseline.parquet"
    frame.to_csv(src, index=False)
    baseline.to_parquet(base, index=False)
    return frame, baseline, src, base


def compute(tmp_path, src, base, as_of="2022-12-20T04"):
    return compute_point_in_time_features(
        source_path=src, baseline_path=base, as_of=as_of,
        ba="PJM", output_dir=tmp_path / "features",
    )


def test_feature_parity_and_replay(tmp_path):
    frame, baseline, src, base = inputs(tmp_path)
    result = compute(tmp_path, src, base)
    reference = frame.copy()
    reference["t"] = np.arange(-4, 1, dtype=float)
    expected = apply_zscore(reference, baseline).iloc[-1]
    for key in ("load_z", "fe_z", "ramp3_z", "ic_z"):
        assert result["features"][key] == pytest.approx(expected[key])
    assert result["status"] == "features-only-not-a-risk-prediction"
    assert json.loads((tmp_path / "features" / f"features-{result['sha256']}.json").read_text())["features"] == result["features"]
    assert compute(tmp_path, src, base)["sha256"] == result["sha256"]


def test_reject_future_data(tmp_path):
    frame, _, src, base = inputs(tmp_path)
    with pytest.raises(ValueError, match="Future observations"):
        compute(tmp_path, src, base, "2022-12-20T03")


def test_reject_missing_hour(tmp_path):
    frame, _, src, base = inputs(tmp_path)
    frame.drop(index=3).to_csv(src, index=False)
    with pytest.raises(ValueError, match="four-hour"):
        compute(tmp_path, src, base)


def test_reject_nonfinite_baseline(tmp_path):
    _, baseline, src, base = inputs(tmp_path)
    baseline.loc[4, "demand_std"] = 0
    baseline.to_parquet(base, index=False)
    with pytest.raises(ValueError, match="non-finite"):
        compute(tmp_path, src, base)


def test_reject_duplicate_timestamp(tmp_path):
    frame, _, src, base = inputs(tmp_path)
    pd.concat([frame, frame.iloc[-1:]]).to_csv(src, index=False)
    with pytest.raises(ValueError, match="Duplicate"):
        compute(tmp_path, src, base)


def test_decision_time_is_distinct_from_observation_end(tmp_path):
    _, _, src, base = inputs(tmp_path)
    result = compute_point_in_time_features(
        source_path=src, baseline_path=base,
        as_of="2022-12-20T04:00Z",
        decision_as_of="2022-12-20T06:00Z",
        ba="PJM", output_dir=tmp_path / "features",
    )
    assert result["as_of"] == "2022-12-20T04:00:00+00:00"
    assert result["decision_as_of"] == "2022-12-20T06:00:00+00:00"
    with pytest.raises(ValueError, match="decision_as_of"):
        compute_point_in_time_features(
            source_path=src, baseline_path=base,
            as_of="2022-12-20T04:00Z",
            decision_as_of="2022-12-20T03:00Z",
            ba="PJM", output_dir=tmp_path / "features",
        )


@pytest.mark.asyncio
async def test_feature_agent_rejects_changed_pinned_baseline(tmp_path):
    import hashlib
    from uuid import uuid4
    from shared.eventbus.events import EventEnvelope
    from gridregime.oaf.feature_agent import PointInTimeFeatureAgent, REQUESTED

    _, _, src, baseline = inputs(tmp_path)
    agent = object.__new__(PointInTimeFeatureAgent)
    agent.name = "grid-features"
    agent.baseline_path = baseline
    agent.output_dir = tmp_path / "features"
    event = EventEnvelope(
        event_type=REQUESTED, source_agent="test", correlation_id=uuid4(),
        payload={
            "artifact_path": str(src), "as_of": "2022-12-20T04:00Z",
            "decision_as_of": "2022-12-20T06:00Z", "ba": "PJM",
            "source_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
            "baseline_sha256": "0" * 64,
        },
    )
    with pytest.raises(ValueError, match="Frozen baseline checksum mismatch"):
        await agent.handle_event(event)


@pytest.mark.asyncio
async def test_feature_agent_rejects_changed_pinned_source(tmp_path):
    import hashlib
    from uuid import uuid4
    from shared.eventbus.events import EventEnvelope
    from gridregime.oaf.feature_agent import PointInTimeFeatureAgent, REQUESTED

    _, _, src, baseline = inputs(tmp_path)
    agent = object.__new__(PointInTimeFeatureAgent)
    agent.name = "grid-features"
    agent.baseline_path = baseline
    agent.output_dir = tmp_path / "features"
    event = EventEnvelope(
        event_type=REQUESTED, source_agent="test", correlation_id=uuid4(),
        payload={
            "artifact_path": str(src), "as_of": "2022-12-20T04:00Z",
            "ba": "PJM", "source_sha256": "0" * 64,
            "baseline_sha256": hashlib.sha256(baseline.read_bytes()).hexdigest(),
        },
    )
    with pytest.raises(ValueError, match="Source artifact checksum mismatch"):
        await agent.handle_event(event)


@pytest.mark.asyncio
async def test_feature_agent_requires_pinned_hashes_and_matching_baseline(tmp_path):
    import hashlib
    from uuid import uuid4
    from shared.eventbus.events import EventEnvelope
    from gridregime.oaf.feature_agent import PointInTimeFeatureAgent, REQUESTED

    _, _, src, baseline = inputs(tmp_path)
    agent = object.__new__(PointInTimeFeatureAgent)
    agent.name = "grid-features"
    agent.baseline_path = baseline
    agent.output_dir = tmp_path / "features"
    payload = {
        "artifact_path": str(src), "as_of": "2022-12-20T04:00Z",
        "ba": "PJM",
    }
    def event(data):
        return EventEnvelope(event_type=REQUESTED, source_agent="test",
                             correlation_id=uuid4(), payload=data)
    with pytest.raises(ValueError, match="requires pinned"):
        await agent.handle_event(event(payload))
    pinned = {
        **payload,
        "source_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
        "baseline_sha256": hashlib.sha256(baseline.read_bytes()).hexdigest(),
        "baseline_path": str(tmp_path / "different.parquet"),
    }
    with pytest.raises(ValueError, match="baseline path differs"):
        await agent.handle_event(event(pinned))
    pinned["baseline_path"] = str(baseline)
    computed = await agent.handle_event(event(pinned))
    assert len(computed) == 1
