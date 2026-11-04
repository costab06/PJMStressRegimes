"""Z-scored event survey figures and phase portrait (Milestone 1B, second pass).

Produces five figures:
  fig5_load_z.png           LoadZ = (D - μ_{h,m}) / σ_{h,m}
  fig6_fe_z.png             ForecastErrorZ
  fig7_ramp3_z.png          RampZ (3-hour rate)
  fig8_ic_z.png             InterchangeZ
  fig9_phase_portrait.png   Trajectory in (FE_z, IC_z) from t=-24 to t=0

All figures use the same no-outcome-coloring convention as event_survey.py.
The phase portrait adds time markers at t = -24, -12, -6, -3, -1, 0.

Usage:
    python -m gridregime.plotting.survey_z
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve()
PROJECT_ROOT = _HERE.parents[3]

INTERIM_DIR   = PROJECT_ROOT / "data" / "interim" / "eia930"
BASELINE_PATH = PROJECT_ROOT / "data" / "interim" / "baseline_PJM_2021.parquet"
EVENTS_CSV    = PROJECT_ROOT / "metadata" / "events.csv"
FIGURES_DIR   = PROJECT_ROOT / "results" / "figures"
TABLES_DIR    = PROJECT_ROOT / "results" / "tables"

T_MIN = -72
T_MAX = +12

import matplotlib.cm as _cm
_COLORS = [_cm.tab20(i / 20) for i in range(20)]
_LINE_KW  = dict(linewidth=1.3, alpha=0.85)
# Phase portrait markers at these t values
_PHASE_MARKS = [-24, -12, -6, -3, -1, 0]


# ---------------------------------------------------------------------------
# Reuse alignment logic from event_survey
# ---------------------------------------------------------------------------

def _load_events() -> pd.DataFrame:
    df = pd.read_csv(EVENTS_CSV)
    for col in ["window_start", "event_end", "operator_action_time"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
    return df


def _peak_demand_ts(interim_df: pd.DataFrame,
                    window_start: pd.Timestamp,
                    event_end: pd.Timestamp) -> pd.Timestamp:
    mask = ((interim_df["timestamp_utc"] >= window_start) &
            (interim_df["timestamp_utc"] <= event_end))
    sub = interim_df[mask].dropna(subset=["demand_mwh"])
    if sub.empty:
        raise ValueError("No demand data for peak alignment")
    return sub.loc[sub["demand_mwh"].idxmax(), "timestamp_utc"]


def load_aligned_z(events: pd.DataFrame, baseline: pd.DataFrame
                   ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load and z-score all event windows.

    Returns (aligned_z, meta) where aligned_z has z-scored columns.
    """
    from gridregime.features.seasonal import apply_zscore

    frames: list[pd.DataFrame] = []
    meta_rows: list[dict] = []

    for _, ev in events.iterrows():
        eid = ev["event_id"]
        path = INTERIM_DIR / f"{eid}.parquet"
        if not path.exists():
            print(f"  SKIP {eid}: interim parquet not found")
            continue

        df = pd.read_parquet(path).sort_values("timestamp_utc").reset_index(drop=True)

        if ev["model_role"] == "positive" and pd.notna(ev.get("operator_action_time")):
            t0 = ev["operator_action_time"]
            alignment_type = "operator_action"
        else:
            t0 = _peak_demand_ts(df, ev["window_start"], ev["event_end"])
            alignment_type = "peak_demand"

        df["t"] = (df["timestamp_utc"] - t0).dt.total_seconds() / 3600
        df = df[(df["t"] >= T_MIN) & (df["t"] <= T_MAX)].copy()
        if df.empty:
            continue

        df = apply_zscore(df, baseline)
        df["event_id"] = eid

        frames.append(df[[
            "event_id", "t", "timestamp_utc",
            "demand_mwh", "forecast_mwh", "interchange_mwh",
            "forecast_error_pct", "ramp_3h",
            "load_z", "fe_z", "ramp3_z", "ic_z",
        ]])
        meta_rows.append({
            "event_id":       eid,
            "episode_id":     ev.get("episode_id", eid),
            "model_role":     ev["model_role"],
            "alignment_type": alignment_type,
            "t0_utc":         t0.isoformat(),
        })

    aligned = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    meta    = pd.DataFrame(meta_rows)
    return aligned, meta


# ---------------------------------------------------------------------------
# Figure helpers
# ---------------------------------------------------------------------------

