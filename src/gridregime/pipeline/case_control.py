"""Case-control matched comparison: S3 episode vs season-matched controls.

Matches each S3 episode to its meteorologically comparable hard-negative
controls (same season), then overlays their z-scored trajectories in the
final 24 h window. The control envelope (min/max shading + mean) makes it
immediately visible whether and when the S3 episode diverges.

Matched groups
--------------
  WINTER  ELL_2022 (S3) vs COLD_2018, POLAR_2019, COLD_2025, COLD_2026
  SUMMER  HEAT_2026 (S3) vs HEAT_2023, HEAT_2024, HEAT_2025,
                              HEAT_2025_JUL, HEAT_2026_SEP

Output figures
--------------
  fig17_cc_winter.png   4-panel time series  (LoadZ, FE_Z, RampZ, IC_Z)
  fig18_cc_summer.png   same for summer group
  fig19_cc_phase.png    Phase portrait (FE_Z, IC_Z) for both groups
  fig20_cc_divergence.png  Hour-by-hour divergence of S3 from control mean

Output table
------------
  results/tables/case_control_summary.csv

Usage
-----
    python -m gridregime.pipeline.case_control
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

EVENTS_CSV = PROJECT_ROOT / "metadata" / "events.csv"
FIGURES_DIR = PROJECT_ROOT / "results" / "figures"
TABLES_DIR  = PROJECT_ROOT / "results" / "tables"

T_LO, T_HI = -24.0, 0.0   # comparison window

# Matched groups: (case_episode, [control_episodes], season_label)
GROUPS = [
    (
        "ELL_2022",
        ["COLD_2018", "POLAR_2019", "COLD_2025", "COLD_2026"],
        "Winter",
    ),
    (
        "HEAT_2026",
        ["HEAT_2023", "HEAT_2024", "HEAT_2025", "HEAT_2025_JUL", "HEAT_2026_SEP"],
        "Summer",
    ),
]

FEATURES = [
    ("load_z",   r"$LoadZ$",           "#2166ac"),
    ("fe_z",     r"$ForecastErrorZ$",  "#4dac26"),
    ("ramp3_z",  r"$RampZ$  (3h)",     "#d6604d"),
    ("ic_z",     r"$InterchangeZ$",    "#7b2d8b"),
]

_CASE_KW    = dict(color="#d62728", linewidth=2.5, zorder=5)
_CTRL_MEAN_KW = dict(color="steelblue", linewidth=1.5, linestyle="--", zorder=3)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def _load_events() -> pd.DataFrame:
    df = pd.read_csv(EVENTS_CSV)
    for col in ["window_start", "event_end", "operator_action_time"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
    return df


def load_obs(events: pd.DataFrame, baseline: pd.DataFrame) -> pd.DataFrame:
    """Z-scored observations deduped to (episode_id, t)."""
    from gridregime.plotting.survey_z import load_aligned_z

    aligned, _ = load_aligned_z(events, baseline)
    ev_lookup = events[["event_id", "episode_id", "model_role", "severity"]].copy()
    aligned = aligned.merge(ev_lookup, on="event_id", how="left")
    aligned = (
        aligned
        .sort_values(["episode_id", "t"])
        .drop_duplicates(subset=["episode_id", "t"], keep="first")
        .reset_index(drop=True)
    )
    return aligned


def _get_series(obs: pd.DataFrame, ep_id: str, col: str) -> pd.Series:
    """Return col vs t for episode, sorted, in t ∈ [T_LO, T_HI]."""
    sub = (
        obs[obs["episode_id"] == ep_id]
        .sort_values("t")
    )
    sub = sub[sub["t"].between(T_LO, T_HI)]
    return sub.set_index("t")[col]


def _envelope(obs: pd.DataFrame, ctrl_ids: list[str],
              col: str) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return (mean, min, max) over controls at a common t grid."""
    t_grid = np.arange(T_LO, T_HI + 1, 1.0)
    stacked = []
    for ep_id in ctrl_ids:
        s = _get_series(obs, ep_id, col)
        # Interpolate onto the common grid
        interped = s.reindex(s.index.union(t_grid)).interpolate("index").reindex(t_grid)
        stacked.append(interped.values)
    arr = np.array(stacked, dtype=float)
    mn  = pd.Series(np.nanmean(arr, axis=0), index=t_grid)
    lo  = pd.Series(np.nanmin(arr,  axis=0), index=t_grid)
    hi  = pd.Series(np.nanmax(arr,  axis=0), index=t_grid)
    return mn, lo, hi


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------

