"""Unsupervised regime detection: Gaussian HMM on pooled episode sequences.

Fits a GaussianHMM on all hourly z-scored observations, treating each
meteorological episode as one sequence. No outcome labels are used during
fitting. After decoding, state occupancy in t ∈ [−24, 0] is computed per
episode and compared across S1/S2/S3 populations.

Steps
-----
1. Load z-scored aligned windows (re-using survey_z.load_aligned_z).
2. Add episode_id; deduplicate by (episode_id, t) → one sequence per episode.
3. Fit GaussianHMM for K in {3, 4, 5}; select by BIC.
4. Decode states; compute occupancy in t ∈ [−24, 0] per episode.
5. Write output figures and tables.

Output figures
--------------
  fig10_bic.png            BIC vs number of states
  fig11_state_means.png    State mean z-scores (heatmap)
  fig12_state_occupancy.png  Occupancy in t=[−24,0] per episode (stacked bar)
  fig13_phase_states.png   Phase portrait (FE_z, IC_z) coloured by state
  fig14_state_timelines.png  State sequence strips for all episodes

Output tables
-------------
  results/tables/regime_state_occupancy.csv
  results/tables/regime_state_means.csv

Usage
-----
    python -m gridregime.pipeline.regime_detection
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import matplotlib.patches as mpatches
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve()
PROJECT_ROOT = _HERE.parents[3]

EVENTS_CSV    = PROJECT_ROOT / "metadata" / "events.csv"
INTERIM_DIR   = PROJECT_ROOT / "data" / "interim" / "eia930"
BASELINE_PATH = PROJECT_ROOT / "data" / "interim" / "seasonal_baseline.parquet"
FIGURES_DIR   = PROJECT_ROOT / "results" / "figures"
TABLES_DIR    = PROJECT_ROOT / "results" / "tables"

FEATURES = ["load_z", "fe_z", "ramp3_z", "ic_z"]
K_RANGE  = [3, 4, 5]

# Colour palette for states (up to 6 states)
_STATE_COLORS = ["#4878d0", "#ee854a", "#6acc65", "#d65f5f", "#b47cc7", "#c4ad66"]

# Colour by model_role for occupancy chart row labels
_ROLE_COLORS = {"positive": "#d62728", "hard_negative": "#1f77b4"}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_events() -> pd.DataFrame:
    df = pd.read_csv(EVENTS_CSV)
    for col in ["window_start", "event_end", "operator_action_time", "first_alert_time"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
    return df


def load_episode_sequences(
    events: pd.DataFrame,
    baseline: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load z-scored data deduped to one sequence per episode.

    Returns
    -------
    obs : DataFrame with columns [episode_id, t, load_z, fe_z, ramp3_z, ic_z]
          Sorted by (episode_id, t). One row per unique (episode_id, t).
    ep_meta : DataFrame with columns [episode_id, model_role, severity,
              t0_utc, event_ids]
    """
    from gridregime.plotting.survey_z import load_aligned_z

    aligned, ev_meta = load_aligned_z(events, baseline)
    if aligned.empty:
        raise RuntimeError("No z-scored data loaded.")

    # Join episode_id and model_role onto aligned
    ev_lookup = events[["event_id", "episode_id", "model_role", "severity"]].copy()
    aligned = aligned.merge(ev_lookup, on="event_id", how="left")

    # Deduplicate: within an episode, multiple events share overlapping windows.
    # Keep the first occurrence of each (episode_id, t) so each hour is counted once.
    aligned = (
        aligned
        .sort_values(["episode_id", "t"])
        .drop_duplicates(subset=["episode_id", "t"], keep="first")
        .reset_index(drop=True)
    )

    # Episode-level metadata: earliest t0 and list of contributing event IDs
    ep_rows = []
    for ep_id, grp in aligned.groupby("episode_id"):
        role = grp["model_role"].iloc[0]
        sev  = grp["severity"].iloc[0]
        ep_rows.append({
            "episode_id": ep_id,
            "model_role": role,
            "severity":   sev,
            "n_hours":    len(grp),
        })
    ep_meta = pd.DataFrame(ep_rows)

    obs = aligned[["episode_id", "t"] + FEATURES].copy()
    return obs, ep_meta


