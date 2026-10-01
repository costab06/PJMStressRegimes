"""Event survey figures — four separate figures, all events overlaid.

Alignment:
  positive events    t=0 = operator_action_time
  hard_negative      t=0 = peak-demand hour within [window_start, event_end]
                          (alignment_type="peak_demand")

Window: T_MIN <= t <= T_MAX  (-72h to +12h)

Figures produced:
  fig1_demand_norm.png       window-normalised demand
  fig2_forecast_error.png    forecast error (%)
  fig3_ramp_3h.png           3-hour ramp rate (MW/h)
  fig4_interchange_rel.png   interchange as % of demand

Summary table:
  results/tables/event_summary.csv  — stats over t in [T_MIN, 0]

Visual convention: same line treatment for all events; no outcome coloring.
Identifiable by legend. t=0 marked with a dashed vertical line.
A second pass (colored by outcome) can be generated separately.

Usage:
    python -m gridregime.plotting.event_survey
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

INTERIM_DIR = PROJECT_ROOT / "data" / "interim" / "eia930"
EVENTS_CSV  = PROJECT_ROOT / "metadata" / "events.csv"
FIGURES_DIR = PROJECT_ROOT / "results" / "figures"
TABLES_DIR  = PROJECT_ROOT / "results" / "tables"

T_MIN = -72   # hours before t=0
T_MAX = +12   # hours after  t=0

# Ten distinguishable colours — same palette for both passes
_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
]
_LINE_KW = dict(linewidth=1.3, alpha=0.85)


# ---------------------------------------------------------------------------
# Data loading and alignment
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
    mask = (interim_df["timestamp_utc"] >= window_start) & \
           (interim_df["timestamp_utc"] <= event_end)
    sub = interim_df[mask].dropna(subset=["demand_mwh"])
    if sub.empty:
        raise ValueError("No demand data in event window for peak-demand alignment")
    return sub.loc[sub["demand_mwh"].idxmax(), "timestamp_utc"]


def load_aligned(events: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load interim parquets, compute t relative to t=0, clip to [T_MIN, T_MAX].

    Returns
    -------
    aligned : DataFrame with columns
        event_id, t, demand_mwh, forecast_mwh, interchange_mwh,
        demand_norm, forecast_error_pct, ramp_3h, ic_rel
    meta : DataFrame with columns
        event_id, model_role, alignment_type, t0_utc
    """
    frames: list[pd.DataFrame] = []
    meta_rows: list[dict] = []

    for _, ev in events.iterrows():
        eid = ev["event_id"]
        path = INTERIM_DIR / f"{eid}.parquet"
        if not path.exists():
            print(f"  SKIP {eid}: interim parquet not found")
            continue

        df = pd.read_parquet(path).sort_values("timestamp_utc").reset_index(drop=True)

        # ---- determine t=0 ----
        if ev["model_role"] == "positive" and pd.notna(ev.get("operator_action_time")):
            t0 = ev["operator_action_time"]
            alignment_type = "operator_action"
        else:
            t0 = _peak_demand_ts(df, ev["window_start"], ev["event_end"])
            alignment_type = "peak_demand"

        df["t"] = (df["timestamp_utc"] - t0).dt.total_seconds() / 3600
        df = df[(df["t"] >= T_MIN) & (df["t"] <= T_MAX)].copy()
        if df.empty:
            print(f"  SKIP {eid}: no data in [{T_MIN}h, {T_MAX}h] after alignment")
            continue

        df["event_id"] = eid

        # ---- derived signals ----

        # Window-normalised demand  D* = D / max(D in window)
        dmax = df["demand_mwh"].max()
        df["demand_norm"] = df["demand_mwh"] / dmax if dmax > 0 else np.nan

        # Forecast error (%)  FE = 100*(D - D̂)/D̂
        df["forecast_error_pct"] = (
            100.0 * (df["demand_mwh"] - df["forecast_mwh"]) / df["forecast_mwh"]
        )

        # 3-hour ramp rate (MW/h)  R₃ = (D[t] - D[t-3]) / 3
        # Only computed where t gaps are exactly 3 h (no missing hours bridged)
        df = df.reset_index(drop=True)
        d_vals = df["demand_mwh"].values.astype(float)
        t_vals = df["t"].values.astype(float)
        r3 = np.full(len(d_vals), np.nan)
        for i in range(3, len(d_vals)):
            if abs(t_vals[i] - t_vals[i - 3] - 3.0) < 0.02:
                r3[i] = (d_vals[i] - d_vals[i - 3]) / 3.0
        df["ramp_3h"] = r3

        # Interchange relative to demand (%)  I_rel = 100*I/D
        df["ic_rel"] = 100.0 * df["interchange_mwh"] / df["demand_mwh"]

        frames.append(df[[
            "event_id", "t",
            "demand_mwh", "forecast_mwh", "interchange_mwh",
            "demand_norm", "forecast_error_pct", "ramp_3h", "ic_rel",
        ]])
        meta_rows.append({
            "event_id":       eid,
            "model_role":     ev["model_role"],
            "alignment_type": alignment_type,
            "t0_utc":         t0.isoformat(),
        })

    aligned = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    meta    = pd.DataFrame(meta_rows)
    return aligned, meta


