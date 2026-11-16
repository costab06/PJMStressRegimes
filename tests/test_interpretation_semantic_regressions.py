"""Regression tests derived from the first real qwen3:8b PJM audit."""
from gridregime.interpretation_live import DEMO_EVIDENCE
from gridregime.interpretation_verification import audit_interpretation, publish_reviewed


def claim(cid, text, evidence_ids, assertion, kind="observed_fact"):
    return {
        "id": cid, "text": text, "type": kind,
        "evidence_ids": evidence_ids,
        "evidence_roles": {i: "establishes_fact" for i in evidence_ids},
        "assertion": assertion,
    }


def correlation(text):
    return claim("C_CORRELATION", text, ["E_CORRELATION"],
                 {"kind": "value", "evidence_id": "E_CORRELATION",
                  "metric": "pearson_r", "unit": "ratio", "value": -0.1338})


def compound(assertion):
    return claim(
        "C_ABS_PCT_DISCREPANCY",
        "High-demand hours exhibit lower percentage error but higher absolute error compared to other hours.",
        ["E_PCT_HIGH", "E_PCT_OTHER", "E_ABS_HIGH", "E_ABS_OTHER"],
        assertion, kind="interpretation",
    )


def comparison(left, right, operator):
    return {"kind": "comparison", "left": left, "right": right, "operator": operator}


def audit(*claims):
    return audit_interpretation({"evidence": DEMO_EVIDENCE, "claims": list(claims)})


def test_original_live_correlation_misidentification_is_rejected():
    result = audit(correlation(
        "The Pearson correlation coefficient between forecast and actual values is -0.1338."
    ))
    record = result["audits"][0]
    assert record["status"] == "rejected"
    assert "correlation_variable_mismatch" in record["issues"]
    try:
        publish_reviewed(result, {"C_CORRELATION"})
    except ValueError as exc:
        assert "rejected" in str(exc)
    else:
        raise AssertionError("Incorrect metric identity was published")


def test_correct_correlation_variables_still_require_review():
    result = audit(correlation(
        "The Pearson correlation between hourly demand change and interchange level is -0.1338."
    ))
    assert result["audits"][0]["status"] == "review_required"


def test_significance_claim_rejected_without_statistical_test():
    result = audit(correlation(
        "The correlation between demand change and interchange level is not statistically significant."
    ))
    assert "significance_requires_statistical_test" in result["audits"][0]["issues"]
    assert result["audits"][0]["status"] == "rejected"


def test_original_compound_claim_with_one_assertion_is_rejected():
    result = audit(compound(comparison("E_PCT_HIGH", "E_PCT_OTHER", "lt")))
    assert "compound_claim_missing_assertions" in result["audits"][0]["issues"]
    assert result["audits"][0]["status"] == "rejected"


def test_compound_claim_requires_both_correct_comparisons():
    good = {"kind": "all", "assertions": [
        comparison("E_PCT_HIGH", "E_PCT_OTHER", "lt"),
        comparison("E_ABS_HIGH", "E_ABS_OTHER", "gt"),
    ]}
    result = audit(compound(good))
    assert result["audits"][0]["status"] == "review_required"
    assert result["publication"] == []
    bad = {"kind": "all", "assertions": [
        comparison("E_PCT_HIGH", "E_PCT_OTHER", "lt"),
        comparison("E_ABS_HIGH", "E_ABS_OTHER", "lt"),
    ]}
    result = audit(compound(bad))
    assert result["audits"][0]["status"] == "rejected"
    assert "comparison_contradicted" in result["audits"][0]["issues"]
