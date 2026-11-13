"""Baseline approval manifest verification regression tests."""
import hashlib
import json

import pytest

from gridregime.oaf.baseline_manifest import verify_baseline_manifest


def manifest(tmp_path):
    baseline = tmp_path / "frozen.parquet"
    baseline.write_bytes(b"frozen-reference")
    record = {
        "schema_version": 1,
        "feature_version": "frozen-v1",
        "sha256": hashlib.sha256(baseline.read_bytes()).hexdigest(),
        "reference_period_start_utc": "2021-01-01T00:00:00Z",
        "reference_period_end_utc": "2022-01-01T00:00:00Z",
        "approval_id": "research-review-001",
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(record))
    return baseline, path, record


def test_valid_baseline_manifest(tmp_path):
    baseline, path, record = manifest(tmp_path)
    assert verify_baseline_manifest(
        baseline_path=baseline, manifest_path=path,
    ) == record


def test_tampered_baseline_is_rejected(tmp_path):
    baseline, path, _ = manifest(tmp_path)
    baseline.write_bytes(b"modified")
    with pytest.raises(ValueError, match="checksum"):
        verify_baseline_manifest(baseline_path=baseline, manifest_path=path)


def test_missing_approval_is_rejected(tmp_path):
    baseline, path, record = manifest(tmp_path)
    record["approval_id"] = ""
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="approval"):
        verify_baseline_manifest(baseline_path=baseline, manifest_path=path)


def test_naive_reference_period_is_rejected(tmp_path):
    baseline, path, record = manifest(tmp_path)
    record["reference_period_start_utc"] = "2021-01-01"
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="timezone-aware"):
        verify_baseline_manifest(baseline_path=baseline, manifest_path=path)