# ---------------------------------------------------------------------------
# HMM fitting
# ---------------------------------------------------------------------------

def _bic(model, X: np.ndarray, lengths: list[int]) -> float:
    """BIC for a fitted GaussianHMM."""
    from hmmlearn.hmm import GaussianHMM
    K = model.n_components
    p = X.shape[1]
    # free parameters: transition (K*(K-1)), initial (K-1), means (K*p),
    # full covariances (K * p*(p+1)/2)
    n_params = K * (K - 1) + (K - 1) + K * p + K * p * (p + 1) // 2
    log_L = model.score(X, lengths=lengths)
    return -2 * log_L + n_params * np.log(len(X))


def fit_hmm_grid(
    obs: pd.DataFrame,
    k_range: list[int] = K_RANGE,
    n_restarts: int = 8,
) -> dict:
    """Fit GaussianHMM for each K; return best model per K and BIC scores."""
    from hmmlearn.hmm import GaussianHMM

    # Build sequence list (one per episode, sorted by t)
    episodes = obs["episode_id"].unique()
    sequences, lengths = [], []
    for ep in episodes:
        seq = (
            obs[obs["episode_id"] == ep]
            .sort_values("t")[FEATURES]
            .dropna()
            .values
        )
        if len(seq) >= 5:
            sequences.append(seq)
            lengths.append(len(seq))

    X = np.vstack(sequences)
    print(f"  HMM corpus: {len(episodes)} episodes, {len(X)} observations, "
          f"{X.shape[1]} features")

    results: dict[int, dict] = {}
    for K in k_range:
        best_model, best_bic = None, np.inf
        for seed in range(n_restarts):
            m = GaussianHMM(
                n_components=K,
                covariance_type="full",
                n_iter=300,
                random_state=seed,
            )
            try:
                m.fit(X, lengths=lengths)
                b = _bic(m, X, lengths)
                if b < best_bic:
                    best_bic   = b
                    best_model = m
            except Exception as exc:
                print(f"    K={K} seed={seed} failed: {exc}")
        results[K] = {"model": best_model, "bic": best_bic}
        print(f"  K={K}  BIC={best_bic:.1f}")

    return {"fits": results, "X": X, "lengths": lengths, "episodes": episodes}


def select_best_k(fits: dict) -> int:
    """Return K with lowest BIC."""
    return min(fits, key=lambda k: fits[k]["bic"])


def decode_all(
    model,
    obs: pd.DataFrame,
) -> pd.DataFrame:
    """Viterbi decode and attach state column to obs."""
    episodes = obs["episode_id"].unique()
    frames = []
    for ep in episodes:
        ep_df = obs[obs["episode_id"] == ep].sort_values("t").copy()
        ep_clean = ep_df.dropna(subset=FEATURES)
        if ep_clean.empty:
            ep_df["state"] = np.nan
            frames.append(ep_df)
            continue
        X_ep = ep_clean[FEATURES].values
        states = model.predict(X_ep)
        ep_clean = ep_clean.copy()
        ep_clean["state"] = states
        # Merge states back to full ep_df (NaN rows get NaN state)
        ep_df = ep_df.merge(ep_clean[["episode_id", "t", "state"]],
                            on=["episode_id", "t"], how="left")
        frames.append(ep_df)
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# Occupancy analysis
# ---------------------------------------------------------------------------

def compute_occupancy(
    obs_states: pd.DataFrame,
    ep_meta: pd.DataFrame,
    n_states: int,
    t_lo: float = -24.0,
    t_hi: float = 0.0,
) -> pd.DataFrame:
    """Fraction of hours in t ∈ [t_lo, t_hi] spent in each state, per episode."""
    window = obs_states[
        obs_states["t"].between(t_lo, t_hi) &
        obs_states["state"].notna()
    ].copy()
    window["state"] = window["state"].astype(int)

    rows = []
    for _, em in ep_meta.iterrows():
        ep_id = em["episode_id"]
        sub = window[window["episode_id"] == ep_id]
        total = len(sub)
        row = {"episode_id": ep_id,
               "model_role": em["model_role"],
               "severity":   em["severity"],
               "n_hours_window": total}
        for s in range(n_states):
            frac = (sub["state"] == s).sum() / total if total > 0 else np.nan
            row[f"state_{s}_frac"] = round(frac, 3)
        rows.append(row)
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


