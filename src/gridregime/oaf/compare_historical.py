"""Compare a historical EIA-930 window with its OAF-adapted artifact.

Usage:
    python -m gridregime.oaf.compare_historical \
        --start 2022-12-20T00 --end 2022-12-28T23 \
        --output-dir data/derived/oaf-validation

Requires EIA_API_KEY for uncached months, or an existing EIA-930 cache.
This checks the ingestion boundary only, not downstream feature equivalence.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import pandas as pd
from pandas.testing import assert_frame_equal

from gridregime.ingest.eia930 import fetch_window
from gridregime.oaf.eia930_agent import persist_eia_window


def compare_window(ba: str, start: str, end: str, output_dir: Path) -> dict:
    original = fetch_window(ba, start, end)
    # Compare against the same immutable in-memory source snapshot. Two
    # independent API calls can differ if EIA revises data between requests.
    result = persist_eia_window(
        ba=ba, start=start, end=end, output_dir=output_dir,
        fetcher=lambda _ba, _start, _end: original.copy(),
    )
    artifact = Path(result["artifact_path"])
    stored = pd.read_csv(artifact, parse_dates=["timestamp_utc"])
    expected = original.copy()
    expected["timestamp_utc"] = pd.to_datetime(expected["timestamp_utc"], utc=True)
    expected = expected.sort_values("timestamp_utc").reset_index(drop=True)
    stored = stored[expected.columns].reset_index(drop=True)
    # CSV may not preserve float binary representation exactly; numerical
    # differences must stay below a strict round-trip tolerance.
    assert_frame_equal(
        stored, expected, check_dtype=False, check_exact=False,
        rtol=1e-12, atol=1e-10,
    )
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert digest == result["sha256"]
    return {
        "ba": ba, "start": start, "end": end,
        "rows": len(stored), "sha256": digest, "artifact_path": str(artifact),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ba", default="PJM")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(compare_window(args.ba, args.start, args.end, args.output_dir))


if __name__ == "__main__":
    main()
