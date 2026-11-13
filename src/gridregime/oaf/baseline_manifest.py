"""Pinned baseline manifest for reproducible frozen-v1 feature execution.

A manifest records the exact approved bytes and reference-period declaration.
It does not independently certify that the baseline is scientifically valid.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def verify_baseline_manifest(*, baseline_path: str | Path,
                             manifest_path: str | Path) -> dict:
    baseline_path = Path(baseline_path)
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = ("schema_version", "feature_version", "sha256",
                "reference_period_start_utc", "reference_period_end_utc",
                "approval_id")
    if any(not manifest.get(key) for key in required):
        raise ValueError("Baseline manifest missing required provenance or approval fields")
    if manifest["schema_version"] != 1 or manifest["feature_version"] != "frozen-v1":
        raise ValueError("Unsupported baseline manifest version")
    if not isinstance(manifest["sha256"], str) or len(manifest["sha256"]) != 64:
        raise ValueError("Invalid baseline SHA-256")
    if not isinstance(manifest["approval_id"], str) or not manifest["approval_id"].strip():
        raise ValueError("Missing baseline approval identifier")
    import pandas as pd
    start = pd.Timestamp(manifest["reference_period_start_utc"])
    end = pd.Timestamp(manifest["reference_period_end_utc"])
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("Baseline reference period must be ordered and timezone-aware")
    digest = hashlib.sha256(baseline_path.read_bytes()).hexdigest()
    if digest != manifest["sha256"]:
        raise ValueError("Frozen baseline does not match approved manifest checksum")
    return manifest
