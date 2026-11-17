"""Deterministic and mocked-review regression tests for the fixed benchmark."""
from gridregime.interpretation_benchmark import benchmark_cases, evaluate


def test_benchmark_is_fixed_balanced_and_unique():
    cases = benchmark_cases()
    assert len(cases) == 24
    assert len({c["id"] for c in cases}) == 24
    assert sum(c["expected"] == "supported" for c in cases) == 12
    assert sum(c["expected"] == "unsupported" for c in cases) == 12


def test_deterministic_baseline_and_no_publication():
    result = evaluate(benchmark_cases())
    metrics = result["metrics"]
    assert metrics["deterministic_detection_rate"] >= 3 / 12
    assert metrics["combined_detection_rate"] == metrics["deterministic_detection_rate"]
    assert metrics["combined_false_rejection_rate"] == 0
    assert metrics["semantic_abstention_rate"] is None
    assert result["publication"] == []


def test_perfect_mock_reviewer_detects_remaining_unsupported():
    labels = {c["id"]: c["expected"] for c in benchmark_cases()}
    import json
    def reviewer(claim, evidence):
        verdict = labels[claim["id"]]
        return json.dumps({
            "verdict": verdict, "reason": "injected oracle for harness test",
            "cited_evidence_ids": [e["id"] for e in evidence],
        })
    result = evaluate(benchmark_cases(), semantic_review=True, reviewer=reviewer)
    metrics = result["metrics"]
    assert metrics["combined_detection_rate"] == 1
    assert metrics["combined_false_rejection_rate"] == 0
    assert metrics["semantic_abstention_rate"] == 0
    assert result["publication"] == []


def test_uncertain_and_error_are_counted_as_abstentions_not_detections():
    import json
    def reviewer(claim, evidence):
        return json.dumps({"verdict": "uncertain", "reason": "insufficient evidence",
                           "cited_evidence_ids": []})
    result = evaluate(benchmark_cases(), semantic_review=True, reviewer=reviewer)
    metrics = result["metrics"]
    assert metrics["semantic_abstention_rate"] == 1
    assert metrics["combined_detection_rate"] == metrics["deterministic_detection_rate"]
    assert result["publication"] == []


def test_wrong_mock_review_can_be_measured_as_false_rejection():
    import json
    def reviewer(claim, evidence):
        return json.dumps({"verdict": "unsupported", "reason": "incorrect verdict",
                           "cited_evidence_ids": [e["id"] for e in evidence]})
    result = evaluate(benchmark_cases(), semantic_review=True, reviewer=reviewer)
    assert result["metrics"]["combined_false_rejection_rate"] == 1
    assert result["publication"] == []
