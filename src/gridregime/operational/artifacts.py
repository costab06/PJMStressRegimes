"""Content-addressed feature snapshot input shared by replay and OAF handlers."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from .contracts import FeatureSnapshot


def read_snapshots(path: str | Path, *, expected_sha256: str, allowed_root: str | Path | None = None) -> list[FeatureSnapshot]:
    if len(expected_sha256) != 64 or any(c not in '0123456789abcdef' for c in expected_sha256):
        raise ValueError('invalid snapshot artifact checksum')
    artifact = Path(path).resolve(strict=True)
    if allowed_root is not None:
        root = Path(allowed_root).resolve(strict=True)
        if not artifact.is_relative_to(root):
            raise PermissionError('snapshot path is outside configured input directory')
    if not artifact.is_file():
        raise ValueError('snapshot artifact must be a regular file')
    raw = artifact.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('snapshot artifact checksum mismatch')
    records = json.loads(raw)
    if not isinstance(records, list) or not records:
        raise ValueError('expected nonempty snapshot array')
    return [FeatureSnapshot(**record) for record in records]
