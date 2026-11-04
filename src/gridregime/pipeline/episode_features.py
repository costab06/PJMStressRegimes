"""Episode-level summary features and discriminant scatter plots.

For each episode, computes summary statistics over t ∈ [−12, 0] from the
z-scored aligned windows. Produces a scatter matrix so the analyst can see
directly which features (or combinations) separate S3 from S2.

This is the right analysis when N_S3 = 2: transparent, labelled, no latent
structure to interpret.

Features computed in t ∈ [−12, 0]
-----------------------------------
  max_load_z        Peak LoadZ
  mean_fe_z         Mean ForecastErrorZ  (positive = demand > forecast)
  max_ramp3_z       Peak 3-hour ramp Z-score
  mean_ic_z         Mean InterchangeZ    (positive = net importer)
  fe_trend          Slope of FE_Z (σ/h)  — is the error growing?
  load_persistence  Fraction of hours with LoadZ > 2σ

Output figures
--------------
  fig15_episode_scatter.png   Scatter matrix of feature pairs
  fig16_feature_bars.png      Per-feature bar chart, all episodes

Output table
------------
  results/tables/episode_features.csv

Usage
-----
    python -m gridregime.pipeline.episode_features
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import numpy as np
import pandas as pd
from scipy import stats as sp_stats

_HERE = Path(__file__).resolve()
PROJECT_ROOT = _HERE.parents[3]

EVENTS_CSV    = PROJECT_ROOT / "metadata" / "events.csv"
FIGURES_DIR   = PROJECT_ROOT / "results" / "figures"
TABLES_DIR    = PROJECT_ROOT / "results" / "tables"

T_WINDOW = (-12.0, 0.0)   # hours before t=0 used for summary stats

_ROLE_COLOR  = {"positive": "#d62728", "hard_negative": "#1f77b4"}
_ROLE_MARKER = {"positive": "*",       "hard_negative": "o"}
_ROLE_SIZE   = {"positive": 220,       "hard_negative": 60}
_SEV_LABEL   = {"S3": "S3 emergency", "S2": "S2 managed", "S1": "S1 extreme"}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_events() -> pd.DataFrame:
    df = pd.read_csv(EVENTS_CSV)
    for col in ["window_start", "event_end", "operator_action_time"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
    return df


def load_z_by_episode(events: pd.DataFrame,
                      baseline: pd.DataFrame) -> pd.DataFrame:
    """Return z-scored observations deduped to one row per (episode_id, t)."""
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


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

def _slope(x: np.ndarray, y: np.ndarray) -> float:
    """OLS slope; returns NaN if fewer than 3 valid pairs."""
    mask = ~(np.isnan(x) | np.isnan(y))
    if mask.sum() < 3:
        return np.nan
    return float(sp_stats.linregress(x[mask], y[mask]).slope)


def compute_episode_features(obs: pd.DataFrame) -> pd.DataFrame:
    """Compute summary features per episode in t ∈ T_WINDOW."""
    t_lo, t_hi = T_WINDOW
    window = obs[obs["t"].between(t_lo, t_hi)].copy()

    rows = []
    for ep_id, grp in window.groupby("episode_id"):
        grp = grp.sort_values("t")
        t_arr   = grp["t"].values
        lz      = grp["load_z"].values
        fez     = grp["fe_z"].values
        rz      = grp["ramp3_z"].values
        icz     = grp["ic_z"].values

        rows.append({
            "episode_id":       ep_id,
            "model_role":       grp["model_role"].iloc[0],
            "severity":         grp["severity"].iloc[0],
            # --- core features ---
            "max_load_z":       float(np.nanmax(lz))       if np.any(~np.isnan(lz)) else np.nan,
            "mean_fe_z":        float(np.nanmean(fez))     if np.any(~np.isnan(fez)) else np.nan,
            "max_ramp3_z":      float(np.nanmax(rz))       if np.any(~np.isnan(rz)) else np.nan,
            "mean_ic_z":        float(np.nanmean(icz))     if np.any(~np.isnan(icz)) else np.nan,
            # --- trajectory / persistence features ---
            "fe_trend":         _slope(t_arr, fez),         # σ/h: is error growing?
            "load_persistence": float(np.nanmean(lz > 2.0)) if np.any(~np.isnan(lz)) else np.nan,
            # --- at t=0 ---
            "load_z_at_t0":     float(grp.iloc[(grp["t"].abs()).argsort().iloc[0]]["load_z"]),
            "fe_z_at_t0":       float(grp.iloc[(grp["t"].abs()).argsort().iloc[0]]["fe_z"]),
            "ic_z_at_t0":       float(grp.iloc[(grp["t"].abs()).argsort().iloc[0]]["ic_z"]),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------

def _save(fig: plt.Figure, name: str) -> Path:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    path = FIGURES_DIR / name
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def fig_scatter_matrix(feat: pd.DataFrame) -> Path:
    """Scatter matrix of key feature pairs — one labelled point per episode."""
    pairs = [
        ("max_load_z",    "mean_fe_z",    "Max LoadZ [−12,0]",    "Mean FE_Z [−12,0]"),
        ("max_load_z",    "mean_ic_z",    "Max LoadZ [−12,0]",    "Mean IC_Z [−12,0]"),
        ("mean_fe_z",     "mean_ic_z",    "Mean FE_Z [−12,0]",    "Mean IC_Z [−12,0]"),
        ("max_ramp3_z",   "mean_fe_z",    "Max RampZ [−12,0]",    "Mean FE_Z [−12,0]"),
        ("fe_trend",      "max_load_z",   "FE_Z trend (σ/h)",     "Max LoadZ [−12,0]"),
        ("load_persistence", "mean_ic_z", "LoadZ > 2σ fraction",  "Mean IC_Z [−12,0]"),
    ]

    ncols = 3
    nrows = 2
    fig, axes = plt.subplots(nrows, ncols, figsize=(14, 9))
    axes = axes.flatten()

    for ax, (xcol, ycol, xlabel, ylabel) in zip(axes, pairs):
        ax.axhline(0, color="gray", linewidth=0.5, linestyle=":", zorder=0)
        ax.axvline(0, color="gray", linewidth=0.5, linestyle=":", zorder=0)

        for _, row in feat.iterrows():
            xv = row[xcol]
            yv = row[ycol]
            if np.isnan(xv) or np.isnan(yv):
                continue
            role = row["model_role"]
            ax.scatter(xv, yv,
                       color=_ROLE_COLOR[role],
                       marker=_ROLE_MARKER[role],
                       s=_ROLE_SIZE[role],
                       zorder=4, edgecolors="white", linewidths=0.5)
            ax.annotate(row["episode_id"],
                        xy=(xv, yv), xytext=(4, 3),
                        textcoords="offset points",
                        fontsize=6.5,
                        color=_ROLE_COLOR[role],
                        zorder=5)

        ax.set_xlabel(xlabel, fontsize=9)
        ax.set_ylabel(ylabel, fontsize=9)
        ax.grid(True, linestyle=":", linewidth=0.4, alpha=0.4)
        ax.tick_params(labelsize=8)

    # Legend
    from matplotlib.lines import Line2D
    handles = [
        Line2D([0], [0], marker="*", color="w", markerfacecolor="#d62728",
               markersize=12, label="S3 emergency (positive)"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#1f77b4",
               markersize=8,  label="S2/S1 hard negative"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=2, fontsize=9,
               bbox_to_anchor=(0.5, -0.02))
    fig.suptitle(
        "Fig 15 — Episode-level feature scatter matrix   t ∈ [−12 h, 0]\n"
        "★ = S3 emergency   ●  = hard negative   Labels: episode_id",
        fontsize=11, y=1.01,
    )
    fig.tight_layout()
    return _save(fig, "fig15_episode_scatter.png")


def fig_feature_bars(feat: pd.DataFrame) -> Path:
    """Grouped bar chart: each feature, episodes sorted by severity."""
    feature_cols = [
        ("max_load_z",       "Max LoadZ [−12,0]"),
        ("mean_fe_z",        "Mean FE_Z [−12,0]"),
        ("max_ramp3_z",      "Max RampZ [−12,0]"),
        ("mean_ic_z",        "Mean IC_Z [−12,0]"),
        ("fe_trend",         "FE_Z trend (σ/h)"),
        ("load_persistence", "LoadZ > 2σ fraction [−12,0]"),
    ]
    # Sort: S3 first
    role_order = {"positive": 0, "hard_negative": 1}
    sev_order  = {"S3": 0, "S2": 1, "S1": 2}
    feat = feat.copy()
    feat["_rs"] = feat["model_role"].map(role_order)
    feat["_ss"] = feat["severity"].map(sev_order).fillna(9)
    feat = feat.sort_values(["_rs", "_ss", "episode_id"]).reset_index(drop=True)
    ep_ids = feat["episode_id"].tolist()
    colors = [_ROLE_COLOR[r] for r in feat["model_role"]]

    nf = len(feature_cols)
    fig, axes = plt.subplots(nf, 1, figsize=(13, nf * 2.0), sharex=True)

    for ax, (col, label) in zip(axes, feature_cols):
        vals = feat[col].values.astype(float)
        bars = ax.bar(range(len(ep_ids)), vals, color=colors,
                      edgecolor="white", linewidth=0.4)
        ax.axhline(0, color="gray", linewidth=0.5, linestyle=":")
        ax.set_ylabel(label, fontsize=8)
        ax.grid(True, axis="y", linestyle=":", linewidth=0.4, alpha=0.4)
        ax.tick_params(axis="y", labelsize=7)

    axes[-1].set_xticks(range(len(ep_ids)))
    axes[-1].set_xticklabels(ep_ids, rotation=40, ha="right", fontsize=8)
    for tick, row in zip(axes[-1].get_xticklabels(), feat.itertuples()):
        tick.set_color(_ROLE_COLOR[row.model_role])

    from matplotlib.patches import Patch
    handles = [Patch(color="#d62728", label="S3 emergency"),
               Patch(color="#1f77b4", label="S2/S1 hard negative")]
    fig.legend(handles=handles, loc="upper right", fontsize=8.5)
    fig.suptitle(
        "Fig 16 — Per-feature summary  t ∈ [−12 h, 0]   ·   red = S3, blue = hard negative",
        fontsize=11,
    )
    fig.tight_layout()
    return _save(fig, "fig16_feature_bars.png")


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

    print("Loading z-scored episode observations...")
    obs  = load_z_by_episode(events, baseline)
    feat = compute_episode_features(obs)

    feat_path = TABLES_DIR / "episode_features.csv"
    feat.to_csv(feat_path, index=False)
    print(f"\nFeature table → {feat_path.relative_to(PROJECT_ROOT)}")

    # Sort for display: S3 first
    display = feat.copy()
    display["_rs"] = display["model_role"].map({"positive": 0, "hard_negative": 1})
    display["_ss"] = display["severity"].map({"S3": 0, "S2": 1, "S1": 2}).fillna(9)
    display = display.sort_values(["_rs", "_ss", "episode_id"]).drop(
        columns=["_rs", "_ss"]
    )
    num_cols = ["max_load_z","mean_fe_z","max_ramp3_z","mean_ic_z",
                "fe_trend","load_persistence","fe_z_at_t0","ic_z_at_t0"]
    print(display[["episode_id","severity"] + num_cols].round(2).to_string(index=False))

    print("\nGenerating figures...")
    p15 = fig_scatter_matrix(feat)
    p16 = fig_feature_bars(feat)
    for p in (p15, p16):
        print(f"  → {p.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    run()
