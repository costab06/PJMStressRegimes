"""Content-addressed feature snapshot input shared by replay and OAF handlers."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from .contracts import FeatureSnapshot


def read_snapshots(path: str | Path, *, expected_sha256: str) -> list[FeatureSnapshot]:
    if len(expected_sha256) != 64 or any(c not in '0123456789abcdef' for c in expected_sha256):
        raise ValueError('invalid snapshot artifact checksum')
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('snapshot artifact checksum mismatch')
    records = json.loads(raw)
    if not isinstance(records, list) or not records:
        raise ValueError('expected nonempty snapshot array')
    return [FeatureSnapshot(**record) for record in records]
