"""Central validation figure: HMM state probabilities above operator action timeline.

Plots P(Z_t = k) for each regime k as a stacked area (or line) chart, with
vertical markers for each operator action from operator_actions.csv, colored
and ranked by severity_rank. The visual question: did the inferred state shift
before PJM began escalating?
"""

from __future__ import annotations

from typing import Optional

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

ACTION_COLORS = {1: "#f5a623", 2: "#d0021b", 3: "#7b0000"}
STATE_COLORS = ["#4e9af1", "#f1c84e", "#e05c5c", "#7ecf7e", "#b07ede"]


def plot_state_probs_with_actions(
    timestamps: pd.DatetimeIndex,
    state_probs: np.ndarray,
    actions: pd.DataFrame,
    event_id: Optional[str] = None,
    ax: Optional[plt.Axes] = None,
    title: str = "",
) -> plt.Figure:
    """Plot HMM state probabilities with operator action markers.

    Args:
        timestamps: Hourly DatetimeIndex aligned to state_probs rows.
        state_probs: Array of shape (T, K) — P(Z_t = k) from model.predict_proba
                     or HMM posterior decoding.
        actions: DataFrame from operator_actions.csv, filtered to one event_id.
                 Must have columns [timestamp, action_name, severity_rank].
        event_id: If given, shown in the title.
        ax: Existing axes; creates new figure if None.
        title: Override title string.

    Returns:
        matplotlib Figure.
    """
    n_states = state_probs.shape[1]
    fig, ax = plt.subplots(figsize=(16, 5)) if ax is None else (ax.figure, ax)

    # Stacked area: P(Z_t = k)
    ax.stackplot(
        timestamps,
        state_probs.T,
        labels=[f"State {k}" for k in range(n_states)],
        colors=STATE_COLORS[:n_states],
        alpha=0.75,
    )

    # Operator action markers
    actions = actions.copy()
    actions["timestamp"] = pd.to_datetime(actions["timestamp"], utc=True)
    for _, row in actions.sort_values("severity_rank").iterrows():
        rank = int(row["severity_rank"])
        color = ACTION_COLORS.get(rank, "#333333")
        ax.axvline(row["timestamp"], color=color, linewidth=1.5, linestyle="--", zorder=5)
        ax.text(
            row["timestamp"],
            0.97,
            row["action_name"],
            transform=ax.get_xaxis_transform(),
            rotation=90,
            va="top",
            ha="right",
            fontsize=7,
            color=color,
        )

    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1))
    ax.set_xlabel("Time (UTC)")
    ax.set_ylabel("P(Z_t = k)")
    ax.set_title(title or (f"HMM Regime Probabilities — {event_id}" if event_id else "HMM Regime Probabilities"))
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    return fig
