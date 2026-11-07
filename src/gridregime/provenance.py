"""Deterministic input provenance for research workflows.

No dependency on OpenAgentFabric: scientific code remains independently usable.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable


def sha256_file(path: str | Path) -> str:
    """SHA-256 digest of exact file bytes."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    episode_id: str,
    research_spec: str | Path,
    inputs: Iterable[str | Path],
    *,
    code_revision: str | None = None,
) -> dict:
    """Produce a stable provenance fingerprint from an episode and input files.

    Use stable, preferably project-relative paths across machines because input
    path strings are included as logical identifiers in the fingerprint.
    """
    if not episode_id.strip():
        raise ValueError("episode_id must not be empty")
    files: dict[str, str] = {}
    for input_path in inputs:
        key = str(input_path)
        if key in files:
            raise ValueError(f"duplicate input path: {key}")
        files[key] = sha256_file(input_path)
    payload = {
        "schema_version": 1,
        "episode_id": episode_id,
        "research_spec_sha256": sha256_file(research_spec),
        "inputs": dict(sorted(files.items())),
        "code_revision": code_revision,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload["fingerprint_sha256"] = hashlib.sha256(canonical).hexdigest()
    return payload
