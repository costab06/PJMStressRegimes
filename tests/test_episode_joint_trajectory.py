import numpy as np
import pandas as pd
import pytest

from gridregime.episode_joint_trajectory import compare_episodes


def fixture():
    times = pd.date_range("2022-12-22T22:00:00Z", periods=24, freq="h")
    data = pd.DataFrame({
        "timestamp_utc": times, "episode_id": "ELL_2022", "severity": "S3",
        "load_z": np.full(24, 3.0), "fe_z": np.full(24, 4.0),
        "ramp3_z": np.zeros(24), "ic_z": np.zeros(24),
    })
    events = pd.DataFrame([{
        "episode_id": "ELL_2022", "severity": "S3",
        "operator_action_time": "2022-12-23T22:30:00Z",
        "first_alert_time": "", "window_start": "2022-12-20T00:00:00Z",
    }])
    return data, events


def test_joint_l2_and_persistence():
    data, events = fixture()
    row = compare_episodes(data, events).iloc[0]
    assert row["status"] == "complete"
    assert row["joint_peak"] == 5.0
    assert row["joint_hours_above_threshold"] == 24
    assert row["joint_longest_run_hours"] == 24
    assert row["joint_delta"] == 0.0


def test_missing_hour_is_not_interpolated():
    data, events = fixture()
    row = compare_episodes(data.drop(index=5), events).iloc[0]
    assert row["status"] == "incomplete"
    assert row["complete_hours"] == 23


def test_duplicate_episode_hour_rejected():
    data, events = fixture()
    with pytest.raises(ValueError, match="duplicate_episode_timestamp"):
        compare_episodes(pd.concat([data, data.iloc[:1]]), events)


def test_missing_anchor_remains_missing():
    data, events = fixture()
    events.loc[0, "operator_action_time"] = ""
    row = compare_episodes(data, events).iloc[0]
    assert row["status"] == "missing_anchor"


def test_severity_mismatch_rejected():
    data, events = fixture()
    data["severity"] = "S2"
    with pytest.raises(ValueError, match="severity_mismatch"):
        compare_episodes(data, events)