def _save(fig: plt.Figure, name: str) -> Path:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    path = FIGURES_DIR / name
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def fig_panel(obs: pd.DataFrame,
              case_id: str,
              ctrl_ids: list[str],
              season: str,
              figname: str) -> Path:
    """4-panel time series: each z-score feature, case vs control envelope."""
    nf = len(FEATURES)
    fig, axes = plt.subplots(nf, 1, figsize=(11, nf * 2.6), sharex=True)

    for ax, (col, ylabel, fcolor) in zip(axes, FEATURES):
        ax.axvline(0,  color="black", linewidth=1.0, linestyle="--", zorder=4)
        ax.axhline(0,  color="gray",  linewidth=0.5, linestyle=":", zorder=1)

        # Control envelope
        mn, lo, hi = _envelope(obs, ctrl_ids, col)
        ax.fill_between(mn.index, lo.values, hi.values,
                        color="steelblue", alpha=0.15, zorder=2,
                        label="Control range (min–max)")
        ax.plot(mn.index, mn.values, **_CTRL_MEAN_KW, label="Control mean")

        # Individual control lines (thin, labeled)
        import matplotlib.cm as _cm
        ctrl_colors = [_cm.Blues(0.4 + 0.5 * i / max(len(ctrl_ids)-1, 1))
                       for i in range(len(ctrl_ids))]
        for ci, (c_id, c_col) in enumerate(zip(ctrl_ids, ctrl_colors)):
            s = _get_series(obs, c_id, col).dropna()
            ax.plot(s.index, s.values,
                    color=c_col, linewidth=0.9, alpha=0.7, zorder=2)

        # Case (S3)
        case_s = _get_series(obs, case_id, col).dropna()
        ax.plot(case_s.index, case_s.values,
                label=f"{case_id} (S3)", **_CASE_KW)

        ax.set_ylabel(ylabel, fontsize=9)
        ax.yaxis.set_major_locator(mticker.MaxNLocator(5))
        ax.grid(True, linestyle=":", linewidth=0.4, alpha=0.4)

        # Time markers
        for tm in [-24, -12, -6]:
            ax.axvline(tm, color="gray", linewidth=0.4, linestyle=":", alpha=0.6)

    # Build legend once on top panel
    handles, labels = axes[0].get_legend_handles_labels()
    # keep only the envelope, mean, and case entries
    keep = [l for l in labels if "Control" in l or "S3" in l]
    keep_h = [h for h, l in zip(handles, labels) if l in keep]
    axes[0].legend(keep_h, keep, fontsize=8.5, loc="upper left", framealpha=0.85)

    axes[-1].set_xlabel("Hours relative to t = 0", fontsize=10)
    axes[-1].set_xlim(T_LO - 0.5, T_HI + 0.5)
    axes[-1].xaxis.set_major_locator(mticker.MultipleLocator(6))

    ctrl_str = ", ".join(ctrl_ids)
    fig.suptitle(
        f"Fig — {season} case-control   t ∈ [−24 h, 0]\n"
        f"Case: {case_id} (S3, red)   Controls: {ctrl_str}\n"
        "Shaded band = control min–max range   Dashed = control mean",
        fontsize=10, y=1.01,
    )
    fig.tight_layout()
    return _save(fig, figname)