def _new_fig(ylabel: str, title: str) -> tuple[plt.Figure, plt.Axes]:
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.axvline(0, color="black", linewidth=1.0, linestyle="--", zorder=5)
    ax.axhline(0, color="gray",  linewidth=0.6, linestyle=":",  zorder=1)
    ax.set_xlabel("Hours relative to t = 0", fontsize=11)
    ax.set_ylabel(ylabel, fontsize=11)
    ax.set_title(title, fontsize=12, pad=8)
    ax.set_xlim(T_MIN - 1, T_MAX + 1)
    ax.xaxis.set_major_locator(mticker.MultipleLocator(12))
    ax.xaxis.set_minor_locator(mticker.MultipleLocator(6))
    ax.grid(True, which="major", linestyle=":", linewidth=0.5, alpha=0.5)
    ax.grid(True, which="minor", linestyle=":", linewidth=0.25, alpha=0.3)
    return fig, ax


def _legend_label(meta: pd.DataFrame, eid: str) -> str:
    row = meta[meta["event_id"] == eid]
    if row.empty:
        return eid
    return f"{eid}  [peak]" if row.iloc[0]["alignment_type"] == "peak_demand" else eid


def _save(fig: plt.Figure, name: str) -> Path:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    path = FIGURES_DIR / name
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def _plot_z(aligned: pd.DataFrame, meta: pd.DataFrame,
            col: str, ax: plt.Axes) -> None:
    for i, (eid, grp) in enumerate(aligned.groupby("event_id", sort=False)):
        grp = grp.sort_values("t")
        ax.plot(grp["t"], grp[col],
                color=_COLORS[i % len(_COLORS)],
                label=_legend_label(meta, eid),
                **_LINE_KW)


# ---------------------------------------------------------------------------
# The four z-scored time-series figures
# ---------------------------------------------------------------------------

def fig_load_z(aligned: pd.DataFrame, meta: pd.DataFrame) -> Path:
    fig, ax = _new_fig(
        ylabel=r"$LoadZ_t = (D_t - \mu_{h,m})\,/\,\sigma_{h,m}$",
        title="Fig 5 — Seasonally normalised demand (LoadZ)\nbaseline: 2021 PJM, conditioned on hour-of-day × month",
    )
    _plot_z(aligned, meta, "load_z", ax)
    ax.legend(fontsize=8.5, loc="lower left", framealpha=0.85, ncol=2)
    fig.tight_layout()
    return _save(fig, "fig5_load_z.png")


def fig_fe_z(aligned: pd.DataFrame, meta: pd.DataFrame) -> Path:
    fig, ax = _new_fig(
        ylabel=r"$ForecastErrorZ_t$",
        title="Fig 6 — Forecast error Z-score",
    )
    _plot_z(aligned, meta, "fe_z", ax)
    ax.legend(fontsize=8.5, loc="lower left", framealpha=0.85, ncol=2)
    fig.tight_layout()
    return _save(fig, "fig6_fe_z.png")


def fig_ramp_z(aligned: pd.DataFrame, meta: pd.DataFrame) -> Path:
    fig, ax = _new_fig(
        ylabel=r"$RampZ_t$  (3-hour rate)",
        title="Fig 7 — 3-hour ramp rate Z-score",
    )
    _plot_z(aligned, meta, "ramp3_z", ax)
    ax.legend(fontsize=8.5, loc="lower left", framealpha=0.85, ncol=2)
    fig.tight_layout()
    return _save(fig, "fig7_ramp3_z.png")


def fig_ic_z(aligned: pd.DataFrame, meta: pd.DataFrame) -> Path:
    fig, ax = _new_fig(
        ylabel=r"$InterchangeZ_t$",
        title="Fig 8 — Net interchange Z-score",
    )
    _plot_z(aligned, meta, "ic_z", ax)
    ax.legend(fontsize=8.5, loc="lower left", framealpha=0.85, ncol=2)
    fig.tight_layout()
    return _save(fig, "fig8_ic_z.png")


# ---------------------------------------------------------------------------
# Figure 9 — Phase portrait in (FE_z, IC_z)
# ---------------------------------------------------------------------------

