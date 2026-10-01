"""Event window extraction."""

from __future__ import annotations

import pandas as pd


def extract_window(
    df: pd.DataFrame,
    event_start: str,
    event_end: str,
    pre_hours: int = 72,
    post_hours: int = 72,
    ts_col: str = "timestamp_utc",
) -> pd.DataFrame:
    """Extract a time window around an event.

    Args:
        df: Full time-series DataFrame indexed or columned by ts_col.
        event_start: Event start as ISO-8601 string.
        event_end: Event end as ISO-8601 string.
        pre_hours: Hours before event_start to include.
        post_hours: Hours after event_end to include.
        ts_col: Timestamp column name.

    Returns:
        Sliced DataFrame with an added 'hours_to_event' column
        (negative = before, 0 = during, positive = after).
    """
    t0 = pd.Timestamp(event_start, tz="UTC")
    t1 = pd.Timestamp(event_end, tz="UTC")
    window_start = t0 - pd.Timedelta(hours=pre_hours)
    window_end = t1 + pd.Timedelta(hours=post_hours)

    mask = (df[ts_col] >= window_start) & (df[ts_col] <= window_end)
    out = df[mask].copy()
    out["hours_to_event"] = (out[ts_col] - t0).dt.total_seconds() / 3600
    return out.reset_index(drop=True)
