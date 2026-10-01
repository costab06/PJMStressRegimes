"""Lead time analysis: how far in advance can stress be detected?"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score


def lead_time_auc(
    scores: pd.Series,
    event_start: str,
    lead_hours: list[int] | None = None,
) -> pd.Series:
    """Compute ROC-AUC at each lead time before an event.

    Args:
        scores: Anomaly/stress scores with DatetimeIndex (UTC).
        event_start: Event start ISO-8601.
        lead_hours: Lead times to evaluate; defaults to [6,12,24,48,72].

    Returns:
        Series indexed by lead time in hours.
    """
    if lead_hours is None:
        lead_hours = [6, 12, 24, 48, 72]

    t0 = pd.Timestamp(event_start, tz="UTC")
    results = {}
    for h in lead_hours:
        cutoff = t0 - pd.Timedelta(hours=h)
        window = scores[scores.index <= cutoff].tail(h * 2)
        # Label: 1 if within h hours of event
        labels = (window.index >= (t0 - pd.Timedelta(hours=h))).astype(int)
        if labels.sum() == 0 or labels.sum() == len(labels):
            results[h] = float("nan")
        else:
            results[h] = roc_auc_score(labels, window.values)
    return pd.Series(results, name="roc_auc")
