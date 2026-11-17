"""Fast transport-independent tests for the new application boundary."""
import pytest
from gridregime.operational import FeatureSnapshot, candidate_from_training, evaluate_stress


def snapshot(**kwargs):
    params = dict(observation_as_of="2026-07-01T00:00:00Z", feature_version="frozen-v1", source_sha256="a"*64, values={"load_z": 3.0, "fe_z": 4.0, "ramp3_z": 0.0, "ic_z": 0.0})
    params.update(kwargs)
    return FeatureSnapshot(**params)


def test_signal_is_evidence_grounded_not_emergency_probability():
    result = evaluate_stress(snapshot(), decision_as_of="2026-07-01T01:00:00Z")
    assert result.score == 5.0 and result.state == "elevated"
    assert result.evidence["fe_z"] == 4.0
    assert result.predictive_validation_status == "not_established"


def test_feature_contract_fails_closed():
    with pytest.raises(ValueError):
        snapshot(values={"load_z": float("nan"), "fe_z": 1, "ramp3_z": 2, "ic_z": 3})
    with pytest.raises(ValueError):
        snapshot(source_sha256="bad")


def test_time_contract_fails_closed():
    with pytest.raises(ValueError):
        snapshot(observation_as_of="2026-07-01T00:00:00")
    with pytest.raises(ValueError):
        evaluate_stress(snapshot(), decision_as_of="2026-06-30T23:00:00Z")


def test_candidate_is_unapproved_and_checksums_artifact():
    candidate = candidate_from_training(model_id="isolation-forest", model_version="v2", feature_version="frozen-v1", artifact=b"model", evaluation={"coverage": 0.9}, trained_as_of="2026-07-01T00:00:00Z")
    assert candidate.approved is False and len(candidate.artifact_sha256) == 64
