"""Event window visualization."""

from __future__ import annotations

from typing import Optional

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import pandas as pd


def plot_event_window(
    df: pd.DataFrame,
    event_start: str,
    event_end: str,
    y_col: str = "demand_mwh_clean",
    score_col: Optional[str] = None,
    controls: Optional[list[pd.DataFrame]] = None,
    ax: Optional[plt.Axes] = None,
    title: str = "",
) -> plt.Figure:
    """Plot an event window with optional anomaly scores and control overlays.

    Args:
        df: Event window DataFrame with timestamp_utc column.
        event_start: ISO-8601 event start.
        event_end: ISO-8601 event end.
        y_col: Column to plot on primary axis.
        score_col: Optional anomaly score column for secondary axis.
        controls: Optional list of control-period DataFrames.
        ax: Existing axes; creates new figure if None.
        title: Plot title.

    Returns:
        matplotlib Figure.
    """
    fig, ax1 = plt.subplots(figsize=(14, 5)) if ax is None else (ax.figure, ax)

    ax1.plot(df["timestamp_utc"], df[y_col], color="steelblue", linewidth=1.5, label="Event")

    if controls:
        for i, ctrl in enumerate(controls):
            ax1.plot(
                ctrl["timestamp_utc"],
                ctrl[y_col],
                color="gray",
                alpha=0.4,
                linewidth=0.8,
                label=f"Control {i+1}" if i == 0 else "_nolegend_",
            )

    t0 = pd.Timestamp(event_start, tz="UTC")
    t1 = pd.Timestamp(event_end, tz="UTC")
    ax1.axvspan(t0, t1, alpha=0.15, color="red", label="Event period")

    if score_col and score_col in df.columns:
        ax2 = ax1.twinx()
        ax2.plot(df["timestamp_utc"], df[score_col], color="darkorange", linewidth=1, linestyle="--")
        ax2.set_ylabel("Anomaly score", color="darkorange")

    ax1.set_xlabel("Time (UTC)")
    ax1.set_ylabel(y_col)
    ax1.set_title(title)
    ax1.legend(loc="upper left")
    fig.tight_layout()
    return fig
