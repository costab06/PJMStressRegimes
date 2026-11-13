"""Contract tests for deterministic acquisition-to-feature planning."""
import hashlib

import pytest

from gridregime.oaf.feature_request_planner import plan_feature_request


def inputs(tmp_path):
    source = tmp_path / "eia.csv"
    baseline = tmp_path / "baseline.parquet"
    source.write_bytes(b"frozen eia snapshot")
    baseline.write_bytes(b"approved baseline bytes")
    dispatch = {
        "ba": "PJM", "start": "2022-12-19T05",
        "end": "2022-12-20T04", "as_of": "2022-12-20T06:00Z",
        "publication_lag_hours": 2, "require_pjm": False,
    }
    fetched = {
        "ba": "PJM", "start": dispatch["start"], "end": dispatch["end"],
        "artifact_path": str(source),
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }
    status = {
        "status": "observation-ready-publication-unverified",
        "ready_for_predictive_inference": False,
        "sources": {"eia930": "observations-current-publication-unverified"},
    }
    return dispatch, fetched, status, baseline


def test_feature_request_joins_verified_artifacts_and_times(tmp_path):
    dispatch, fetched, status, baseline = inputs(tmp_path)
    result = plan_feature_request(
        dispatch=dispatch, eia_fetched=fetched,
        acquisition_status=status, baseline_path=baseline,
    )
    assert result["as_of"] == "2022-12-20T04:00:00+00:00"
    assert result["decision_as_of"] == "2022-12-20T06:00:00+00:00"
    assert result["baseline_sha256"] == hashlib.sha256(baseline.read_bytes()).hexdigest()
    assert result["ready_for_predictive_inference"] is False
    assert result == plan_feature_request(
        dispatch=dispatch, eia_fetched=fetched,
        acquisition_status=status, baseline_path=baseline,
    )


def test_reject_tampered_source(tmp_path):
    dispatch, fetched, status, baseline = inputs(tmp_path)
    (tmp_path / "eia.csv").write_bytes(b"changed source")
    with pytest.raises(ValueError, match="hash mismatch"):
        plan_feature_request(
            dispatch=dispatch, eia_fetched=fetched,
            acquisition_status=status, baseline_path=baseline,
        )


def test_reject_mismatched_observation_window(tmp_path):
    dispatch, fetched, status, baseline = inputs(tmp_path)
    fetched["end"] = "2022-12-20T03"
    with pytest.raises(ValueError, match="window"):
        plan_feature_request(
            dispatch=dispatch, eia_fetched=fetched,
            acquisition_status=status, baseline_path=baseline,
        )


def test_reject_unready_evidence(tmp_path):
    dispatch, fetched, status, baseline = inputs(tmp_path)
    status["status"] = "pending-evidence"
    with pytest.raises(ValueError, match="not observation-ready"):
        plan_feature_request(
            dispatch=dispatch, eia_fetched=fetched,
            acquisition_status=status, baseline_path=baseline,
        )


def test_reject_required_pjm_without_verified_coverage(tmp_path):
    dispatch, fetched, status, baseline = inputs(tmp_path)
    dispatch["require_pjm"] = True
    with pytest.raises(ValueError, match="PJM evidence"):
        plan_feature_request(
            dispatch=dispatch, eia_fetched=fetched,
            acquisition_status=status, baseline_path=baseline,
        )
