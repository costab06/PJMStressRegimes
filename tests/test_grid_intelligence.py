"""Synthetic evidence and response-contract tests; no local model required."""
import json

import pandas as pd
import pytest

from gridregime.grid_intelligence import build_evidence
from gridregime.grid_interpretation_agent import validate_interpretation, render_report


def sample():
    return pd.DataFrame({
        "timestamp_utc": pd.date_range("2026-07-01", periods=72, freq="h", tz="UTC"),
        "demand_mwh": [100000 + i * 100 + (5000 if i >= 60 else 0) for i in range(72)],
        "forecast_mwh": [100000 + i * 100 for i in range(72)],
        "interchange_mwh": [1000 + i * 20 for i in range(72)],
    })


def test_evidence_has_stable_ids_and_comparison():
    e = build_evidence(sample())
    assert [o["id"] for o in e["observations"]] == ["E1", "E2", "E3", "E4", "E5"]
    assert e["observations"][1]["high_demand_pct"] > e["observations"][1]["other_hours_pct"]
    assert e["observations"][3]["increase_mwh"] == 5100


def test_rejects_too_few_hours():
    with pytest.raises(ValueError, match="48"):
        build_evidence(sample().iloc[:24])


def valid_response():
    return {"summary": "The observations warrant further investigation.",
            "findings": [{
                "title": "Forecast accuracy during elevated demand",
                "interpretation": "Forecast errors appear different across demand conditions; the cause remains uncertain.",
                "evidence_ids": ["E1", "E2"],
                "alternative_explanations": ["Time of day effects"],
                "additional_evidence_needed": ["Weather and calendar context"],
            }]}


def test_report_and_contract():
    e = build_evidence(sample())
    response = validate_interpretation(json.dumps(valid_response()), e)
    report = render_report(e, response, "local-model")
    assert "E2" in report and "grid_evidence.json" in report


@pytest.mark.parametrize("mutation", [
    lambda d: d["findings"][0].update(evidence_ids=["E99"]),
    lambda d: d["findings"][0].update(interpretation="The outage was caused by 30% growth"),
    lambda d: d.update(summary="This proves the grid was unsafe"),
])
def test_rejects_unsupported_claims(mutation):
    e = build_evidence(sample())
    response = valid_response()
    mutation(response)
    with pytest.raises(ValueError):
        validate_interpretation(json.dumps(response), e)
