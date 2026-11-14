"""Audit 2021 source anomalies and build a reproducible descriptive baseline.

Run: python -m gridregime.pipeline.freeze_reference_2021
This writes an audit, a candidate baseline and provenance; it does NOT approve
the baseline for operational workers or establish point-in-time eligibility.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from gridregime.features.seasonal import build_baseline, save_baseline

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "data/raw/eia930"
OUT = ROOT / "data/processed"
STATS = ("demand_mean", "demand_std", "fe_mean", "fe_std",
         "ramp3_mean", "ramp3_std", "ic_mean", "ic_std")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run() -> dict:
    paths = [RAW / f"PJM_2021-{month:02d}.parquet" for month in range(1, 13)]
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing reference months: {missing}")
    frames = []
    for path in paths:
        frame = pd.read_parquet(path)
        for col in ("timestamp_utc", "demand_mwh", "forecast_mwh", "interchange_mwh"):
            if col not in frame:
                raise ValueError(f"{path.name}: missing {col}")
        frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
        frames.append(frame)
    raw = pd.concat(frames, ignore_index=True).sort_values("timestamp_utc")
    expected = pd.date_range("2021-01-01T00:00Z", "2021-12-31T23:00Z", freq="h")
    if not pd.DatetimeIndex(raw["timestamp_utc"]).equals(expected):
        raise ValueError("2021 reference timestamps are missing, duplicated or out of order")
    if raw[["demand_mwh", "forecast_mwh", "interchange_mwh"]].isna().any().any():
        raise ValueError("Null required observations in reference year")
    bad = ~raw["demand_mwh"].between(10_000, 200_000)
    exclusions = raw.loc[bad, ["timestamp_utc", "demand_mwh", "forecast_mwh",
                                "interchange_mwh"]].copy()
    exclusions["reason"] = "demand outside predefined plausible PJM range [10000, 200000] MW"
    exclusions["action"] = "excluded from baseline statistics; raw cache retained"
    OUT.mkdir(parents=True, exist_ok=True)
    audit_path = OUT / "baseline_2021_exclusions.csv"
    exclusions.to_csv(audit_path, index=False)
    baseline = build_baseline(paths)
    if len(baseline) != 288 or baseline[list(STATS)].isna().any().any():
        raise ValueError("Incomplete seasonal baseline")
    std_cols = [c for c in STATS if c.endswith("_std")]
    if not (baseline[std_cols] > 0).all().all():
        raise ValueError("Nonpositive baseline standard deviation")
    if baseline["n"].min() < 20:
        raise ValueError("Insufficient reference observations per cell")
    baseline_path = OUT / "baseline_2021_frozen_v1.parquet"
    save_baseline(baseline, baseline_path)
    provenance = {
        "schema_version": 1, "feature_version": "frozen-v1",
        "status": "candidate-not-approved",
        "reference_period_start_utc": "2021-01-01T00:00:00Z",
        "reference_period_end_utc": "2022-01-01T00:00:00Z",
        "reference_hours": len(raw), "excluded_demand_hours": int(bad.sum()),
        "excluded_timestamps_utc": [x.isoformat() for x in exclusions["timestamp_utc"]],
        "exclusion_audit": str(audit_path.relative_to(ROOT)),
        "exclusion_audit_sha256": sha256(audit_path),
        "source_month_sha256": {p.name: sha256(p) for p in paths},
        "baseline_path": str(baseline_path.relative_to(ROOT)),
        "baseline_sha256": sha256(baseline_path),
        "cell_count": len(baseline), "minimum_cell_n": int(baseline["n"].min()),
        "publication_time_verified": False,
        "revision_history_verified": False,
        "scientific_approval": None,
        "notes": "Demand outliers excluded before ramp computation; ramp spanning invalid interval is undefined. One-year baseline is exploratory.",
    }
    provenance_path = OUT / "baseline_2021_provenance.json"
    provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    print(f"Audit: {audit_path} ({len(exclusions)} exclusions)")
    print(f"Candidate baseline: {baseline_path} ({len(baseline)} cells)")
    print(f"Provenance: {provenance_path}")
    print(f"SHA-256: {provenance['baseline_sha256']}")
    return provenance


if __name__ == "__main__":
    run()