def fig_bic(fits: dict) -> Path:
    ks   = sorted(fits)
    bics = [fits[k]["bic"] for k in ks]
    best = min(ks, key=lambda k: fits[k]["bic"])

    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(ks, bics, "o-", color="#1f77b4", linewidth=1.8, markersize=7)
    ax.axvline(best, color="#d62728", linestyle="--", linewidth=1.2,
               label=f"Best K={best}")
    ax.set_xlabel("Number of hidden states (K)", fontsize=11)
    ax.set_ylabel("BIC", fontsize=11)
    ax.set_title("Fig 10 — BIC for GaussianHMM: K = 3 … 5", fontsize=12)
    ax.legend(fontsize=9)
    ax.set_xticks(ks)
    ax.grid(True, linestyle=":", alpha=0.5)
    fig.tight_layout()
    return _save(fig, "fig10_bic.png")


def fig_state_means(model, feature_names: list[str]) -> Path:
    K = model.n_components
    means = model.means_   # shape (K, n_features)

    fig, ax = plt.subplots(figsize=(7, max(3, K * 0.9 + 1)))
    vmax = max(2.5, np.abs(means).max() * 1.1)
    im = ax.imshow(means, aspect="auto", cmap="RdBu_r",
                   vmin=-vmax, vmax=vmax)
    ax.set_xticks(range(len(feature_names)))
    ax.set_xticklabels(feature_names, fontsize=10)
    ax.set_yticks(range(K))
    ax.set_yticklabels([f"State {s}" for s in range(K)], fontsize=10)
    ax.set_title(
        f"Fig 11 — HMM state means (K={K})\n"
        "Colour = mean z-score in each feature; blue = below normal, red = above normal",
        fontsize=11, pad=8,
    )
    for i in range(K):
        for j, feat in enumerate(feature_names):
            val = means[i, j]
            ax.text(j, i, f"{val:+.2f}", ha="center", va="center",
                    fontsize=9,
                    color="white" if abs(val) > vmax * 0.5 else "black")
    plt.colorbar(im, ax=ax, label="Mean z-score")
    fig.tight_layout()
    return _save(fig, "fig11_state_means.png")


def fig_state_occupancy(occ: pd.DataFrame, n_states: int) -> Path:
    # Sort: S3 first, then S2, then S1 — within each by severity label
    role_order = {"positive": 0, "hard_negative": 1}
    sev_order  = {"S3": 0, "S2": 1, "S1": 2}
    occ = occ.copy()
    occ["_rsort"] = occ["model_role"].map(role_order)
    occ["_ssort"] = occ["severity"].map(sev_order).fillna(9)
    occ = occ.sort_values(["_rsort", "_ssort", "episode_id"]).reset_index(drop=True)

    state_cols = [f"state_{s}_frac" for s in range(n_states)]
    fig, ax = plt.subplots(figsize=(max(10, len(occ) * 0.8), 5))

    bottoms = np.zeros(len(occ))
    for s in range(n_states):
        vals = occ[f"state_{s}_frac"].fillna(0).values
        ax.bar(range(len(occ)), vals, bottom=bottoms,
               color=_STATE_COLORS[s % len(_STATE_COLORS)],
               label=f"State {s}", edgecolor="white", linewidth=0.4)
        bottoms += vals

    ax.set_xticks(range(len(occ)))
    ax.set_xticklabels(occ["episode_id"], rotation=45, ha="right", fontsize=8.5)
    ax.set_ylabel("Fraction of hours in t ∈ [−24, 0]", fontsize=10)
    ax.set_title(
        f"Fig 12 — State occupancy per episode in t = [−24 h, 0]  (K={n_states})\n"
        "Red label = S3 (positive); blue = hard negative",
        fontsize=11, pad=8,
    )
    ax.set_ylim(0, 1.05)
    ax.legend(fontsize=9, loc="upper right")
    ax.grid(True, axis="y", linestyle=":", alpha=0.4)

    # Colour x-tick labels by model_role
    for tick, (_, row) in zip(ax.get_xticklabels(), occ.iterrows()):
        tick.set_color(_ROLE_COLORS.get(row["model_role"], "black"))

    fig.tight_layout()
    return _save(fig, "fig12_state_occupancy.png")


