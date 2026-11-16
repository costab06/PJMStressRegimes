"""Bounded hypothesis investigations and local-model selection contracts."""
import json
import pandas as pd
import pytest
from gridregime.grid_investigation import investigate
from gridregime.grid_interpretation_agent import validate_hypothesis, validate_followup, render_investigation


def sample():
    return pd.DataFrame({
        "timestamp_utc": pd.date_range("2026-07-01", periods=240, freq="h", tz="UTC"),
        "demand_mwh": [100000 + 1000 * (i % 24) + (12000 if i >= 192 else 0) for i in range(240)],
        "forecast_mwh": [101000 + 1000 * (i % 24) for i in range(240)],
        "interchange_mwh": [1000 + (i % 24) * 30 for i in range(240)],
    })


def test_forecast_investigation():
    result = investigate(sample(), "forecast_accuracy")
    assert result["high_n"] > 0
    assert result["hour_matched"]["eligible_hours"] > 0
    assert result["overall"]["high_mean_absolute_mwh"] >= 0


def test_ramp_investigation():
    result = investigate(sample(), "ramp_interchange")
    assert result["paired_hours"] == 239
    assert result["pearson_r"] is not None


def test_reject_unknown_tool():
    with pytest.raises(ValueError, match="Unsupported"):
        investigate(sample(), "python_eval")


def test_selection_and_followup_contracts():
    h = validate_hypothesis(json.dumps({"question": "forecast_accuracy", "reason": "Test the contrast"}))
    f = validate_followup(json.dumps({
        "assessment": "The pattern remains uncertain",
        "supporting_evidence": "Matched comparisons help",
        "remaining_uncertainty": "Weather may confound",
        "next_data_needed": "Temperature observations",
    }))
    report = render_investigation(h, investigate(sample(), h["question"]), f)
    assert "Hypothesis and follow-up" in report
    assert "\\n" not in report


def test_reject_unknown_selection():
    with pytest.raises(ValueError):
        validate_hypothesis(json.dumps({"question": "arbitrary_code", "reason": "No"}))


def test_missing_followup_is_marked_incomplete():
    response = {
        "assessment": "Insufficient evidence",
        "supporting_evidence": "",
        "remaining_uncertainty": None,
        "next_data_needed": "Weather",
    }
    result = validate_followup(json.dumps(response))
    assert result["incomplete"] is True
    assert "requires review" in result["supporting_evidence"]
    assert "requires review" in result["remaining_uncertainty"]


def test_invalid_followup_type_still_rejected():
    response = {
        "assessment": ["invalid"],
        "supporting_evidence": "Evidence",
        "remaining_uncertainty": "Uncertain",
        "next_data_needed": "Weather",
    }
    with pytest.raises(ValueError, match="field type"):
        validate_followup(json.dumps(response))
