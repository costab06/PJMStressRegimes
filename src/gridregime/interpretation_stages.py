"""Independent, auditable verification stages.

Numerical checks establish typed arithmetic consistency only. Evidence identity
and prose checks are conservative PJM-specific rules, not general entailment.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Any

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


def verify_numerical_assertion(assertion: dict, ids: list[str],
                               evidence: dict[str, dict]) -> list[str]:
    """Check typed values/comparisons, including every part of a compound."""
    reasons: list[str] = []
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
                reasons.extend(verify_numerical_assertion(part, ids, evidence))
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

    return reasons


def verify_evidence_identity(claim: dict, evidence: dict[str, dict]) -> list[str]:
    """Check declared measurement identities; no general semantic inference."""
    reasons: list[str] = []
    ids = claim.get("evidence_ids")
    ids = ids if isinstance(ids, list) else []
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

    return reasons


def verify_prose_consistency(claim: dict, evidence: dict[str, dict]) -> list[str]:
    """Conservative text-to-assertion checks; never asserts full entailment."""
    reasons: list[str] = []
    ids = claim.get("evidence_ids")
    ids = ids if isinstance(ids, list) else []
    assertion = claim.get("assertion")
    text_lower = claim.get("text", "").lower() if isinstance(claim.get("text"), str) else ""
    # Catch prose that names absolute error while the structured assertion
    # silently cites percentage error (observed in live qwen3:8b run v2).
    # This narrow check does not claim general prose entailment.
    names_absolute_mae = bool(re.search(
        r"\b(?:mean absolute error|absolute mean error|absolute (?:forecast )?error|mae)\b",
        text_lower,
    ))
    names_percentage_mae = bool(re.search(
        r"\b(?:percentage|percent|mape|percentage error)\b", text_lower
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

    return reasons
