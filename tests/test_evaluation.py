"""Tests for evaluation modules."""

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def scores():
    idx = pd.date_range("2022-12-20", periods=24 * 10, freq="h", tz="UTC")
    rng = np.random.default_rng(2)
    vals = rng.uniform(0, 1, len(idx))
    # Inflate scores during event
    event_mask = (idx >= pd.Timestamp("2022-12-23", tz="UTC")) & \
                 (idx <= pd.Timestamp("2022-12-26", tz="UTC"))
    vals[event_mask] *= 1.5
    return pd.Series(vals.clip(0, 1), index=idx)


def test_false_alarm_rate_no_alarms(scores):
    from gridregime.evaluation.false_alarms import false_alarm_rate
    zero_scores = pd.Series(0.0, index=scores.index)
    result = false_alarm_rate(zero_scores, [("2022-12-23", "2022-12-26")])
    assert result["n_false_alarms"] == 0


def test_false_alarm_rate_keys(scores):
    from gridregime.evaluation.false_alarms import false_alarm_rate
    result = false_alarm_rate(scores, [("2022-12-23", "2022-12-26")])
    assert set(result.keys()) == {"n_true_events", "n_detected", "n_false_alarms", "false_alarm_rate"}
