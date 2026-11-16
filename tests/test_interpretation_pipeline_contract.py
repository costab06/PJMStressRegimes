"""End-to-end interpretation contract test using deterministic PJM evidence.

No LLM service is required: this replays representative structured LLM output
through the same verifier and publication gate used by an eventual live runner.
"""
from copy import deepcopy

import pytest

from gridregime.interpretation_verification import audit_interpretation, publish_reviewed


@pytest.fixture
def pjm_evidence():
    return [
        {"id": "E2H", "metric": "mae_percent", "value": 3.3846, "unit": "percent", "population": "high_demand"},
        {"id": "E2O", "metric": "mae_percent", "value": 4.2445, "unit": "percent", "population": "other_hours"},
        {"id": "E6H", "metric": "mae_absolute", "value": 5091.413, "unit": "MWh", "population": "high_demand"},
        {"id": "E6O", "metric": "mae_absolute", "value": 4485.795, "unit": "MWh", "population": "other_hours"},
        {"id": "E3H", "metric": "signed_bias_percent", "value": -0.9647, "unit": "percent", "population": "high_demand"},
        {"id": "E5", "metric": "pearson_r", "value": -0.1338, "unit": "ratio", "population": "all_hours"},
    ]


def fact(cid, text, ids, assertion):
    return {
        "id": cid, "type": "observed_fact", "text": text,
        "evidence_ids": ids,
        "evidence_roles": {i: "establishes_fact" for i in ids},
        "assertion": assertion,
    }


def test_replayed_llm_output_requires_review_and_rejects_numeric_errors(pjm_evidence):
    """The authoritative output must never copy the raw LLM report verbatim."""
    claims = [
        fact("C_pct_correct", "High demand has lower percentage MAE.", ["E2H", "E2O"],
             {"kind": "comparison", "left": "E2H", "right": "E2O", "operator": "lt"}),
        fact("C_abs_wrong", "High demand has lower absolute MAE.", ["E6H", "E6O"],
             {"kind": "comparison", "left": "E6H", "right": "E6O", "operator": "lt"}),
        fact("C_bias_wrong", "High demand has positive signed forecast bias.", ["E3H"],
             {"kind": "value", "evidence_id": "E3H", "metric": "signed_bias_percent",
              "unit": "percent", "value": 0.9647}),
        fact("C_abs_correct", "High demand has higher absolute MAE.", ["E6H", "E6O"],
             {"kind": "comparison", "left": "E6H", "right": "E6O", "operator": "gt"}),
        {
            "id": "C_significance", "type": "interpretation",
            "text": "Correlation is not statistically significant.",
            "evidence_ids": ["E5"], "evidence_roles": {"E5": "establishes_fact"},
            "assertion": {"kind": "value", "evidence_id": "E5", "metric": "pearson_r",
                          "unit": "ratio", "value": -0.1338},
        },
    ]
    llm_output = {"evidence": pjm_evidence, "claims": claims}
    original = deepcopy(llm_output)
    audit = audit_interpretation(llm_output)
    statuses = {a["id"]: a for a in audit["audits"]}
    assert statuses["C_abs_wrong"]["status"] == "rejected"
    assert statuses["C_bias_wrong"]["status"] == "rejected"
    assert statuses["C_pct_correct"]["status"] == "review_required"
    assert statuses["C_abs_correct"]["status"] == "review_required"
    assert statuses["C_significance"]["status"] == "review_required"
    assert "interpretation_requires_independent_review" in statuses["C_significance"]["issues"]
    assert audit["publication"] == []
    assert llm_output == original

    # Simulate explicit reviewer approval of ONLY the two numerically consistent facts.
    published = publish_reviewed(audit, {"C_pct_correct", "C_abs_correct"})
    assert {c["id"] for c in published["publication"]} == {"C_pct_correct", "C_abs_correct"}
    assert all("significant" not in c["text"] for c in published["publication"])
    assert published["source"] == original
    with pytest.raises(ValueError, match="rejected"):
        publish_reviewed(audit, {"C_abs_wrong"})


def test_context_only_or_uncited_fact_cannot_be_published(pjm_evidence):
    claim = fact("C_context", "The correlation proves causality.", ["E5"],
                 {"kind": "value", "evidence_id": "E5", "metric": "pearson_r",
                  "unit": "ratio", "value": -0.1338})
    claim["evidence_roles"]["E5"] = "context_only"
    audit = audit_interpretation({"evidence": pjm_evidence, "claims": [claim]})
    assert audit["audits"][0]["status"] == "rejected"
    with pytest.raises(ValueError, match="rejected"):
        publish_reviewed(audit, {"C_context"})
