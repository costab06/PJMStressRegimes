"""Conservative claim-level publication gate inspired by InvestmentIntelligence.

The verifier checks typed assertions, not arbitrary prose entailment.
Unverifiable claims are withheld, never silently promoted to verified.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
import re
from typing import Any

VALID_TYPES = {"observed_fact", "interpretation", "prediction"}
VALID_ROLES = {"establishes_fact", "supports_inference", "context_only"}
COMPARISONS = {"gt", "lt", "eq"}
TOLERANCE = Decimal("0.000001")


def _number(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("invalid_numeric_value")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("invalid_numeric_value") from None
    if not number.is_finite():
        raise ValueError("invalid_numeric_value")
    return number


def _compare(a: Decimal, b: Decimal, operator: str) -> bool:
    delta = a - b
    tolerance = max(TOLERANCE, max(abs(a), abs(b)) * Decimal("0.00000001"))
    if operator == "gt":
        return delta > tolerance
    if operator == "lt":
        return delta < -tolerance
    if operator == "eq":
        return abs(delta) <= tolerance
    return False


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

    assertion = claim.get("assertion")
    text_lower = claim.get("text", "").lower() if isinstance(claim.get("text"), str) else ""
    # Domain-specific semantic checks are conservative: flag known contradictions,
    # never claim to establish general natural-language entailment.
    correlation_ids = [i for i in ids if i in evidence and evidence[i].get("metric") == "pearson_r"]
    if correlation_ids and "between" in text_lower:
        # This metric is specifically demand-change versus interchange-level,
        # not forecast versus actual. Require both measured concepts.
        if not (re.search(r"demand\s+chang", text_lower) and
                re.search(r"interchange", text_lower)):
            reasons.append("correlation_variable_mismatch")
    if correlation_ids and re.search(r"statistically significant|not significant|insignificant", text_lower):
        reasons.append("significance_requires_statistical_test")
    # Catch prose that names absolute error while the structured assertion
    # silently cites percentage error (observed in live qwen3:8b run v2).
    # This narrow check does not claim general prose entailment.
    names_absolute_mae = bool(re.search(
        r"\\b(?:mean absolute error|absolute mean error|absolute (?:forecast )?error|mae)\\b",
        text_lower,
    ))
    names_percentage_mae = bool(re.search(
        r"\\b(?:percentage|percent|mape|percentage error)\\b", text_lower
    ))
    if names_absolute_mae and not names_percentage_mae:
        referenced_metrics = {
            evidence[i].get("metric") for i in ids if i in evidence
        }
        if "mae_percent" in referenced_metrics and "mae_absolute" not in referenced_metrics:
            reasons.append("prose_metric_identity_mismatch")
    # Compound conclusions need a typed assertion for each independent metric.
    compound_mae = ("percentage" in text_lower or "percent" in text_lower) and "absolute" in text_lower and "error" in text_lower
    assertions = assertion.get("assertions") if isinstance(assertion, dict) and assertion.get("kind") == "all" else [assertion]
    if compound_mae:
        checked_metrics = set()
        for part in assertions if isinstance(assertions, list) else []:
            if isinstance(part, dict) and part.get("kind") == "comparison":
                a, b = part.get("left"), part.get("right")
                if isinstance(a, str) and isinstance(b, str) and a in evidence and b in evidence:
                    if evidence[a].get("metric") == evidence[b].get("metric"):
                        checked_metrics.add(evidence[a].get("metric"))
        if not {"mae_percent", "mae_absolute"} <= checked_metrics:
            reasons.append("compound_claim_missing_assertions")
    if kind == "prediction":
        reasons.append("prediction_not_established_by_historical_evidence")
    if kind == "interpretation":
        reasons.append("interpretation_requires_independent_review")
    if not isinstance(assertion, dict) or assertion.get("kind") not in {"comparison", "value", "all"}:
        reasons.append("missing_typed_assertion")
    elif assertion["kind"] == "all":
        parts = assertion.get("assertions")
        if not isinstance(parts, list) or not parts or any(
            not isinstance(p, dict) or p.get("kind") not in {"comparison", "value"} for p in parts
        ):
            reasons.append("invalid_compound_assertion")
        else:
            for part in parts:
                subclaim = dict(claim, assertion=part, text="Numeric subassertion")
                subaudit = verify_claim(subclaim, evidence)
                if subaudit["status"] == "rejected":
                    reasons.extend(subaudit["issues"])
    elif assertion["kind"] == "comparison":
        left, right, op = assertion.get("left"), assertion.get("right"), assertion.get("operator")
        if op not in COMPARISONS or left not in ids or right not in ids or left == right:
            reasons.append("invalid_comparison")
        elif left in evidence and right in evidence:
            l, r = evidence[left], evidence[right]
            if l.get("unit") != r.get("unit") or l.get("metric") != r.get("metric"):
                reasons.append("incompatible_metrics_or_units")
            elif l.get("population") == r.get("population"):
                reasons.append("comparison_requires_distinct_populations")
            else:
                try:
                    if not _compare(_number(l["value"]), _number(r["value"]), op):
                        reasons.append("comparison_contradicted")
                except (KeyError, ValueError):
                    reasons.append("invalid_evidence_value")
    elif assertion["kind"] == "value":
        eid = assertion.get("evidence_id")
        if eid not in ids or eid not in evidence:
            reasons.append("invalid_value_reference")
        else:
            fact = evidence[eid]
            if assertion.get("unit") != fact.get("unit") or assertion.get("metric") != fact.get("metric"):
                reasons.append("incompatible_metrics_or_units")
            else:
                try:
                    if not _compare(_number(assertion["value"]), _number(fact["value"]), "eq"):
                        reasons.append("value_contradicted")
                except (KeyError, ValueError):
                    reasons.append("invalid_evidence_value")
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
