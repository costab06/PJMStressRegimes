"""Offline semantic-review contract and fixed-error benchmark.

No Ollama needed; injected reviewer exercises all verdict and safety paths.
"""
import json

import pytest

from gridregime.interpretation_live import DEMO_EVIDENCE, run_experiment
from gridregime.interpretation_verification import audit_interpretation, publish_reviewed
from gridregime.interpretation_semantic_review import parse_review, review_audit


def claim(cid, text, ids, assertion):
    return {
        "id": cid, "type": "interpretation", "text": text,
        "evidence_ids": ids,
        "evidence_roles": {i: "establishes_fact" for i in ids},
        "assertion": assertion,
    }


def compare(left, right, operator):
    return {"kind": "comparison", "left": left, "right": right, "operator": operator}


def audit(*claims):
    return audit_interpretation({"evidence": DEMO_EVIDENCE, "claims": list(claims)})


def response(verdict, ids, reason="reviewed"):
    return json.dumps({"verdict": verdict, "reason": reason, "cited_evidence_ids": ids})


def test_reviewer_cannot_override_deterministic_rejection():
    bad = claim("bad", "Absolute MAE is lower during high demand.",
                ["E_ABS_HIGH", "E_ABS_OTHER"],
                compare("E_ABS_HIGH", "E_ABS_OTHER", "lt"))
    calls = []
    reviewed = review_audit(audit(bad), reviewer=lambda *args: calls.append(args))
    item = reviewed["audits"][0]
    assert item["status"] == "rejected"
    assert item["semantic_review"]["verdict"] == "not_run"
    assert not calls
    with pytest.raises(ValueError, match="rejected"):
        publish_reviewed(reviewed, {"bad"})


def test_reviewer_support_does_not_publish_or_change_status():
    good = claim("good", "High demand has higher absolute MAE.",
                 ["E_ABS_HIGH", "E_ABS_OTHER"],
                 compare("E_ABS_HIGH", "E_ABS_OTHER", "gt"))
    reviewed = review_audit(audit(good), reviewer=lambda c, e:
                            response("supported", [x["id"] for x in e]))
    item = reviewed["audits"][0]
    assert item["semantic_review"]["verdict"] == "supported"
    assert item["status"] == "review_required"
    assert reviewed["publication"] == []


def test_reviewer_detects_unrecognized_semantic_error_as_advice():
    # Numerical assertion is consistent, but prose uses the wrong variable pair.
    wrong = claim("wrong", "The correlation describes forecast and actual values.",
                  ["E_CORRELATION"],
                  {"kind": "value", "evidence_id": "E_CORRELATION",
                   "metric": "pearson_r", "unit": "ratio", "value": -0.1338})
    reviewed = review_audit(audit(wrong), reviewer=lambda c, e:
                            response("unsupported", ["E_CORRELATION"], "wrong variables"))
    assert reviewed["audits"][0]["semantic_review"]["verdict"] == "unsupported"
    assert reviewed["audits"][0]["status"] == "review_required"
    assert reviewed["publication"] == []


def test_invalid_or_uncited_reviewer_response_fails_closed():
    good = claim("good", "Higher absolute MAE.",
                 ["E_ABS_HIGH", "E_ABS_OTHER"],
                 compare("E_ABS_HIGH", "E_ABS_OTHER", "gt"))
    reviewed = review_audit(audit(good), reviewer=lambda c, e:
                            response("supported", ["INVENTED"]))
    assert reviewed["audits"][0]["semantic_review"]["verdict"] == "error"
    assert reviewed["publication"] == []
    with pytest.raises(ValueError, match="supported_review_requires_citation"):
        parse_review(response("supported", []), {"E_ABS_HIGH"})


def test_reviewer_failure_does_not_erase_deterministic_results():
    good = claim("good", "Higher absolute MAE.",
                 ["E_ABS_HIGH", "E_ABS_OTHER"],
                 compare("E_ABS_HIGH", "E_ABS_OTHER", "gt"))
    def unavailable(*args):
        raise OSError("Ollama offline")
    reviewed = review_audit(audit(good), reviewer=unavailable)
    assert reviewed["audits"][0]["status"] == "review_required"
    assert reviewed["audits"][0]["semantic_review"]["verdict"] == "error"


def test_live_runner_writes_advisory_review_without_publication(tmp_path):
    good = claim("good", "Higher absolute MAE.",
                 ["E_ABS_HIGH", "E_ABS_OTHER"],
                 compare("E_ABS_HIGH", "E_ABS_OTHER", "gt"))
    report = run_experiment(
        tmp_path, raw_response=json.dumps({"claims": [good]}),
        semantic_review=True,
        reviewer=lambda c, e: response("supported", [x["id"] for x in e]),
    )
    assert report["semantic_counts"]["supported"] == 1
    assert report["published"] == 0
    saved = json.loads((tmp_path / "claim_audit.json").read_text())
    assert saved["publication"] == []


def test_fixed_regression_benchmark_counts_deterministic_rejections():
    examples = [
        claim("wrong_direction", "High demand absolute MAE is lower.",
              ["E_ABS_HIGH", "E_ABS_OTHER"],
              compare("E_ABS_HIGH", "E_ABS_OTHER", "lt")),
        claim("wrong_metric", "Mean absolute error is lower in high demand.",
              ["E_PCT_HIGH", "E_PCT_OTHER"],
              compare("E_PCT_HIGH", "E_PCT_OTHER", "lt")),
        claim("wrong_correlation", "Pearson correlation between forecast and actual is -0.1338.",
              ["E_CORRELATION"],
              {"kind": "value", "evidence_id": "E_CORRELATION",
               "metric": "pearson_r", "unit": "ratio", "value": -0.1338}),
        claim("correct_absolute", "Absolute MAE is higher during high demand.",
              ["E_ABS_HIGH", "E_ABS_OTHER"],
              compare("E_ABS_HIGH", "E_ABS_OTHER", "gt")),
    ]
    result = audit(*examples)
    statuses = {a["id"]: a["status"] for a in result["audits"]}
    assert statuses == {
        "wrong_direction": "rejected", "wrong_metric": "rejected",
        "wrong_correlation": "rejected", "correct_absolute": "review_required",
    }
