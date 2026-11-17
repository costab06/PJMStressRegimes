"""Offline contracts for the sourced PJM holdout.

The labels and factual descriptions must be manually checked against the
2026-10-01 research specification before interpreting model accuracy.
"""
import json

from gridregime.interpretation_benchmark import evaluate
from gridregime.interpretation_pjm_holdout import EVIDENCE, holdout_cases


def test_holdout_is_balanced_and_source_grounded():
    cases=holdout_cases()
    assert len(cases)==20
    assert len({c["id"] for c in cases})==20
    assert sum(c["expected"]=="supported" for c in cases)==10
    assert sum(c["expected"]=="unsupported" for c in cases)==10
    assert all(e["source"] in {"research_spec.yaml","paper/manuscript.md"}
               for e in EVIDENCE)


def test_holdout_is_distinct_from_mae_benchmark():
    from gridregime.interpretation_benchmark import benchmark_cases
    old={c["claim"]["text"] for c in benchmark_cases()}
    new={c["claim"]["text"] for c in holdout_cases()}
    assert not old.intersection(new)
    assert all(e["id"].startswith("H_") for e in EVIDENCE)


def test_holdout_runs_without_llm_or_publication():
    result=evaluate(holdout_cases(),evidence=EVIDENCE)
    assert result["metrics"]["cases"]==20
    assert result["metrics"]["semantic_eligible"]>0
    assert result["publication"]==[]


def test_holdout_reviewer_is_advisory():
    labels={c["id"]:c["expected"] for c in holdout_cases()}
    def reviewer(claim,evidence):
        return json.dumps({"verdict":labels[claim["id"]],
                           "reason":"offline harness oracle",
                           "cited_evidence_ids":[e["id"] for e in evidence]})
    result=evaluate(holdout_cases(),evidence=EVIDENCE,
                    semantic_review=True,reviewer=reviewer)
    assert result["metrics"]["combined_detection_rate"]==1
    assert result["metrics"]["combined_false_rejection_rate"]==0
    assert result["publication"]==[]
