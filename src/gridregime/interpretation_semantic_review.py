"""Advisory semantic review of claims with a local Ollama model.

The reviewer sees only cited evidence and a claim. It cannot approve publication,
alter deterministic decisions, or certify natural-language entailment.
"""
from __future__ import annotations

from copy import deepcopy
import json
from urllib.request import Request, urlopen

VERDICTS = {"supported", "unsupported", "uncertain"}
REVIEW_PROMPT = """You are an independent, skeptical reviewer of historical PJM research.
Examine the claim's prose AND structured assertion against ONLY the cited evidence.
Check variable identities, population, units, direction, compound statements,
causal overreach, and unsupported significance claims. Do not invent data.
A matching number alone does not prove the prose. Return JSON ONLY:
{"verdict":"supported|unsupported|uncertain","reason":"short explanation",
"cited_evidence_ids":["IDs actually used"]}.
Judge whether the CLAIM AS WORDED is justified by the supplied evidence,
not whether the proposition could possibly be true in the real world.
- supported: every material assertion follows from the cited evidence, within
  its measured variables, population, time scope, and strength of inference.
- unsupported: any material assertion goes beyond, misstates, or contradicts
  the evidence. This includes claims of proof, causation, intent, universal
  scope, regional scope, future guarantees, or statistical significance when
  the necessary supporting measurements or tests are absent. A proposition
  can be unsupported without being proven false.
- uncertain: the available evidence or the claim's wording is genuinely
  ambiguous, so you cannot confidently decide whether the claim is supported.
  Do NOT use uncertain merely because an unsupported claim might be true with
  additional evidence. Missing evidence for a definite claim is unsupported.
Evaluate every independent clause; the weakest unsupported material clause
determines the verdict. The structured assertion may be numerically correct
while the prose is unsupported. 'supported' is advisory, NOT approval.
"""


def parse_review(raw: str, allowed_ids: set[str]) -> dict:
    obj = json.loads(raw)
    if not isinstance(obj, dict) or obj.get("verdict") not in VERDICTS:
        raise ValueError("invalid_semantic_verdict")
    reason = obj.get("reason")
    ids = obj.get("cited_evidence_ids")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 4000:
        raise ValueError("invalid_semantic_reason")
    if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids):
        raise ValueError("invalid_semantic_citations")
    if len(ids) != len(set(ids)) or not set(ids).issubset(allowed_ids):
        raise ValueError("unknown_semantic_citation")
    if obj["verdict"] == "supported" and not ids:
        raise ValueError("supported_review_requires_citation")
    return {"verdict": obj["verdict"], "reason": reason,
            "cited_evidence_ids": ids}


def query_semantic_review(claim: dict, evidence: list[dict], *,
                          model: str = "qwen3:8b",
                          url: str = "http://127.0.0.1:11434/api/chat",
                          timeout: float = 180.0) -> str:
    payload = json.dumps({
        "model": model, "stream": False, "format": "json",
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": REVIEW_PROMPT},
            {"role": "user", "content": json.dumps({
                "claim": claim, "cited_evidence": evidence,
            }, sort_keys=True)},
        ],
    }).encode("utf-8")
    request = Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)["message"]["content"]


def review_audit(audit: dict, *, model: str = "qwen3:8b",
                 reviewer=None) -> dict:
    """Append advisory review results without changing authoritative statuses.

    reviewer(claim, cited_evidence) can be injected for offline tests.
    """
    result = deepcopy(audit)
    source = result["source"]
    catalog = {e["id"]: e for e in source["evidence"]}
    claims = {c["id"]: c for c in source["claims"]}
    if len(claims) != len(source["claims"]):
        raise ValueError("duplicate_claim_id")
    if result.get("publication"):
        raise ValueError("semantic_review_requires_unpublished_audit")
    for item in result["audits"]:
        cid = item["id"]
        claim = claims[cid]
        ids = claim.get("evidence_ids", [])
        ids = ids if isinstance(ids, list) else []
        cited = [catalog[i] for i in ids if isinstance(i, str) and i in catalog]
        if item["status"] == "rejected":
            item["semantic_review"] = {
                "verdict": "not_run", "reason": "deterministic_rejection",
                "cited_evidence_ids": [],
            }
            continue
        try:
            raw = (reviewer(claim, cited) if reviewer is not None
                   else query_semantic_review(claim, cited, model=model))
            item["semantic_review"] = parse_review(raw, {
                e["id"] for e in cited
            })
        except (ValueError, KeyError, TypeError, OSError, TimeoutError) as exc:
            item["semantic_review"] = {
                "verdict": "error", "reason": type(exc).__name__,
                "cited_evidence_ids": [],
            }
    result["semantic_review_model"] = model
    result["status"] = "requires_independent_claim_review"
    result["publication"] = []
    return result
