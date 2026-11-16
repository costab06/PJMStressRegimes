"""Conservative claim-level publication gate inspired by InvestmentIntelligence.

The verifier checks typed assertions, not arbitrary prose entailment.
Unverifiable claims are withheld, never silently promoted to verified.
"""
from __future__ import annotations

from copy import deepcopy
from gridregime.interpretation_stages import (
    verify_numerical_assertion, verify_evidence_identity, verify_prose_consistency,
)

VALID_TYPES = {"observed_fact", "interpretation", "prediction"}
VALID_ROLES = {"establishes_fact", "supports_inference", "context_only"}
def verify_claim(claim: dict, evidence: dict[str, dict]) -> dict:
    """Return a deterministic disposition with machine-readable reasons."""
    reasons: list[str] = []
    cid = claim.get("id")
    kind = claim.get("type")
    ids = claim.get("evidence_ids")
    roles = claim.get("evidence_roles")
    if kind not in VALID_TYPES or not isinstance(claim.get("text"), str) or not claim["text"].strip():
        reasons.append("invalid_claim_schema")
    if not isinstance(ids, list) or not ids or any(not isinstance(i, str) for i in ids):
        reasons.append("missing_evidence_ids")
        ids = []
    if len(ids) != len(set(ids)):
        reasons.append("duplicate_evidence_ids")
    if any(i not in evidence for i in ids):
        reasons.append("unknown_evidence_id")
    if not isinstance(roles, dict) or set(roles) != set(ids) or any(
        r not in VALID_ROLES for r in roles.values()
    ):
        reasons.append("invalid_evidence_roles")
    elif not any(roles[i] == "establishes_fact" for i in ids):
        reasons.append("no_fact_establishing_evidence")

    numerical_issues = verify_numerical_assertion(claim.get("assertion"), ids, evidence)
    identity_issues = verify_evidence_identity(claim, evidence)
    prose_issues = verify_prose_consistency(claim, evidence)
    reasons.extend(numerical_issues)
    reasons.extend(identity_issues)
    reasons.extend(prose_issues)
    if kind == "prediction":
        reasons.append("prediction_not_established_by_historical_evidence")
    if kind == "interpretation":
        reasons.append("interpretation_requires_independent_review")
    # Numerical consistency is necessary but not sufficient for prose entailment.
    status = "rejected" if any(x in reasons for x in (
        "invalid_claim_schema", "missing_evidence_ids", "duplicate_evidence_ids",
        "unknown_evidence_id", "invalid_evidence_roles", "no_fact_establishing_evidence",
        "invalid_comparison", "incompatible_metrics_or_units",
        "comparison_requires_distinct_populations", "comparison_contradicted",
        "invalid_evidence_value", "invalid_value_reference", "value_contradicted",
        "missing_typed_assertion", "invalid_compound_assertion",
        "compound_claim_missing_assertions", "correlation_variable_mismatch",
        "significance_requires_statistical_test", "prose_metric_identity_mismatch",
    )) else "review_required"
    return {"id": cid, "status": status, "issues": reasons,
            "stages": {"numerical": numerical_issues, "evidence_identity": identity_issues,
                       "prose_consistency": prose_issues},
            "numeric_check": "not_disproven" if status != "rejected" else "failed"}


def audit_interpretation(document: dict) -> dict:
    """Audit without mutating original proposals; fail closed for publication.

    The caller must separately provide reviewed claim IDs to publish text.
    """
    original = deepcopy(document)
    evidence = {}
    for item in document.get("evidence", []):
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            if item["id"] in evidence:
                raise ValueError("duplicate_evidence_catalog_id")
            evidence[item["id"]] = item
    claims = document.get("claims", [])
    if not isinstance(claims, list):
        raise ValueError("claims_must_be_list")
    audits = [verify_claim(c, evidence) for c in claims]
    return {"source": original, "audits": audits,
            "publication": [],
            "status": "requires_independent_claim_review",
            "note": "A passing numeric check does not prove narrative entailment."}


def publish_reviewed(audit: dict, approved_ids: set[str]) -> dict:
    """Only explicitly approved, non-rejected claims may be rendered."""
    result = deepcopy(audit)
    by_id = {a["id"]: a for a in result["audits"]}
    if len(by_id) != len(result["audits"]):
        raise ValueError("duplicate_claim_id")
    unknown = approved_ids - set(by_id)
    if unknown:
        raise ValueError("unknown_approved_claim_ids")
    invalid = [i for i in approved_ids if by_id[i]["status"] == "rejected"]
    if invalid:
        raise ValueError("cannot_publish_rejected_claim")
    result["publication"] = [
        {"id": c["id"], "text": c["text"], "evidence_ids": c["evidence_ids"]}
        for c in result["source"]["claims"] if c["id"] in approved_ids
    ]
    result["status"] = "reviewed_publication"
    return result
