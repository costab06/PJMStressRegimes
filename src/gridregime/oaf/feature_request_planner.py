"""Deterministic join of acquisition evidence into a frozen-v1 feature request.

This pure planner does not imply publication-time verification or predictive
readiness. It can be called by a future durable OAF orchestration agent.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd


def plan_feature_request(
    *, dispatch: dict, eia_fetched: dict, acquisition_status: dict,
    baseline_path: str | Path,
) -> dict:
    """Require consistent cycle evidence before planning feature computation."""
    if acquisition_status.get("status") != "observation-ready-publication-unverified":
        raise ValueError("Acquisition evidence is not observation-ready")
    if acquisition_status.get("ready_for_predictive_inference") is not False:
        raise ValueError("Feature planner cannot authorize predictive inference")
    if dispatch.get("require_pjm"):
        if acquisition_status.get("sources", {}).get("pjm_procedures") != "verified":
            raise ValueError("Required PJM evidence is not verified")
    ba = dispatch["ba"]
    if eia_fetched["ba"] != ba:
        raise ValueError("Balancing authority mismatch")
    end = pd.Timestamp(dispatch["end"])
    end = end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")
    fetched_end = pd.Timestamp(eia_fetched["end"])
    fetched_end = fetched_end.tz_localize("UTC") if fetched_end.tzinfo is None else fetched_end.tz_convert("UTC")
    start = pd.Timestamp(dispatch["start"])
    start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
    fetched_start = pd.Timestamp(eia_fetched["start"])
    fetched_start = fetched_start.tz_localize("UTC") if fetched_start.tzinfo is None else fetched_start.tz_convert("UTC")
    if start != fetched_start or end != fetched_end:
        raise ValueError("EIA artifact window does not match dispatched cycle")
    decision = pd.Timestamp(dispatch["as_of"])
    decision = decision.tz_localize("UTC") if decision.tzinfo is None else decision.tz_convert("UTC")
    if decision < end or decision != decision.floor("h"):
        raise ValueError("Invalid decision and observation timestamps")
    if (decision - end) != pd.Timedelta(hours=dispatch["publication_lag_hours"]):
        raise ValueError("Observation end differs from configured publication lag")
    source = Path(eia_fetched["artifact_path"])
    baseline = Path(baseline_path)
    if not source.is_file() or not baseline.is_file():
        raise FileNotFoundError("Source artifact or frozen baseline is missing")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != eia_fetched["sha256"]:
        raise ValueError("EIA source artifact hash mismatch")
    return {
        "artifact_path": str(source),
        "baseline_path": str(baseline),
        "source_sha256": digest,
        "baseline_sha256": hashlib.sha256(baseline.read_bytes()).hexdigest(),
        "as_of": end.isoformat(),
        "decision_as_of": decision.isoformat(),
        "ba": ba,
        "publication_time_verified": False,
        "ready_for_predictive_inference": False,
    }
