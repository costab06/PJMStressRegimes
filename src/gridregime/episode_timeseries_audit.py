"""Audit frozen v1 PJM time-series coverage around independent episodes.

Input must contain precomputed, *validated* LoadZ, ForecastErrorZ, RampZ,
InterchangeZ and a timezone-aware timestamp_utc column. This script does not
recompute the frozen 2021 hour×month baseline, infer event severity, or train
a model. It audits alignment and summarizes descriptive pre-anchor trajectories.

Usage:
 python -m gridregime.episode_timeseries_audit --hourly data/processed/FEATURES.csv
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

FEATURES = ("LoadZ", "ForecastErrorZ", "RampZ", "InterchangeZ")


def _utc(value):
    if pd.isna(value) or str(value).strip() == "":
        return pd.NaT
    return pd.to_datetime(value, utc=True, errors="raise")


def episode_anchors(events: pd.DataFrame) -> pd.DataFrame:
    """One record per independent episode; never count repeated action days."""
    required = {"episode_id", "severity", "operator_action_time",
                "first_alert_time", "window_start"}
    missing = required - set(events.columns)
    if missing:
        raise ValueError(f"events_missing_columns:{sorted(missing)}")
    rows = []
    for episode, group in events.groupby("episode_id", sort=True, dropna=False):
        if pd.isna(episode) or not str(episode).strip():
            raise ValueError("missing_episode_id")
        severities = set(group["severity"].dropna())
        if len(severities) != 1:
            raise ValueError(f"inconsistent_episode_severity:{episode}")
        severity = next(iter(severities))
        if severity not in {"S1", "S2", "S3"}:
            raise ValueError(f"invalid_severity:{episode}")
        anchor_col = "operator_action_time" if severity == "S3" else "first_alert_time"
        candidates = [_utc(v) for v in group[anchor_col] if not pd.isna(v) and str(v).strip()]
        anchor = min(candidates) if candidates else pd.NaT
        rows.append({"episode_id": str(episode), "severity": severity,
                     "anchor_type": anchor_col if pd.notna(anchor) else "missing",
                     "anchor_utc": anchor,
                     "catalog_rows": len(group)})
    return pd.DataFrame(rows)


def audit_timeseries(hourly: pd.DataFrame, events: pd.DataFrame,
                     pre_hours: int = 24) -> dict:
    """Only complete, pre-anchor hourly data enter descriptive summaries."""
    if pre_hours < 2:
        raise ValueError("pre_hours_must_be_at_least_two")
    needed = {"timestamp_utc", *FEATURES}
    if needed - set(hourly.columns):
        raise ValueError(f"hourly_missing_columns:{sorted(needed - set(hourly.columns))}")
    frame = hourly.copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="raise")
    if frame["timestamp_utc"].isna().any():
        raise ValueError("invalid_hourly_timestamp")
    if frame["timestamp_utc"].duplicated().any():
        raise ValueError("duplicate_hourly_timestamp")
    for feature in FEATURES:
        frame[feature] = pd.to_numeric(frame[feature], errors="raise")
        frame[feature] = frame[feature].replace([np.inf, -np.inf], np.nan)
    frame = frame.set_index("timestamp_utc").sort_index()
    records = []
    for item in episode_anchors(events).to_dict("records"):
        anchor = item["anchor_utc"]
        record = {k: v for k, v in item.items() if k != "anchor_utc"}
        record["anchor_utc"] = anchor.isoformat() if pd.notna(anchor) else None
        record["pre_hours"] = pre_hours
        if pd.isna(anchor):
            record.update({"status": "missing_anchor", "observed_hours": 0,
                           "complete_hours": 0, "missing_hours": pre_hours})
            records.append(record)
            continue
        # Only fully elapsed hours strictly before the operator action/alert.
        end = anchor.floor("h")
        expected = pd.date_range(end=end - pd.Timedelta(hours=1),
                                 periods=pre_hours, freq="h", tz="UTC")
        window = frame.reindex(expected)[list(FEATURES)]
        valid = window.notna().all(axis=1)
        record.update({"observed_hours": int(window.notna().any(axis=1).sum()),
                       "complete_hours": int(valid.sum()),
                       "missing_hours": int((~valid).sum()),
                       "status": "complete" if valid.all() else "incomplete"})
        for feature in FEATURES:
            values = window[feature]
            record[f"{feature}_max_abs"] = (float(values.abs().max())
                                            if values.notna().any() else None)
            record[f"{feature}_start"] = (float(values.iloc[0])
                                           if pd.notna(values.iloc[0]) else None)
            record[f"{feature}_end"] = (float(values.iloc[-1])
                                         if pd.notna(values.iloc[-1]) else None)
            record[f"{feature}_delta"] = (
                float(values.iloc[-1] - values.iloc[0])
                if pd.notna(values.iloc[0]) and pd.notna(values.iloc[-1]) else None)
        records.append(record)
    return {"features": list(FEATURES), "pre_hours": pre_hours,
            "independent_episodes": len(records),
            "complete_episodes": sum(r["status"] == "complete" for r in records),
            "by_severity": {s: sum(r["severity"] == s for r in records)
                            for s in ("S1", "S2", "S3")},
            "episodes": records,
            "note": "Descriptive coverage only; no classification performance or independent-hour inference."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hourly", required=True, type=Path,
                        help="CSV of validated frozen-v1 hourly z-score features")
    parser.add_argument("--events", type=Path, default=Path("metadata/events.csv"))
    parser.add_argument("--pre-hours", type=int, default=24)
    parser.add_argument("--output", type=Path,
                        default=Path("results/episode-timeseries-audit.json"))
    args = parser.parse_args()
    result = audit_timeseries(pd.read_csv(args.hourly), pd.read_csv(args.events),
                              pre_hours=args.pre_hours)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "episodes"}, indent=2))


if __name__ == "__main__":
    main()
