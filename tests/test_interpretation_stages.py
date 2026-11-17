"""Stage separation and fixed regressions from the two live qwen3:8b runs."""
from gridregime.interpretation_live import DEMO_EVIDENCE
from gridregime.interpretation_verification import audit_interpretation
from gridregime.interpretation_stages import (
    verify_numerical_assertion, verify_evidence_identity, verify_prose_consistency,
)


def _claim(text, ids, assertion):
    return {
        "id": "C", "type": "interpretation", "text": text,
        "evidence_ids": ids,
        "evidence_roles": {i: "establishes_fact" for i in ids},
        "assertion": assertion,
    }


def _audit(claim):
    return audit_interpretation({"evidence": DEMO_EVIDENCE, "claims": [claim]})["audits"][0]


def test_stage_numeric_contradiction_is_independent_of_prose():
    claim = _claim(
        "High demand absolute error is lower", ["E_ABS_HIGH", "E_ABS_OTHER"],
        {"kind": "comparison", "left": "E_ABS_HIGH", "right": "E_ABS_OTHER", "operator": "lt"},
    )
    result = _audit(claim)
    assert "comparison_contradicted" in result["stages"]["numerical"]
    assert result["status"] == "rejected"


def test_stage_evidence_identity_catches_first_live_run():
    claim = _claim(
        "The Pearson correlation between forecast and actual values is -0.1338.",
        ["E_CORRELATION"],
        {"kind": "value", "evidence_id": "E_CORRELATION",
         "metric": "pearson_r", "unit": "ratio", "value": -0.1338},
    )
    result = _audit(claim)
    assert result["stages"]["numerical"] == []
    assert "correlation_variable_mismatch" in result["stages"]["evidence_identity"]
    assert result["status"] == "rejected"


def test_stage_prose_consistency_catches_second_live_run():
    claim = _claim(
        "The mean absolute error (MAE) is lower during high demand compared to other hours.",
        ["E_PCT_HIGH", "E_PCT_OTHER"],
        {"kind": "comparison", "left": "E_PCT_HIGH",
         "right": "E_PCT_OTHER", "operator": "lt"},
    )
    result = _audit(claim)
    assert result["stages"]["numerical"] == []
    assert "prose_metric_identity_mismatch" in result["stages"]["prose_consistency"]
    assert result["status"] == "rejected"


def test_valid_correlation_still_requires_review():
    claim = _claim(
        "The Pearson correlation between hourly demand change and interchange level is -0.1338.",
        ["E_CORRELATION"],
        {"kind": "value", "evidence_id": "E_CORRELATION",
         "metric": "pearson_r", "unit": "ratio", "value": -0.1338},
    )
    result = _audit(claim)
    assert all(not issues for issues in result["stages"].values())
    assert result["status"] == "review_required"


def test_compound_assertions_are_numerically_checked_individually():
    ids = ["E_PCT_HIGH", "E_PCT_OTHER", "E_ABS_HIGH", "E_ABS_OTHER"]
    claim = _claim(
        "High demand has lower percentage error but higher absolute error.",
        ids, {"kind": "all", "assertions": [
            {"kind": "comparison", "left": "E_PCT_HIGH", "right": "E_PCT_OTHER", "operator": "lt"},
            {"kind": "comparison", "left": "E_ABS_HIGH", "right": "E_ABS_OTHER", "operator": "gt"},
        ]},
    )
    result = _audit(claim)
    assert all(not issues for issues in result["stages"].values())
    assert result["status"] == "review_required"
