import pytest

from gridregime.interpretation_verification import audit_interpretation, publish_reviewed


def evidence():
    return [
        {"id": "E_PCT_HIGH", "metric": "absolute_forecast_error_pct", "value": 3.3846, "unit": "percent", "population": "high"},
        {"id": "E_PCT_OTHER", "metric": "absolute_forecast_error_pct", "value": 4.2445, "unit": "percent", "population": "other"},
        {"id": "E_MWH_HIGH", "metric": "absolute_forecast_error_mwh", "value": 5091.413, "unit": "MWh", "population": "high"},
        {"id": "E_MWH_OTHER", "metric": "absolute_forecast_error_mwh", "value": 4485.795, "unit": "MWh", "population": "other"},
        {"id": "E_BIAS_HIGH", "metric": "signed_forecast_bias_pct", "value": -0.9647, "unit": "percent", "population": "high"},
    ]


def claim(left, right, operator="lt", kind="observed_fact"):
    return {"id": "C1", "type": kind, "text": "A comparison",
            "evidence_ids": [left, right],
            "evidence_roles": {left: "establishes_fact", right: "establishes_fact"},
            "assertion": {"kind": "comparison", "left": left, "right": right, "operator": operator}}


def check(c):
    return audit_interpretation({"evidence": evidence(), "claims": [c]})


def test_correct_percentage_comparison_is_not_disproven():
    a = check(claim("E_PCT_HIGH", "E_PCT_OTHER"))
    assert a["audits"][0]["status"] == "review_required"
    assert a["publication"] == []


def test_inverted_absolute_error_is_rejected():
    a = check(claim("E_MWH_HIGH", "E_MWH_OTHER"))
    assert "comparison_contradicted" in a["audits"][0]["issues"]
    with pytest.raises(ValueError, match="rejected"):
        publish_reviewed(a, {"C1"})


def test_correct_absolute_error_comparison():
    a = check(claim("E_MWH_HIGH", "E_MWH_OTHER", "gt"))
    assert a["audits"][0]["numeric_check"] == "not_disproven"


def test_metric_and_unit_mismatch():
    a = check(claim("E_PCT_HIGH", "E_MWH_OTHER"))
    assert "incompatible_metrics_or_units" in a["audits"][0]["issues"]


def test_sign_value_check_rejects_reversal():
    c = {"id": "C1", "type": "observed_fact", "text": "High-demand bias positive",
         "evidence_ids": ["E_BIAS_HIGH"],
         "evidence_roles": {"E_BIAS_HIGH": "establishes_fact"},
         "assertion": {"kind": "value", "evidence_id": "E_BIAS_HIGH",
                       "metric": "signed_forecast_bias_pct", "unit": "percent", "value": 0.9647}}
    assert "value_contradicted" in check(c)["audits"][0]["issues"]


def test_context_only_cannot_establish_fact():
    c = claim("E_PCT_HIGH", "E_PCT_OTHER")
    c["evidence_roles"] = {i: "context_only" for i in c["evidence_ids"]}
    assert "no_fact_establishing_evidence" in check(c)["audits"][0]["issues"]


def test_prediction_not_verified_by_history():
    a = check(claim("E_PCT_HIGH", "E_PCT_OTHER", kind="prediction"))
    assert "prediction_not_established_by_historical_evidence" in a["audits"][0]["issues"]
    assert a["audits"][0]["status"] == "review_required"


def test_publication_requires_explicit_approval():
    a = check(claim("E_PCT_HIGH", "E_PCT_OTHER"))
    assert a["publication"] == []
    approved = publish_reviewed(a, {"C1"})
    assert len(approved["publication"]) == 1
    assert a["publication"] == []


def test_duplicate_evidence_id_fails_closed():
    with pytest.raises(ValueError, match="duplicate_evidence"):
        audit_interpretation({"evidence": evidence() + [evidence()[0]], "claims": []})