def fig_phase_states(obs_states: pd.DataFrame, n_states: int) -> Path:
    """Phase portrait in (fe_z, ic_z) coloured by HMM state."""
    window = obs_states[obs_states["t"].between(-24, 0)].copy()
    window = window.dropna(subset=["fe_z", "ic_z", "state"])
    window["state"] = window["state"].astype(int)

    fig, ax = plt.subplots(figsize=(9, 7))
    ax.axhline(0, color="gray", linewidth=0.5, linestyle=":", zorder=1)
    ax.axvline(0, color="gray", linewidth=0.5, linestyle=":", zorder=1)

    for s in range(n_states):
        sub = window[window["state"] == s]
        ax.scatter(sub["fe_z"], sub["ic_z"],
                   color=_STATE_COLORS[s % len(_STATE_COLORS)],
                   s=22, alpha=0.65, zorder=3, label=f"State {s}")

    # Overlay episode trajectories as thin lines (black)
    for ep_id, grp in obs_states[obs_states["t"].between(-24, 0)].groupby("episode_id"):
        grp = grp.sort_values("t").dropna(subset=["fe_z", "ic_z"])
        ax.plot(grp["fe_z"], grp["ic_z"],
                color="black", linewidth=0.5, alpha=0.3, zorder=2)
        # Mark t=0 for each episode
        t0_row = grp.iloc[(grp["t"].abs()).argsort().iloc[:1]]
        ax.scatter(float(t0_row["fe_z"]), float(t0_row["ic_z"]),
                   color="black", s=55, marker="*", zorder=5, edgecolors="white",
                   linewidths=0.5)
        ax.annotate(ep_id,
                    xy=(float(t0_row["fe_z"]), float(t0_row["ic_z"])),
                    xytext=(5, 3), textcoords="offset points",
                    fontsize=6.5, color="black", zorder=6)

    ax.set_xlabel(r"$ForecastErrorZ$", fontsize=12)
    ax.set_ylabel(r"$InterchangeZ$", fontsize=12)
    ax.set_title(
        f"Fig 13 — Phase portrait coloured by HMM state  (K={n_states})\n"
        "t = −24 h → 0 h  ·  ★ = t = 0  ·  thin lines = episode trajectories",
        fontsize=11, pad=8,
    )
    ax.legend(fontsize=9, loc="upper left", framealpha=0.85)
    ax.grid(True, linestyle=":", linewidth=0.4, alpha=0.4)
    fig.tight_layout()
    return _save(fig, "fig13_phase_states.png")


