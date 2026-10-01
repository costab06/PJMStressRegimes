"""Exploratory event survey figure.

Produces a 4-panel plot per event (or a grid of events on a single figure)
showing raw demand, forecast error, ramp rate, and net interchange, all
aligned on hours_to_event. This is the Milestone 1A decision-point figure:
see what the underlying state trajectories look like before asking any model
to discover a regime.

Usage (from a notebook or script):

    from gridregime.plotting.event_survey import plot_event_survey
    import pandas as pd

    windows = pd.read_parquet("data/processed/event_windows.parquet")
    events  = pd.read_csv("metadata/events.csv")
    fig = plot_event_survey(windows, events)
    fig.savefig("results/figures/event_survey.png", dpi=150, bbox_inches="tight")
"""

from __future__ import annotations

from typing import Optional

import matplotlib.pyplot as plt
import matplotlib.lines as mlines
import numpy as np
import pandas as pd

# Events shown in the survey figure; order determines row/column layout
SURVEY_EVENT_IDS = [
    "E2022_ELL_23",   # Elliott Day 1
    "E2022_ELL_24",   # Elliott Day 2
    "C2018_COLD",     # 2018 cold snap
    "C2023_HEAT_27",  # 2023 heat Day 1
    "C2023_HEAT_28",  # 2023 heat Day 2
    "C2025_HEAT_23",  # 2025 heat Day 1
    "C2025_HEAT_24",  # 2025 heat Day 2
    "C2025_HEAT_25",  # 2025 heat Day 3
    "E2026_HEAT_02",  # 2026 heat emergency
]

# Visual properties by model_role
ROLE_COLOR = {"positive": "#d0021b", "hard_negative": "#4a90d9"}
ROLE_ALPHA = {"positive": 0.9, "hard_negative": 0.55}

_PANELS = [
    ("demand_mwh",     "Demand (MW)",          False),
    ("forecast_error", "Forecast error (MW)",  True),
    ("ramp",           "Ramp rate (MW/h)",      True),
    ("interchange_mwh","Net interchange (MW)", True),
]


def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Add derived columns needed by the figure."""
    df = df.copy().sort_values("hours_to_event")
    df["forecast_error"] = df["demand_mwh"] - df["forecast_mwh"]
    df["ramp"] = df["demand_mwh"].diff()
    # Zero out ramp across non-consecutive hours (gap detection)
    hour_gap = df["hours_to_event"].diff().abs() > 1.5
    df.loc[hour_gap, "ramp"] = float("nan")
    return df


def plot_event_survey(
    windows: pd.DataFrame,
    events: pd.DataFrame,
    event_ids: Optional[list[str]] = None,
    ncols: int = 3,
    hours_range: tuple[float, float] = (-72, 72),
    figsize_per_panel: tuple[float, float] = (4.5, 2.8),
) -> plt.Figure:
    """Plot 4-panel survey for a set of events, one column per event.

    Each column shows demand, forecast error, ramp, and interchange aligned on
    hours_to_event. Positive events (operator action taken) are plotted in red;
    hard-negative controls in blue. A vertical dashed line at t=0 marks the
    operator_action_time for positive events (or window_start for controls).

    Args:
        windows: Combined event windows DataFrame from event_windows.parquet.
                 Must have [event_id, hours_to_event, demand_mwh, forecast_mwh,
                 interchange_mwh].
        events: events.csv as DataFrame with [event_id, event_name, model_role].
        event_ids: Subset of event_ids to plot; defaults to SURVEY_EVENT_IDS.
        ncols: Number of event columns per row.
        hours_range: X-axis limits in hours_to_event.
        figsize_per_panel: (width, height) per individual panel in inches.

    Returns:
        matplotlib Figure.
    """
    if event_ids is None:
        event_ids = [eid for eid in SURVEY_EVENT_IDS if eid in windows["event_id"].unique()]

    n_panels = len(_PANELS)
    n_events = len(event_ids)
    ncols = min(ncols, n_events)
    nrows_events = int(np.ceil(n_events / ncols))
    total_rows = n_panels * nrows_events

    fig_w = figsize_per_panel[0] * ncols
    fig_h = figsize_per_panel[1] * total_rows
    fig, axes = plt.subplots(
        total_rows, ncols,
        figsize=(fig_w, fig_h),
        squeeze=False,
        sharex="col",
    )

    meta = events.set_index("event_id")

    for col_idx, event_id in enumerate(event_ids):
        row_group = col_idx // ncols
        col_in_group = col_idx % ncols

        ev = windows[windows["event_id"] == event_id]
        if ev.empty:
            continue
        ev = _prepare(ev)
        ev = ev[(ev["hours_to_event"] >= hours_range[0]) & (ev["hours_to_event"] <= hours_range[1])]

        role = meta.at[event_id, "model_role"] if event_id in meta.index else "hard_negative"
        color = ROLE_COLOR.get(role, "#555555")
        alpha = ROLE_ALPHA.get(role, 0.7)
        label = meta.at[event_id, "event_name"] if event_id in meta.index else event_id

        for panel_idx, (col, ylabel, zeroline) in enumerate(_PANELS):
            ax_row = row_group * n_panels + panel_idx
            ax = axes[ax_row][col_in_group]

            if col in ev.columns:
                ax.plot(ev["hours_to_event"], ev[col], color=color, alpha=alpha, linewidth=1.2)
            else:
                ax.text(0.5, 0.5, f"{col}\nnot available", transform=ax.transAxes,
                        ha="center", va="center", fontsize=8, color="gray")

            ax.axvline(0, color="black", linewidth=0.8, linestyle="--", alpha=0.6)
            if zeroline:
                ax.axhline(0, color="gray", linewidth=0.5, linestyle=":")

            ax.set_xlim(hours_range)
            ax.tick_params(labelsize=7)

            if col_in_group == 0:
                ax.set_ylabel(ylabel, fontsize=8)

            if panel_idx == 0:
                role_marker = "●" if role == "positive" else "○"
                ax.set_title(f"{role_marker} {label}", fontsize=8, color=color, pad=3)

            if ax_row == total_rows - 1:
                ax.set_xlabel("Hours to event", fontsize=8)

    # Turn off unused axes
    for col_idx in range(n_events, nrows_events * ncols):
        row_group = col_idx // ncols
        col_in_group = col_idx % ncols
        for panel_idx in range(n_panels):
            ax_row = row_group * n_panels + panel_idx
            axes[ax_row][col_in_group].set_visible(False)

    # Shared legend
    pos_line = mlines.Line2D([], [], color=ROLE_COLOR["positive"], label="Positive (action taken)")
    neg_line = mlines.Line2D([], [], color=ROLE_COLOR["hard_negative"], label="Hard negative (no action)")
    vline = mlines.Line2D([], [], color="black", linestyle="--", linewidth=0.8, label="t = 0 (action / window ref)")
    fig.legend(handles=[pos_line, neg_line, vline], loc="lower center",
               ncol=3, fontsize=8, bbox_to_anchor=(0.5, 0.0))

    fig.suptitle("Event Survey — Demand, Forecast Error, Ramp, Interchange", fontsize=10, y=1.01)
    fig.tight_layout(rect=[0, 0.03, 1, 1])
    return fig


def save_survey(fig: plt.Figure, out_dir: str | Path = "results/figures") -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "event_survey.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    print(f"Saved → {path}")
    return path
