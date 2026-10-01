"""Changepoint detection using ruptures."""

from __future__ import annotations

import numpy as np
import pandas as pd
import ruptures as rpt


def detect(
    series: pd.Series,
    model: str = "rbf",
    penalty: float = 10.0,
    min_size: int = 24,
) -> list[int]:
    """Detect changepoints in a univariate series.

    Args:
        series: 1-D time series (hourly).
        model: ruptures cost model ('rbf', 'l2', 'l1').
        penalty: Penalty parameter for PELT algorithm.
        min_size: Minimum segment size in samples.

    Returns:
        List of changepoint indices (sample positions, 1-indexed as ruptures convention).
    """
    signal = series.to_numpy().reshape(-1, 1)
    algo = rpt.Pelt(model=model, min_size=min_size).fit(signal)
    return algo.predict(pen=penalty)


def changepoints_to_timestamps(
    indices: list[int],
    index: pd.DatetimeIndex,
) -> list[pd.Timestamp]:
    """Convert ruptures sample indices to timestamps."""
    return [index[i - 1] for i in indices if i < len(index)]
