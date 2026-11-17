"""Optional, explicit evidence provenance for interpretation review.

Provenance describes the *source*, not a claim inferred by the reviewer.
No dates, scopes, or epistemic status are inferred from filenames.
Legacy evidence records without provenance remain valid.
"""
from __future__ import annotations

from copy import deepcopy

STATUSES = {"observation", "exploratory_finding", "hypothesis",
            "methodological_definition", "planned", "established_result"}


def validate_provenance(evidence: dict) -> list[str]:
    """Validate optional source metadata; return deterministic issue codes."""
    if "provenance" not in evidence:
        return []
    p = evidence["provenance"]
    if not isinstance(p, dict):
        return ["invalid_evidence_provenance"]
    allowed = {"document", "section", "source_date", "observation_period",
               "evidence_status", "locator"}
    if not p or set(p) - allowed:
        return ["invalid_evidence_provenance"]
    for key, value in p.items():
        if not isinstance(value, str) or not value.strip():
            return ["invalid_evidence_provenance"]
    if "evidence_status" in p and p["evidence_status"] not in STATUSES:
        return ["invalid_evidence_provenance"]
    return []


def prepare_cited_evidence(evidence: dict) -> dict:
    """Copy cited evidence unchanged, including explicitly supplied provenance.

    The reviewer gets the source's dates and status in the cited evidence,
    without benchmark labels or a guessed context envelope.
    """
    return deepcopy(evidence)
