"""Immutable EIA-930 snapshot revision ledger.

An observation-window identity can have multiple content hashes. The ledger
records when *our collector* first saw each version, not when EIA published it.
No entry is eligible as point-in-time evidence without source publication proof.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _utc(value: str) -> str:
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.tzinfo is None:
        raise ValueError("Revision observation time must be timezone-aware")
    return instant.astimezone(timezone.utc).isoformat()


def record_snapshot(*, ledger_dir: str | Path, ba: str, start: str, end: str,
                    sha256: str, observed_at: str) -> dict:
    """Append a collector-observed version using an immutable hash-named record.

    A pre-existing record must match exactly. Each snapshot version is stored
    separately so later revisions cannot overwrite historical content.
    """
    if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
        raise ValueError("Invalid artifact SHA-256")
    observed = _utc(observed_at)
    identity = hashlib.sha256(
        json.dumps([ba, start, end], separators=(",", ":")).encode()
    ).hexdigest()
    directory = Path(ledger_dir) / identity
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{sha256}.json"
    record = {
        "schema_version": 1, "source": "eia930", "ba": ba,
        "start": start, "end": end, "sha256": sha256,
        "collector_observed_at_utc": observed,
        "source_published_at_utc": None,
        "source_revision_at_utc": None,
        "publication_time_verified": False,
        "revision_history_verified": False,
    }
    encoded = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if target.exists():
        prior = json.loads(target.read_bytes())
        if prior != record:
            # The same artifact may be fetched again at a later time; retain
            # first-observed time without rewriting the original record.
            if {k: v for k, v in prior.items() if k != "collector_observed_at_utc"} != {
                k: v for k, v in record.items() if k != "collector_observed_at_utc"
            }:
                raise ValueError("Conflicting immutable revision ledger entry")
        return prior
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".revision-",
                                         delete=False) as f:
            f.write(encoded)
            tmp = Path(f.name)
        # Link avoids overwriting an existing entry when two workers race.
        try:
            os.link(tmp, target)
        except FileExistsError:
            prior = json.loads(target.read_bytes())
            if {k: v for k, v in prior.items() if k != "collector_observed_at_utc"} != {
                k: v for k, v in record.items() if k != "collector_observed_at_utc"
            }:
                raise ValueError("Conflicting concurrent revision ledger entry")
            return prior
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
    return record


def list_versions(*, ledger_dir: str | Path, ba: str, start: str, end: str) -> list[dict]:
    identity = hashlib.sha256(
        json.dumps([ba, start, end], separators=(",", ":")).encode()
    ).hexdigest()
    directory = Path(ledger_dir) / identity
    return sorted((json.loads(p.read_text()) for p in directory.glob("*.json")),
                  key=lambda r: (r["collector_observed_at_utc"], r["sha256"]))


def assert_point_in_time_eligible(record: dict, decision_as_of: str) -> None:
    """Reject collector timestamps as substitutes for source publication proof."""
    decision = _utc(decision_as_of)
    published = record.get("source_published_at_utc")
    if record.get("publication_time_verified") is not True or not published:
        raise ValueError("Source publication time is unverified")
    if _utc(published) > decision:
        raise ValueError("Source publication occurred after decision timestamp")
    if record.get("revision_history_verified") is not True:
        raise ValueError("Source revision history is unverified")