def fig_phase_cc(obs: pd.DataFrame) -> Path:
    """Phase portrait (FE_Z, IC_Z) for both groups side by side."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    import matplotlib.cm as _cm

    for ax, (case_id, ctrl_ids, season) in zip(axes, GROUPS):
        ax.axhline(0, color="gray", linewidth=0.5, linestyle=":", zorder=1)
        ax.axvline(0, color="gray", linewidth=0.5, linestyle=":", zorder=1)

        # Controls
        ctrl_colors = [_cm.Blues(0.35 + 0.55 * i / max(len(ctrl_ids)-1, 1))
                       for i in range(len(ctrl_ids))]
        for c_id, c_col in zip(ctrl_ids, ctrl_colors):
            s = obs[(obs["episode_id"] == c_id) &
                    obs["t"].between(T_LO, T_HI)].sort_values("t").dropna(
                        subset=["fe_z", "ic_z"])
            ax.plot(s["fe_z"], s["ic_z"],
                    color=c_col, linewidth=1.1, alpha=0.75, zorder=2)
            # Mark t=0
            if not s.empty:
                ax.scatter(s["fe_z"].iloc[-1], s["ic_z"].iloc[-1],
                           color=c_col, s=40, marker="o", zorder=3,
                           edgecolors="white", linewidths=0.5)
            ax.annotate(c_id,
                        xy=(s["fe_z"].iloc[-1], s["ic_z"].iloc[-1]),
                        xytext=(4, 2), textcoords="offset points",
                        fontsize=6.5, color=c_col)

        # Case (S3)
        case_s = obs[(obs["episode_id"] == case_id) &
                     obs["t"].between(T_LO, T_HI)].sort_values("t").dropna(
                         subset=["fe_z", "ic_z"])
        ax.plot(case_s["fe_z"], case_s["ic_z"],
                color="#d62728", linewidth=2.2, zorder=5, label=f"{case_id} (S3)")
        if not case_s.empty:
            # Arrow mid-trajectory
            mid = len(case_s) // 2
            if mid + 1 < len(case_s):
                ax.annotate("",
                    xy=(case_s["fe_z"].iloc[mid+1], case_s["ic_z"].iloc[mid+1]),
                    xytext=(case_s["fe_z"].iloc[mid], case_s["ic_z"].iloc[mid]),
                    arrowprops=dict(arrowstyle="->", color="#d62728", lw=1.5),
                    zorder=6)
            # t=0 star
            ax.scatter(case_s["fe_z"].iloc[-1], case_s["ic_z"].iloc[-1],
                       color="#d62728", s=150, marker="*", zorder=7,
                       edgecolors="white", linewidths=0.5)
            ax.annotate(f"{case_id}\nt=0",
                        xy=(case_s["fe_z"].iloc[-1], case_s["ic_z"].iloc[-1]),
                        xytext=(5, 3), textcoords="offset points",
                        fontsize=7, color="#d62728")
            # t=-24 label
            ax.annotate("t=−24h",
                        xy=(case_s["fe_z"].iloc[0], case_s["ic_z"].iloc[0]),
                        xytext=(4, -8), textcoords="offset points",
                        fontsize=6.5, color="#d62728")

        ax.set_xlabel(r"$ForecastErrorZ$", fontsize=11)
        ax.set_ylabel(r"$InterchangeZ$",   fontsize=11)
        ax.set_title(f"{season} group\n{case_id} (S3) vs controls",
                     fontsize=11, pad=6)
        ax.legend(fontsize=8.5, loc="upper left", framealpha=0.85)
        ax.grid(True, linestyle=":", linewidth=0.4, alpha=0.4)

    fig.suptitle(
        "Fig 19 — Case-control phase portrait   (ForecastErrorZ, InterchangeZ)\n"
        "t = −24 h → 0   ·   red = S3 case   ·   blue shades = controls",
        fontsize=11, y=1.02,
    )
    fig.tight_layout()
    return _save(fig, "fig19_cc_phase.png")


def fig_divergence(obs: pd.DataFrame) -> Path:
    """Hour-by-hour divergence: S3 trajectory minus control mean, per feature."""
    nf = len(FEATURES)
    t_grid = np.arange(T_LO, T_HI + 1, 1.0)

    fig, axes = plt.subplots(nf, 2, figsize=(14, nf * 2.4), sharex=True)
    group_titles = [f"{case_id} − {season} control mean"
                    for case_id, _, season in GROUPS]

    for col_idx, (case_id, ctrl_ids, season) in enumerate(GROUPS):
        for row_idx, (col, ylabel, fcolor) in enumerate(FEATURES):
            ax = axes[row_idx, col_idx]
            ax.axhline(0, color="gray", linewidth=0.8, linestyle="--", zorder=1,
                       label="Zero (= control mean)")
            ax.axvline(0, color="black", linewidth=0.9, linestyle="--", zorder=4)

            mn, lo, hi = _envelope(obs, ctrl_ids, col)
            case_s = _get_series(obs, case_id, col)
            case_interp = (
                case_s
                .reindex(case_s.index.union(t_grid))
                .interpolate("index")
                .reindex(t_grid)
            )
            divergence = case_interp - mn

            # Shade direction of divergence
            ax.fill_between(divergence.index,
                            divergence.values, 0,
                            where=divergence.values > 0,
                            color="#d62728", alpha=0.35, zorder=2)
            ax.fill_between(divergence.index,
                            divergence.values, 0,
                            where=divergence.values < 0,
                            color="#1f77b4", alpha=0.35, zorder=2)
            ax.plot(divergence.index, divergence.values,
                    color=fcolor, linewidth=1.6, zorder=3)

            # Control spread as reference (hi-lo)
            spread = (hi - lo) / 2
            ax.fill_between(divergence.index,
                            -spread, spread,
                            color="gray", alpha=0.12, zorder=1,
                            label="±½ control spread")

            if row_idx == 0:
                ax.set_title(group_titles[col_idx], fontsize=10, pad=4)
            if col_idx == 0:
                ax.set_ylabel(f"Δ {ylabel}", fontsize=8.5)

            ax.grid(True, linestyle=":", linewidth=0.3, alpha=0.4)
            for tm in [-12, -6]:
                ax.axvline(tm, color="gray", linewidth=0.4, linestyle=":")

    for col_idx in range(2):
        axes[-1, col_idx].set_xlabel("Hours relative to t = 0", fontsize=10)
        axes[-1, col_idx].xaxis.set_major_locator(mticker.MultipleLocator(6))

    fig.suptitle(
        "Fig 20 — Divergence: S3 trajectory minus season-matched control mean\n"
        "Red fill = S3 above controls   Blue fill = S3 below controls"
        "   Gray band = ±½ control spread",
        fontsize=11, y=1.01,
    )
    fig.tight_layout()
    return _save(fig, "fig20_cc_divergence.png")


# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------

def build_summary(obs: pd.DataFrame) -> pd.DataFrame:
    """Mean of each feature in t ∈ [−12, 0] for case and controls."""
    rows = []
    for case_id, ctrl_ids, season in GROUPS:
        all_ids = [case_id] + ctrl_ids
        for ep_id in all_ids:
            sub = obs[(obs["episode_id"] == ep_id) &
                      obs["t"].between(-12.0, 0.0)]
            role = sub["model_role"].iloc[0] if not sub.empty else ""
            row = {"season": season, "episode_id": ep_id,
                   "model_role": role, "is_case": ep_id == case_id}
            for col, *_ in FEATURES:
                s = sub[col].dropna()
                row[f"mean_{col}"] = round(float(s.mean()), 3) if len(s) else np.nan
                row[f"max_{col}"]  = round(float(s.max()),  3) if len(s) else np.nan
            rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run() -> None:
    from gridregime.features.seasonal import load_baseline

    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    TABLES_DIR.mkdir(parents=True, exist_ok=True)

    events   = _load_events()
    baseline = load_baseline(
        PROJECT_ROOT / "data" / "interim" / "seasonal_baseline.parquet"
    )
    print("Loading observations...")
    obs = load_obs(events, baseline)

    # ── Summary table ─────────────────────────────────────────────────────────
    summary = build_summary(obs)
    spath = TABLES_DIR / "case_control_summary.csv"
    summary.to_csv(spath, index=False)
    print(f"\nSummary table → {spath.relative_to(PROJECT_ROOT)}")
    for season, grp in summary.groupby("season"):
        print(f"\n── {season} ──────────────────────────────────")
        cols = ["episode_id", "is_case",
                "mean_load_z", "mean_fe_z", "mean_ramp3_z", "mean_ic_z",
                "max_load_z",  "max_ramp3_z"]
        print(grp[cols].to_string(index=False))

    # ── Figures ───────────────────────────────────────────────────────────────
    print("\nGenerating figures...")
    case_w, ctrl_w, _ = GROUPS[0]
    case_s, ctrl_s, _ = GROUPS[1]

    p17 = fig_panel(obs, case_w, ctrl_w, "Winter", "fig17_cc_winter.png")
    p18 = fig_panel(obs, case_s, ctrl_s, "Summer", "fig18_cc_summer.png")
    p19 = fig_phase_cc(obs)
    p20 = fig_divergence(obs)
    for p in (p17, p18, p19, p20):
        print(f"  → {p.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    run()