# ---------------------------------------------------------------------------
# Shared figure helpers
# ---------------------------------------------------------------------------

def _new_fig(ylabel: str, title: str) -> tuple[plt.Figure, plt.Axes]:
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.axvline(0, color="black", linewidth=1.0, linestyle="--", zorder=5,
               label="t = 0")
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
    atype = row.iloc[0]["alignment_type"]
    return f"{eid}  [peak]" if atype == "peak_demand" else eid


def _save(fig: plt.Figure, name: str) -> Path:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    path = FIGURES_DIR / name
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def _plot_all(aligned: pd.DataFrame, meta: pd.DataFrame,
              col: str, ax: plt.Axes, zeroline: bool = True) -> None:
    if zeroline:
        ax.axhline(0, color="gray", linewidth=0.6, linestyle=":", zorder=1)
    for i, (eid, grp) in enumerate(aligned.groupby("event_id", sort=False)):
        grp = grp.sort_values("t")
        ax.plot(grp["t"], grp[col],
                color=_COLORS[i % len(_COLORS)],
                label=_legend_label(meta, eid),
                **_LINE_KW)


# ---------------------------------------------------------------------------
# The four figures
# ---------------------------------------------------------------------------

def fig_demand_norm(aligned: pd.DataFrame, meta: pd.DataFrame) -> Path:
    fig, ax = _new_fig(
        ylabel="D*ₜ  =  Dₜ / max(Dₜ)   [window-normalised]",
        title=(
            "Fig 1 — Normalised demand\n"
            r"$D^*_t = D_t\,/\,\max(D_{\mathrm{window}})$   "
            "(seasonal normalisation pending NOAA integration)"
        ),
    )
    _plot_all(aligned, meta, "demand_norm", ax, zeroline=False)
    ax.axhline(1.0, color="gray", linewidth=0.6, linestyle=":", zorder=1)
    ax.set_ylim(0.48, 1.06)
    ax.legend(fontsize=8.5, loc="lower left", framealpha=0.85, ncol=2)
    fig.tight_layout()
    return _save(fig, "fig1_demand_norm.png")


def fig_forecast_error(aligned: pd.DataFrame, meta: pd.DataFrame) -> Path:
    fig, ax = _new_fig(
        ylabel=r"$FE_t = 100\,(D_t - \hat{D}_t)\,/\,\hat{D}_t$   [%]",
        title="Fig 2 — Demand forecast error (%)",
    )
    _plot_all(aligned, meta, "forecast_error_pct", ax)
    ax.legend(fontsize=8.5, loc="lower left", framealpha=0.85, ncol=2)
    fig.tight_layout()
    return _save(fig, "fig2_forecast_error.png")


