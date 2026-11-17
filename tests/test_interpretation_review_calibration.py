"""Contract checks for semantic-review verdict calibration.

These verify prompt construction and label isolation, not LLM accuracy.
"""
import json

from gridregime.interpretation_benchmark import benchmark_cases
from gridregime.interpretation_semantic_review import REVIEW_PROMPT, query_semantic_review


def test_prompt_distinguishes_unsupported_from_uncertain():
    assert "A proposition" in REVIEW_PROMPT
    assert "unsupported without being proven false" in REVIEW_PROMPT
    assert "Missing evidence for a definite claim is unsupported" in REVIEW_PROMPT
    assert "Do NOT use uncertain" in REVIEW_PROMPT


def test_prompt_does_not_leak_benchmark_examples_or_labels():
    for case in benchmark_cases():
        assert case["claim"]["text"] not in REVIEW_PROMPT


def test_ollama_request_excludes_expected_label(monkeypatch):
    from gridregime import interpretation_semantic_review as module
    case = benchmark_cases()[19]
    captured = {}
    class FakeResponse:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, *args):
            return b'{"message":{"content":"{}"}}'
    def fake_open(request, timeout):
        captured["body"] = json.loads(request.data)
        return FakeResponse()
    monkeypatch.setattr(module, "urlopen", fake_open)
    query_semantic_review(case["claim"], [{"id": "E_BIAS_HIGH", "value": -0.9647}])
    messages = captured["body"]["messages"]
    user = json.loads(messages[1]["content"])
    assert "expected" not in user
    assert "category" not in user
    assert user["claim"]["id"] == case["id"]
    assert captured["body"]["options"]["temperature"] == 0
