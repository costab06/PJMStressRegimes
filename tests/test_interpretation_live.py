"""Offline tests of the live Ollama runner's input/output boundary."""
import json

import pytest

from gridregime.interpretation_live import (
    DEMO_EVIDENCE, parse_model_output, run_experiment,
)


def sample_claim():
    return {
        "id": "C1", "type": "observed_fact",
        "text": "Absolute MAE is higher during high demand.",
        "evidence_ids": ["E_ABS_HIGH", "E_ABS_OTHER"],
        "evidence_roles": {
            "E_ABS_HIGH": "establishes_fact",
            "E_ABS_OTHER": "establishes_fact",
        },
        "assertion": {
            "kind": "comparison", "left": "E_ABS_HIGH",
            "right": "E_ABS_OTHER", "operator": "gt",
        },
    }


def test_live_runner_persists_raw_and_audit_without_auto_publication(tmp_path):
    raw = json.dumps({"claims": [sample_claim()]})
    report = run_experiment(tmp_path, raw_response=raw)
    assert report["counts"]["review_required"] == 1
    assert report["published"] == 0
    assert (tmp_path / "llm_raw.txt").read_text() == raw
    audit = json.loads((tmp_path / "claim_audit.json").read_text())
    assert audit["publication"] == []
    assert audit["source"]["evidence"] == DEMO_EVIDENCE


def test_live_runner_rejects_false_comparison(tmp_path):
    bad = sample_claim()
    bad["assertion"]["operator"] = "lt"
    report = run_experiment(tmp_path, raw_response=json.dumps({"claims": [bad]}))
    assert report["counts"]["rejected"] == 1


def test_live_runner_rejects_duplicate_claim_ids():
    claim = sample_claim()
    with pytest.raises(ValueError, match="duplicate_model_claim_id"):
        parse_model_output(json.dumps({"claims": [claim, claim]}))


def test_live_runner_rejects_non_json_and_wrong_shape():
    with pytest.raises(json.JSONDecodeError):
        parse_model_output("not json")
    with pytest.raises(ValueError, match="claims_array"):
        parse_model_output('{"response": "unstructured"}')


@pytest.mark.live_llm
def test_ollama_smoke(tmp_path):
    """Opt-in integration test: RUN_LIVE_LLM=1 pytest -m live_llm."""
    import os
    if os.getenv("RUN_LIVE_LLM") != "1":
        pytest.skip("Set RUN_LIVE_LLM=1 to invoke local Ollama")
    report = run_experiment(tmp_path)
    assert report["claims"] > 0
    assert report["published"] == 0