def fig_ramp(aligned: pd.DataFrame, meta: pd.DataFrame) -> Path:
    fig, ax = _new_fig(
        ylabel=r"$R_{3,t} = (D_t - D_{t-3})\,/\,3$   [MW/h]",
        title="Fig 3 — 3-hour demand ramp rate",
    )
    _plot_all(aligned, meta, "ramp_3h", ax)
    ax.legend(fontsize=8.5, loc="lower left", framealpha=0.85, ncol=2)
    fig.tight_layout()
    return _save(fig, "fig3_ramp_3h.png")


def fig_interchange(aligned: pd.DataFrame, meta: pd.DataFrame) -> Path:
    fig, ax = _new_fig(
        ylabel=r"$I^{\mathrm{rel}}_t = 100\,I_t\,/\,D_t$   [%]",
        title="Fig 4 — Net interchange as % of demand\n(positive = net importer)",
    )
    _plot_all(aligned, meta, "ic_rel", ax)
    ax.legend(fontsize=8.5, loc="lower left", framealpha=0.85, ncol=2)
    fig.tight_layout()
    return _save(fig, "fig4_interchange_rel.png")


# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------

def build_summary(aligned: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    """Per-event stats computed over t in [T_MIN, 0]."""
    rows = []
    pre   = aligned[aligned["t"] <= 0]
    full  = aligned

    for _, mr in meta.iterrows():
        eid = mr["event_id"]
        g   = pre[pre["event_id"] == eid]
        gf  = full[full["event_id"] == eid]

        def _s(series, fn):
            s = series.dropna()
            return round(float(fn(s)), 1) if len(s) else float("nan")

        # Value at t=0 (closest available row)
        near_t0 = gf.iloc[(gf["t"].abs()).argsort().iloc[:1]]
        fe_t0 = round(float(near_t0["forecast_error_pct"].iloc[0]), 2) if len(near_t0) else float("nan")
        ic_t0 = round(float(near_t0["ic_rel"].iloc[0]),              2) if len(near_t0) else float("nan")

        # Peak demand hour (relative to t=0)
        if g["demand_mwh"].notna().any():
            peak_t = round(float(g.loc[g["demand_mwh"].idxmax(), "t"]), 1)
        else:
            peak_t = float("nan")

        rows.append({
            "event_id":               eid,
            "model_role":             mr["model_role"],
            "alignment_type":         mr["alignment_type"],
            "t0_utc":                 mr["t0_utc"],
            "peak_demand_mw":         _s(g["demand_mwh"],         np.max),
            "peak_demand_t":          peak_t,
            "max_forecast_error_pct": _s(g["forecast_error_pct"], np.max),
            "min_forecast_error_pct": _s(g["forecast_error_pct"], np.min),
            "forecast_error_at_t0":   fe_t0,
            "max_ramp_3h_mw_per_h":   _s(g["ramp_3h"],            np.max),
            "min_ramp_3h_mw_per_h":   _s(g["ramp_3h"],            np.min),
            "min_interchange_mw":     _s(g["interchange_mwh"],    np.min),
            "max_interchange_mw":     _s(g["interchange_mwh"],    np.max),
            "interchange_pct_at_t0":  ic_t0,
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run() -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    TABLES_DIR.mkdir(parents=True, exist_ok=True)

    events = _load_events()
    aligned, meta = load_aligned(events)

    print(f"Aligned {aligned['event_id'].nunique()} events  "
          f"({len(aligned)} rows in [{T_MIN}h, {T_MAX}h])\n")
    print(meta[["event_id", "model_role", "alignment_type", "t0_utc"]].to_string(index=False))

    p1 = fig_demand_norm(aligned, meta)
    p2 = fig_forecast_error(aligned, meta)
    p3 = fig_ramp(aligned, meta)
    p4 = fig_interchange(aligned, meta)
    for p in (p1, p2, p3, p4):
        print(f"  → {p.relative_to(PROJECT_ROOT)}")

    summary = build_summary(aligned, meta)
    spath   = TABLES_DIR / "event_summary.csv"
    summary.to_csv(spath, index=False)
    print(f"\nSummary table → {spath.relative_to(PROJECT_ROOT)}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    run()