def fig_phase_portrait(aligned: pd.DataFrame, meta: pd.DataFrame) -> Path:
    """Trajectory per event in (ForecastErrorZ, InterchangeZ) from t=-24 to t=0."""
    fig, ax = plt.subplots(figsize=(9, 7))
    ax.axhline(0, color="gray", linewidth=0.6, linestyle=":", zorder=1)
    ax.axvline(0, color="gray", linewidth=0.6, linestyle=":", zorder=1)

    # Shade quadrants lightly
    xlim = (-4, 6)
    ylim = (-4, 6)

    window = aligned[(aligned["t"] >= -24) & (aligned["t"] <= 0)].copy()

    for i, (eid, grp) in enumerate(window.groupby("event_id", sort=False)):
        grp = grp.sort_values("t").dropna(subset=["fe_z", "ic_z"])
        if grp.empty:
            continue
        color = _COLORS[i % len(_COLORS)]
        lbl   = _legend_label(meta, eid)

        ax.plot(grp["fe_z"], grp["ic_z"],
                color=color, linewidth=1.4, alpha=0.8, zorder=3)

        # Arrow showing direction of time (midpoint → midpoint+1)
        mid = len(grp) // 2
        if mid + 1 < len(grp):
            ax.annotate("",
                xy=(grp["fe_z"].iloc[mid + 1], grp["ic_z"].iloc[mid + 1]),
                xytext=(grp["fe_z"].iloc[mid], grp["ic_z"].iloc[mid]),
                arrowprops=dict(arrowstyle="->", color=color, lw=1.2),
                zorder=4,
            )

        # Time markers at _PHASE_MARKS
        for mark_t in _PHASE_MARKS:
            near = grp.iloc[(grp["t"] - mark_t).abs().argsort().iloc[:1]]
            if (grp["t"] - mark_t).abs().min() > 1.5:
                continue
            mx, my = float(near["fe_z"].iloc[0]), float(near["ic_z"].iloc[0])
            size = 80 if mark_t == 0 else 35
            marker = "*" if mark_t == 0 else "o"
            ax.scatter(mx, my, color=color, s=size, marker=marker,
                       zorder=5, edgecolors="white", linewidths=0.5)
            if mark_t in (-24, -12, 0):
                ax.annotate(f"t={mark_t:+d}h",
                            xy=(mx, my), xytext=(4, 4),
                            textcoords="offset points",
                            fontsize=6.5, color=color, zorder=6)

        # Legend proxy — last point label
        ax.plot([], [], color=color, linewidth=1.4, label=lbl)

    ax.set_xlabel(r"$ForecastErrorZ_t$", fontsize=12)
    ax.set_ylabel(r"$InterchangeZ_t$", fontsize=12)
    ax.set_title(
        "Fig 9 — Phase portrait: (ForecastErrorZ, InterchangeZ)\n"
        "Trajectory t = −24h → t = 0   ·   ★ marks t = 0",
        fontsize=12, pad=8,
    )

    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    ax.grid(True, linestyle=":", linewidth=0.5, alpha=0.5)
    ax.legend(fontsize=8.5, loc="upper left", framealpha=0.85)

    # Quadrant labels (small, gray)
    kw = dict(fontsize=8, color="lightgray", ha="center", va="center",
              transform=ax.transAxes, zorder=0)
    ax.text(0.22, 0.83, "Under-\nforecast\nHigh import",  **kw)
    ax.text(0.78, 0.83, "Over-\nforecast\nHigh import",   **kw)
    ax.text(0.22, 0.17, "Under-\nforecast\nLow import",   **kw)
    ax.text(0.78, 0.17, "Over-\nforecast\nLow import",    **kw)

    fig.tight_layout()
    return _save(fig, "fig9_phase_portrait.png")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run() -> None:
    from gridregime.features.seasonal import build_baseline, save_baseline, load_baseline

    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    events = _load_events()

    # Load or build baseline
    baseline_cache = PROJECT_ROOT / "data" / "interim" / "seasonal_baseline.parquet"
    if baseline_cache.exists():
        print("Loading cached seasonal baseline...")
        baseline = load_baseline(baseline_cache)
    elif BASELINE_PATH.exists():
        print("Building seasonal baseline from 2021 PJM data...")
        baseline = build_baseline([BASELINE_PATH])
        save_baseline(baseline, baseline_cache)
        n_cells = len(baseline)
        min_n   = int(baseline["n"].min())
        print(f"  {n_cells} (hour, month) cells  |  min samples per cell: {min_n}")
    else:
        raise FileNotFoundError(
            f"Baseline data not found at {BASELINE_PATH}.\n"
            "Run the baseline download first:\n"
            "  python scripts/download_baseline.py"
        )

    aligned, meta = load_aligned_z(events, baseline)
    print(f"Z-scored {aligned['event_id'].nunique()} events  ({len(aligned)} rows)")

    p5  = fig_load_z(aligned, meta)
    p6  = fig_fe_z(aligned, meta)
    p7  = fig_ramp_z(aligned, meta)
    p8  = fig_ic_z(aligned, meta)
    p9  = fig_phase_portrait(aligned, meta)
    for p in (p5, p6, p7, p8, p9):
        print(f"  → {p.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    run()
