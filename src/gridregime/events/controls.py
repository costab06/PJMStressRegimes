"""Control period matching for event comparison."""

from __future__ import annotations

from typing import Iterator

import pandas as pd


def iter_control_windows(
    df: pd.DataFrame,
    event_start: str,
    event_end: str,
    n_prior_years: int = 5,
    pre_hours: int = 72,
    post_hours: int = 72,
    ts_col: str = "timestamp_utc",
) -> Iterator[tuple[int, pd.DataFrame]]:
    """Yield same-calendar-window from N prior years as control periods.

    Args:
        df: Full time-series DataFrame.
        event_start: Event start ISO-8601.
        event_end: Event end ISO-8601.
        n_prior_years: Number of prior years to yield.
        pre_hours: Hours before window start to include.
        post_hours: Hours after window end to include.
        ts_col: Timestamp column name.

    Yields:
        (year_offset, sliced_df) tuples.
    """
    from gridregime.events.windows import extract_window

    t0 = pd.Timestamp(event_start, tz="UTC")
    t1 = pd.Timestamp(event_end, tz="UTC")

    for offset in range(1, n_prior_years + 1):
        ctrl_start = t0 - pd.DateOffset(years=offset)
        ctrl_end = t1 - pd.DateOffset(years=offset)
        try:
            window = extract_window(df, str(ctrl_start), str(ctrl_end), pre_hours, post_hours, ts_col)
            yield offset, window
        except Exception:
            continue