def fig_state_timelines(obs_states: pd.DataFrame, ep_meta: pd.DataFrame,
                        n_states: int) -> Path:
    """Horizontal state-sequence strips, one row per episode."""
    # Order: S3 first, then S2/S1
    role_order = {"positive": 0, "hard_negative": 1}
    sev_order  = {"S3": 0, "S2": 1, "S1": 2}
    ep_meta = ep_meta.copy()
    ep_meta["_rsort"] = ep_meta["model_role"].map(role_order)
    ep_meta["_ssort"] = ep_meta["severity"].map(sev_order).fillna(9)
    ep_order = (
        ep_meta.sort_values(["_rsort", "_ssort", "episode_id"])["episode_id"].tolist()
    )

    fig, axes = plt.subplots(
        len(ep_order), 1,
        figsize=(13, max(6, len(ep_order) * 0.65)),
        sharex=True,
    )
    if len(ep_order) == 1:
        axes = [axes]

    T_LO, T_HI = -72, 12

    for ax, ep_id in zip(axes, ep_order):
        sub = (
            obs_states[obs_states["episode_id"] == ep_id]
            .sort_values("t")
            .dropna(subset=["state"])
        )
        sub = sub[sub["t"].between(T_LO, T_HI)]

        for _, row in sub.iterrows():
            t = row["t"]
            s = int(row["state"])
            ax.barh(0, 1, left=t, color=_STATE_COLORS[s % len(_STATE_COLORS)],
                    height=0.8, edgecolor="none")

        ax.axvline(0, color="black", linewidth=1.0, linestyle="--", zorder=5)
        ax.set_yticks([])
        role = ep_meta[ep_meta["episode_id"] == ep_id]["model_role"].iloc[0]
        ax.set_ylabel(ep_id, rotation=0, ha="right", va="center",
                      fontsize=7.5,
                      color=_ROLE_COLORS.get(role, "black"))
        ax.set_xlim(T_LO - 1, T_HI + 1)

    axes[-1].set_xlabel("Hours relative to t = 0", fontsize=10)
    axes[-1].xaxis.set_major_locator(mticker.MultipleLocator(12))

    # Legend
    patches = [mpatches.Patch(color=_STATE_COLORS[s], label=f"State {s}")
               for s in range(n_states)]
    fig.legend(handles=patches, loc="upper right", fontsize=8.5,
               bbox_to_anchor=(1.0, 1.0))

    fig.suptitle(
        f"Fig 14 — HMM state sequences per episode  (K={n_states})\n"
        "Red label = S3 (positive); blue = hard negative  ·  dashed line = t = 0",
        fontsize=11, y=1.01,
    )
    fig.tight_layout()
    return _save(fig, "fig14_state_timelines.png")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run() -> None:
    from gridregime.features.seasonal import load_baseline

    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    TABLES_DIR.mkdir(parents=True, exist_ok=True)

    # ── 1. Load data ──────────────────────────────────────────────────────────
    events = _load_events()
    baseline_cache = PROJECT_ROOT / "data" / "interim" / "seasonal_baseline.parquet"
    baseline = load_baseline(baseline_cache)
    print("Building episode sequences...")
    obs, ep_meta = load_episode_sequences(events, baseline)
    print(f"  {obs['episode_id'].nunique()} episodes  ·  "
          f"{len(obs)} total hourly observations")
    print(f"  {obs.dropna(subset=FEATURES)['episode_id'].nunique()} episodes with "
          f"complete features after dropping NaN ramp rows\n")

    # ── 2. Fit HMM for K in {3, 4, 5} ────────────────────────────────────────
    print("Fitting HMM (K = 3..5, 8 restarts each)...")
    grid = fit_hmm_grid(obs, K_RANGE, n_restarts=8)
    fits = grid["fits"]
    best_K = select_best_k(fits)
    print(f"\nBest K by BIC: {best_K}")
    best_model = fits[best_K]["model"]

    # ── 3. Decode states ──────────────────────────────────────────────────────
    print("\nDecoding states (Viterbi)...")
    obs_states = decode_all(best_model, obs)

    # ── 4. Occupancy ──────────────────────────────────────────────────────────
    occ = compute_occupancy(obs_states, ep_meta, best_K)
    occ_path = TABLES_DIR / "regime_state_occupancy.csv"
    occ.to_csv(occ_path, index=False)
    print(f"\nOccupancy table → {occ_path.relative_to(PROJECT_ROOT)}")
    state_cols = [c for c in occ.columns if c.startswith("state_")]
    print(occ[["episode_id", "model_role", "severity"] + state_cols].to_string(index=False))

    # State means table
    means_df = pd.DataFrame(
        best_model.means_,
        columns=FEATURES,
        index=[f"state_{s}" for s in range(best_K)],
    )
    means_path = TABLES_DIR / "regime_state_means.csv"
    means_df.to_csv(means_path)
    print(f"\nState means → {means_path.relative_to(PROJECT_ROOT)}")
    print(means_df.round(3).to_string())

    # ── 5. Figures ────────────────────────────────────────────────────────────
    print("\nGenerating figures...")
    p10 = fig_bic({k: fits[k] for k in K_RANGE})
    p11 = fig_state_means(best_model, FEATURES)
    p12 = fig_state_occupancy(occ, best_K)
    p13 = fig_phase_states(obs_states, best_K)
    p14 = fig_state_timelines(obs_states, ep_meta, best_K)
    for p in (p10, p11, p12, p13, p14):
        print(f"  → {p.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    run()
