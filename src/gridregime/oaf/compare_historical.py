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
import json
from pathlib import Path

import pandas as pd
from pandas.testing import assert_frame_equal

from gridregime.ingest.eia930 import fetch_window
from gridregime.oaf.eia930_agent import persist_eia_window


def compare_window(ba: str, start: str, end: str, output_dir: Path,
                   *, cache_dir: Path | None = None, offline: bool = False) -> dict:
    source_hashes = {}
    if offline:
        if cache_dir is None:
            raise ValueError("Offline comparison requires cache_dir")
        t0, t1 = pd.Timestamp(start), pd.Timestamp(end)
        if t0.tzinfo is not None or t1.tzinfo is not None or t1 < t0:
            raise ValueError("Use an ordered UTC window without timezone offsets")
        months = pd.period_range(t0.to_period("M"), t1.to_period("M"), freq="M")
        paths = [Path(cache_dir) / f"{ba}_{month}.parquet" for month in months]
        missing = [str(p) for p in paths if not p.is_file()]
        if missing:
            raise FileNotFoundError(f"Missing cached EIA-930 months: {missing}")
        original = pd.concat([pd.read_parquet(p) for p in paths], ignore_index=True)
        original["timestamp_utc"] = pd.to_datetime(original["timestamp_utc"], utc=True)
        if original["timestamp_utc"].duplicated().any():
            raise ValueError("Duplicate UTC timestamps in historical cache; resolve source revisions explicitly")
        original = original.sort_values("timestamp_utc")
        original = original.loc[original["timestamp_utc"].between(
            t0.tz_localize("UTC"), t1.tz_localize("UTC"))].reset_index(drop=True)
        source_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    else:
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
    report = {
        "ba": ba, "start": start, "end": end,
        "rows": len(stored), "sha256": digest, "artifact_path": str(artifact),
        "source_parquet_sha256": source_hashes,
        "validation": "ingestion-boundary-only",
    }
    (output_dir / f"comparison-{digest}.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ba", default="PJM")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument('--cache-dir', type=Path)
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    print(compare_window(args.ba, args.start, args.end, args.output_dir,
                         cache_dir=args.cache_dir, offline=args.offline))


if __name__ == "__main__":
    main()
