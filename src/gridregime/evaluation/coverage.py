"""Coverage utilities for event_data_coverage.csv.

Separated from the pipeline runner so notebooks can recompute coverage
against an already-fetched event_windows.parquet without re-ingesting.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


REQUIRED_COLS = ["demand_mwh", "forecast_mwh", "interchange_mwh"]
OPTIONAL_COLS = ["generation_mwh", "weather_hours"]


def coverage_from_windows(
    windows: pd.DataFrame,
    events: pd.DataFrame,
    pre_hours: int = 72,
    post_hours: int = 72,
) -> pd.DataFrame:
    """Compute event_data_coverage from a combined event-windows DataFrame.

    Args:
        windows: Output of milestone_1a.run() — must have [event_id, timestamp_utc,
                 demand_mwh, forecast_mwh, generation_mwh, interchange_mwh].
        events: events.csv as a DataFrame with [event_id, window_start, event_end].
        pre_hours: Hours before window_start included in the analysis window.
        post_hours: Hours after event_end included in the analysis window.

    Returns:
        DataFrame matching the event_data_coverage.csv schema.
    """
    rows = []
    for _, event in events.iterrows():
        w = windows[windows["event_id"] == event["event_id"]]
        win_start = pd.Timestamp(event["window_start"], tz="UTC") - pd.Timedelta(hours=pre_hours)
        win_end = pd.Timestamp(event["event_end"], tz="UTC") + pd.Timedelta(hours=post_hours)
        expected = int((win_end - win_start).total_seconds() / 3600) + 1

        def _h(col: str) -> int:
            return int(w[col].notna().sum()) if col in w.columns else 0

        demand_h = _h("demand_mwh")
        forecast_h = _h("forecast_mwh")
        generation_h = _h("generation_mwh")
        interchange_h = _h("interchange_mwh")
        weather_h = _h("temp_c")  # populated after NOAA ingest

        core_min = min(demand_h, forecast_h, interchange_h)
        missing_pct = round((1 - core_min / max(expected, 1)) * 100, 1)

        rows.append({
            "event_id": event["event_id"],
            "window_start": win_start.isoformat(),
            "window_end": win_end.isoformat(),
            "expected_hours": expected,
            "demand_hours": demand_h,
            "forecast_hours": forecast_h,
            "generation_hours": generation_h,
            "interchange_hours": interchange_h,
            "weather_hours": weather_h,
            "missing_pct": missing_pct,
        })
    return pd.DataFrame(rows)


def assert_coverage(coverage: pd.DataFrame, max_missing_pct: float = 5.0) -> None:
    """Raise if any event has more than max_missing_pct core data missing.

    Call this as a pipeline gate before feature engineering.
    """
    bad = coverage[coverage["missing_pct"] > max_missing_pct]
    if not bad.empty:
        lines = bad[["event_id", "missing_pct"]].to_string(index=False)
        raise RuntimeError(
            f"Coverage gate failed — {len(bad)} event(s) exceed {max_missing_pct}% missing:\n{lines}"
        )


def load_coverage(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)
