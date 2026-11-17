"""Fixed, labeled adversarial benchmark for claim-level interpretation review.

Labels are human-authored expectations, never passed to the reviewer. The
benchmark is synthetic around the frozen DEMO_EVIDENCE fixture, not an
empirical estimate of performance on unseen research claims.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gridregime.interpretation_live import DEMO_EVIDENCE
from gridregime.interpretation_semantic_review import review_audit
from gridregime.interpretation_verification import audit_interpretation


def _comparison(a, b, op):
    return {"kind": "comparison", "left": a, "right": b, "operator": op}


def _value(eid):
    fact = next(e for e in DEMO_EVIDENCE if e["id"] == eid)
    return {"kind": "value", "evidence_id": eid, "metric": fact["metric"],
            "unit": fact["unit"], "value": fact["value"]}


def _case(cid, label, text, ids, assertion, category):
    return {"id": cid, "expected": label, "category": category,
            "claim": {"id": cid, "type": "interpretation", "text": text,
                      "evidence_ids": ids,
                      "evidence_roles": {i: "establishes_fact" for i in ids},
                      "assertion": assertion}}


def benchmark_cases():
    p = ["E_PCT_HIGH", "E_PCT_OTHER"]
    a = ["E_ABS_HIGH", "E_ABS_OTHER"]
    h, o, r = "E_BIAS_HIGH", "E_BIAS_OTHER", "E_CORRELATION"
    c = []
    def add(label, text, ids, assertion, category):
        c.append(_case(f"B{len(c)+1:02}", label, text, ids, assertion, category))
    # Supported controls: every statement is limited to the supplied fixture.
    add("supported", "Percentage MAE is lower for high demand than other hours.", p,
        _comparison(*p, "lt"), "numeric")
    add("supported", "Absolute MAE is higher for high demand than other hours.", a,
        _comparison(*a, "gt"), "numeric")
    add("supported", "The high-demand percentage MAE is 3.3846 percent.", [p[0]],
        _value(p[0]), "value")
    add("supported", "Other-hours percentage MAE is 4.2445 percent.", [p[1]],
        _value(p[1]), "value")
    add("supported", "High-demand absolute MAE is 5091.413 MWh.", [a[0]],
        _value(a[0]), "value")
    add("supported", "Other-hours absolute MAE is 4485.795 MWh.", [a[1]],
        _value(a[1]), "value")
    add("supported", "High-demand signed bias is negative at -0.9647 percent.", [h],
        _value(h), "bias")
    add("supported", "Other-hours signed bias is positive at 2.1339 percent.", [o],
        _value(o), "bias")
    add("supported", "The negative signed bias for high demand means actual demand was below forecast.", [h],
        _value(h), "bias")
    add("supported", "The positive signed bias for other hours means actual demand exceeded forecast.", [o],
        _value(o), "bias")
    add("supported", "Pearson correlation between demand change and interchange level is -0.1338.", [r],
        _value(r), "correlation")
    add("supported", "The observed correlation between demand change and interchange level is negative.", [r],
        _value(r), "correlation")
    # Unsupported claims: some intentionally pass the typed numerical gate.
    add("unsupported", "Absolute MAE is lower for high demand than other hours.", a,
        _comparison(*a, "lt"), "numeric_contradiction")
    add("unsupported", "Mean absolute error is lower during high demand than other hours.", p,
        _comparison(*p, "lt"), "metric_mismatch")
    add("unsupported", "Pearson correlation between forecast and actual demand is -0.1338.", [r],
        _value(r), "variable_mismatch")
    add("unsupported", "The demand-change and interchange correlation is statistically significant.", [r],
        _value(r), "unsupported_significance")
    add("unsupported", "The demand-change and interchange correlation proves that interchange causes demand changes.", [r],
        _value(r), "causal_overreach")
    add("unsupported", "The demand-change and interchange correlation establishes that increasing interchange reduces demand.", [r],
        _value(r), "causal_overreach")
    add("unsupported", "The high-demand bias proves forecasting models are intentionally underpredicting demand.", [h],
        _value(h), "intent_inference")
    add("unsupported", "The high-demand bias proves the forecasts were manipulated.", [h],
        _value(h), "intent_inference")
    add("unsupported", "The observed high-demand percentage MAE guarantees future high-demand forecasts will be more accurate.", p,
        _comparison(*p, "lt"), "future_extrapolation")
    add("unsupported", "The observed high-demand absolute MAE establishes that every high-demand hour has a larger error.", a,
        _comparison(*a, "gt"), "aggregation_fallacy")
    add("unsupported", "The observed high-demand percentage MAE demonstrates that all PJM regions have lower error at peak demand.", p,
        _comparison(*p, "lt"), "population_extrapolation")
    add("unsupported", "The weak negative correlation between demand change and interchange level proves the power grid is stable under extreme weather.", [r],
        _value(r), "unsupported_generalization")
    assert len(c) == 24
    return c


def evaluate(cases, *, semantic_review=False, model="qwen3:8b", reviewer=None,
             evidence=None):
    document = {"evidence": DEMO_EVIDENCE if evidence is None else evidence,
                "claims": [c["claim"] for c in cases]}
    audit = audit_interpretation(document)
    if semantic_review:
        audit = review_audit(audit, model=model, reviewer=reviewer)
    records = []
    for case, item in zip(cases, audit["audits"]):
        assert case["id"] == item["id"]
        deterministic = item["status"] == "rejected"
        verdict = item.get("semantic_review", {}).get("verdict", "not_run")
        # Advisory 'unsupported' is a detection, NOT an authoritative rejection.
        detected = deterministic or verdict == "unsupported"
        records.append({
            "id": case["id"], "category": case["category"],
            "expected": case["expected"], "deterministic_rejected": deterministic,
            "semantic_verdict": verdict, "detected_unsupported": detected,
            "deterministic_issues": item["issues"],
            "semantic_reason": item.get("semantic_review", {}).get("reason", ""),
        })
    bad = [x for x in records if x["expected"] == "unsupported"]
    good = [x for x in records if x["expected"] == "supported"]
    eligible = [x for x in records if not x["deterministic_rejected"]]
    def ratio(n, d):
        return n / d if d else None
    metrics = {
        "cases": len(records),
        "unsupported_cases": len(bad), "supported_cases": len(good),
        "deterministic_detection_rate": ratio(
            sum(x["deterministic_rejected"] for x in bad), len(bad)),
        "combined_detection_rate": ratio(
            sum(x["detected_unsupported"] for x in bad), len(bad)),
        "combined_false_rejection_rate": ratio(
            sum(x["detected_unsupported"] for x in good), len(good)),
        "semantic_eligible": len(eligible),
        "semantic_abstention_rate": ratio(
            sum(x["semantic_verdict"] in ("uncertain", "error") for x in eligible),
            len(eligible)) if semantic_review else None,
        "semantic_unsupported_count": sum(
            x["semantic_verdict"] == "unsupported" for x in eligible),
        "semantic_error_count": sum(
            x["semantic_verdict"] == "error" for x in eligible),
        "semantic_review_enabled": semantic_review,
        "model": model if semantic_review else None,
    }
    return {"metrics": metrics, "cases": records, "publication": audit["publication"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--semantic-review", action="store_true")
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--output", type=Path,
                        default=Path("results/interpretation-benchmark.json"))
    args = parser.parse_args()
    result = evaluate(benchmark_cases(), semantic_review=args.semantic_review,
                      model=args.model)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["metrics"], indent=2))


if __name__ == "__main__":
    main()
