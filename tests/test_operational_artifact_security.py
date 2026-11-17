"""Security regressions for snapshot path confinement."""
import hashlib
import json

import pytest

from gridregime.operational.artifacts import read_snapshots


def test_snapshot_path_outside_input_root_is_rejected(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.json"
    raw = json.dumps([{"example": True}]).encode()
    outside.write_bytes(raw)
    with pytest.raises(PermissionError, match="outside configured input directory"):
        read_snapshots(outside, expected_sha256=hashlib.sha256(raw).hexdigest(), allowed_root=allowed)


def test_symlink_escape_is_rejected(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.json"
    raw = b"[]"
    outside.write_bytes(raw)
    (allowed / "link.json").symlink_to(outside)
    with pytest.raises(PermissionError, match="outside configured input directory"):
        read_snapshots(allowed / "link.json", expected_sha256=hashlib.sha256(raw).hexdigest(), allowed_root=allowed)


def test_allowed_file_reaches_existing_validation(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    file = allowed / "snapshots.json"
    raw = b"[]"
    file.write_bytes(raw)
    with pytest.raises(ValueError, match="nonempty snapshot array"):
        read_snapshots(file, expected_sha256=hashlib.sha256(raw).hexdigest(), allowed_root=allowed)
