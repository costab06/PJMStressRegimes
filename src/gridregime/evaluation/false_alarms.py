"""False alarm rate analysis."""

from __future__ import annotations

import pandas as pd


def false_alarm_rate(
    predictions: pd.Series,
    true_events: list[tuple[str, str]],
    threshold: float = 0.5,
    min_gap_hours: int = 24,
) -> dict:
    """Compute false alarm rate given a list of true event windows.

    Args:
        predictions: Binary or probabilistic predictions with DatetimeIndex.
        true_events: List of (start, end) ISO-8601 tuples for true events.
        threshold: Decision threshold for probabilistic predictions.
        min_gap_hours: Minimum gap to merge consecutive alarms into one.

    Returns:
        Dict with keys: n_true_events, n_detected, n_false_alarms, false_alarm_rate.
    """
    binary = (predictions >= threshold).astype(int)

    # Build true event mask
    event_mask = pd.Series(False, index=predictions.index)
    for start, end in true_events:
        t0 = pd.Timestamp(start, tz="UTC")
        t1 = pd.Timestamp(end, tz="UTC")
        event_mask |= (predictions.index >= t0) & (predictions.index <= t1)

    tp = int((binary & event_mask).sum())
    fp = int((binary & ~event_mask).sum())
    n_true = len(true_events)
    n_detected = min(tp, n_true)

    return {
        "n_true_events": n_true,
        "n_detected": n_detected,
        "n_false_alarms": fp,
        "false_alarm_rate": fp / max(1, fp + int((~binary & ~event_mask).sum())),
    }
