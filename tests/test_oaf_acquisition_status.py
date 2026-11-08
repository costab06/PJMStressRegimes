"""Acquisition cycle readiness is conservative and evidence-driven."""
from gridregime.oaf.acquisition_status import evaluate_cycle


def test_missing_evidence_is_pending():
    result = evaluate_cycle(dispatch={"ba": "PJM"}, eia=None, pjm=None)
    assert result["status"] == "pending-evidence"
    assert not result["ready_for_predictive_inference"]


def test_stale_eia_is_degraded():
    result = evaluate_cycle(
        dispatch={"ba": "PJM"}, eia={"status": "stale"}, pjm=None,
    )
    assert result["status"] == "degraded"


def test_current_eia_still_not_publication_verified():
    result = evaluate_cycle(
        dispatch={"ba": "PJM"},
        eia={"status": "observations-current-publication-unverified"},
        pjm=None,
    )
    assert result["status"] == "observation-ready-publication-unverified"
    assert not result["publication_time_verified"]
    assert not result["ready_for_predictive_inference"]


def test_archival_pjm_does_not_satisfy_required_live_source():
    result = evaluate_cycle(
        dispatch={"ba": "PJM"},
        eia={"status": "observations-current-publication-unverified"},
        pjm={"coverage_status": "unverified"},
        require_pjm=True,
    )
    assert result["status"] == "pending-evidence"
    assert result["sources"]["pjm_procedures"] == "unverified"
