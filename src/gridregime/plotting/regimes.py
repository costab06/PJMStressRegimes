"""Regime state visualization."""

from __future__ import annotations

from typing import Optional

import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np
import pandas as pd

STATE_COLORS = ["#4e9af1", "#f1c84e", "#e05c5c", "#7ecf7e", "#b07ede"]


def plot_regimes(
    df: pd.DataFrame,
    states: np.ndarray,
    y_col: str = "demand_mwh_clean",
    ts_col: str = "timestamp_utc",
    ax: Optional[plt.Axes] = None,
    title: str = "HMM Regimes",
) -> plt.Figure:
    """Plot time series with HMM regime state bands.

    Args:
        df: DataFrame with ts_col and y_col.
        states: Integer state array aligned to df rows.
        y_col: Column to plot.
        ts_col: Timestamp column.
        ax: Existing axes; creates new figure if None.
        title: Plot title.

    Returns:
        matplotlib Figure.
    """
    fig, ax = plt.subplots(figsize=(16, 5)) if ax is None else (ax.figure, ax)

    ax.plot(df[ts_col], df[y_col], color="black", linewidth=0.8, zorder=3)

    n_states = len(np.unique(states))
    for state in range(n_states):
        mask = states == state
        color = STATE_COLORS[state % len(STATE_COLORS)]
        ax.fill_between(
            df[ts_col],
            df[y_col].min(),
            df[y_col].max(),
            where=mask,
            alpha=0.25,
            color=color,
            label=f"State {state}",
        )

    ax.set_xlabel("Time (UTC)")
    ax.set_ylabel(y_col)
    ax.set_title(title)
    ax.legend(loc="upper right")
    fig.tight_layout()
    return fig
