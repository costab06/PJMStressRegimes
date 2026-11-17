"""Provenance contract tests: source metadata is data, not prompt inference."""
import json

from gridregime.interpretation_pjm_holdout import EVIDENCE, holdout_cases
from gridregime.interpretation_provenance import validate_provenance
from gridregime.interpretation_verification import audit_interpretation
from gridregime.interpretation_semantic_review import review_audit


def test_holdout_source_date_is_explicit_for_pending_items():
    pending = next(e for e in EVIDENCE if e["id"] == "H_PENDING")
    assert pending["provenance"]["source_date"] == "2026-10-01"
    assert pending["provenance"]["section"] == "model_plan.modeling_gate"


def test_provenance_validation_accepts_legacy_and_new_records():
    assert validate_provenance({"id": "legacy"}) == []
    assert all(validate_provenance(e) == [] for e in EVIDENCE)


def test_invalid_provenance_rejects_claim_without_semantic_override():
    case = holdout_cases()[3]["claim"]
    evidence = [dict(next(e for e in EVIDENCE if e["id"] == "H_PENDING"))]
    evidence[0]["provenance"] = {"source_date": 20261001}
    audit = audit_interpretation({"evidence": evidence, "claims": [case]})
    assert audit["audits"][0]["status"] == "rejected"
    assert "invalid_evidence_provenance" in audit["audits"][0]["issues"]


def test_reviewer_receives_source_context_but_no_benchmark_label():
    case = holdout_cases()[3]["claim"]
    seen = {}
    def reviewer(claim, evidence):
        seen["claim"] = claim
        seen["evidence"] = evidence
        return json.dumps({"verdict": "supported", "reason": "source dated",
                           "cited_evidence_ids": ["H_PENDING"]})
    audit = audit_interpretation({"evidence": EVIDENCE, "claims": [case]})
    result = review_audit(audit, reviewer=reviewer)
    assert seen["evidence"][0]["provenance"]["source_date"] == "2026-10-01"
    assert "expected" not in seen["claim"]
    assert result["audits"][0]["semantic_review"]["verdict"] == "supported"
    assert result["publication"] == []
