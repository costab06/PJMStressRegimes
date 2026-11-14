"""Intervention-aware early-warning analysis (exploratory).

Requires outputs from fit_temperature_regimes and sweep_warning_thresholds.
Uses fixed p99 Isolation Forest, and predeclared 3-of-6 / 6-of-12
persistence checks. Reconstructs one chronological reference warning stream
across weather regimes, including missing-hour breaks. DOES NOT substitute
operator-action times for missing first-alert times.
Run: python -m gridregime.pipeline.evaluate_early_warning
"""
from __future__ import annotations

import json
import numpy as np
import pandas as pd
from gridregime.pipeline.fit_temperature_regimes import ROOT, OUT as MODEL_OUT
from gridregime.pipeline.sweep_warning_thresholds import OUT as SWEEP_OUT

OUT = ROOT / "results/early_warning_v1"
DETECTOR = "isolation_score"
Q = 0.99
RULES = {"raw": (1, 1), "3_of_6": (3, 6), "6_of_12": (6, 12)}


def persistence(frame, n, window):
    """Trailing consecutive hourly slots; missing hours count as non-warning."""
    x = frame.sort_values("timestamp_utc").copy()
    if x["timestamp_utc"].duplicated().any():
        raise ValueError("Duplicate hourly timestamps")
    if x.empty:
        x["trigger"] = pd.Series(dtype=bool)
        return x
    # Reindex to a complete UTC hourly grid so missing hours cannot masquerade
    # as consecutive measurements. Missing hours never trigger warnings.
    idx = pd.date_range(x["timestamp_utc"].min(), x["timestamp_utc"].max(), freq="h", tz="UTC")
    x = x.set_index("timestamp_utc").reindex(idx)
    x.index.name = "timestamp_utc"
    valid = x["warning"].fillna(False).astype(bool)
    count = valid.astype(int).rolling(window, min_periods=window).sum()
    x["trigger"] = valid & count.ge(n)
    # Return only originally observed hours, not manufactured missing scores.
    x = x.loc[x["warning"].notna()].reset_index()
    return x


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    events = pd.read_csv(ROOT / "metadata/events.csv")
    event_anchors = []
    for episode, group in events.groupby("episode_id"):
        severity = group["severity"].unique()
        if len(severity) != 1:
            raise ValueError(f"Inconsistent severity: {episode}")
        first = pd.to_datetime(group["first_alert_time"].dropna(), utc=True)
        action = pd.to_datetime(group["operator_action_time"].dropna(), utc=True)
        event_anchors.append({
            "episode_id": episode, "severity": severity[0],
            "first_documented_alert_utc": first.min() if len(first) else pd.NaT,
            "first_operator_action_utc": action.min() if len(action) else pd.NaT,
            "first_alert_available": bool(len(first)),
            "anchor_source": "metadata/events.csv (source timestamps need verification)"
        })
    anchors = pd.DataFrame(event_anchors)
    anchors.to_csv(OUT / "first_alert_anchor_audit.csv", index=False)

    thresholds = pd.read_csv(SWEEP_OUT / "thresholds.csv")
    thresholds = thresholds.loc[thresholds["detector"].eq(DETECTOR) &
                                np.isclose(thresholds["training_quantile"], Q)]
    if thresholds["regime"].duplicated().any():
        raise ValueError("Duplicate regime thresholds")
    cutoffs = dict(zip(thresholds["regime"], thresholds["score_threshold"]))
    if set(cutoffs) != {"cold", "moderate", "hot"}:
        raise ValueError(f"Expected all three regime thresholds, got {cutoffs}")

    ref = pd.read_csv(SWEEP_OUT / "oct_dec_2021_hourly_replay.csv",
                      parse_dates=["timestamp_utc"])
    ref = ref.loc[ref["detector"].eq(DETECTOR) &
                  np.isclose(ref["training_quantile"], Q)].copy()
    ref["timestamp_utc"] = pd.to_datetime(ref["timestamp_utc"], utc=True)
    ref["warning"] = ref["score"] > ref["regime"].map(cutoffs)
    ref = ref.sort_values("timestamp_utc")
    if ref["timestamp_utc"].duplicated().any():
        raise ValueError("Reference contains duplicate cross-regime hours")
    # Event traces are truncated by OLD S2/S3 anchors. A common first-alert
    # comparison is possible only when that first alert matches the old anchor.
    trace = pd.read_csv(MODEL_OUT / "episode_hourly_temperature_scores.csv")
    trace["timestamp_utc"] = pd.to_datetime(trace["timestamp_utc"], utc=True)
    trace = trace.loc[trace["detector"].eq(DETECTOR)].copy()
    trace["warning"] = trace["score"] > trace["regime"].map(cutoffs)
    if trace["warning"].isna().any():
        raise ValueError("Unknown weather regime in episode trace")
    summary, reference, episode_rows = [], [], []
    for name, (n, window) in RULES.items():
        replay = persistence(ref, n, window)
        # Consecutive trigger runs, splitting at missing hours.
        flag = replay["trigger"].astype(bool)
        begins = flag & (~flag.shift(fill_value=False) |
                         replay["timestamp_utc"].diff().ne(pd.Timedelta(hours=1)))
        reference.append({
            "rule": name, "scored_hours": len(replay),
            "trigger_hours": int(flag.sum()),
            "trigger_fraction": float(flag.mean()) if len(flag) else np.nan,
            "trigger_runs": int(begins.sum()),
            "calendar_days": (replay["timestamp_utc"].max() -
                              replay["timestamp_utc"].min()).total_seconds()/86400 + 1/24,
            "runs_per_30_calendar_days": (int(begins.sum()) * 30 /
                ((replay["timestamp_utc"].max() - replay["timestamp_utc"].min()
                 ).total_seconds()/86400 + 1/24))
        })
        for episode, g in trace.groupby("episode_id"):
            g = g.sort_values("timestamp_utc")
            if g["timestamp_utc"].duplicated().any():
                raise ValueError(f"Conflicting overlapping event hours: {episode}")
            a = anchors.loc[anchors["episode_id"].eq(episode)].iloc[0]
            anchor = a["first_documented_alert_utc"]
            if pd.isna(anchor):
                episode_rows.append({"rule": name, "episode_id": episode,
                    "severity": a["severity"], "status": "missing_first_alert",
                    "detected": pd.NA, "lead_hours": np.nan})
                continue
            # Never extrapolate: original traces are only pre-old-anchor.
            last_complete = g["timestamp_utc"].max() + pd.Timedelta(hours=1)
            if last_complete < anchor - pd.Timedelta(hours=1):
                status = "incomplete_pre_alert_trace"
            else:
                status = "available_trace"
            eligible = g.loc[g["timestamp_utc"] + pd.Timedelta(hours=1) <= anchor]
            if eligible.empty:
                status = "no_pre_alert_hours"
                episode_rows.append({"rule": name, "episode_id": episode,
                    "severity": a["severity"], "status": status,
                    "detected": pd.NA, "lead_hours": np.nan})
                continue
            out = persistence(eligible, n, window)
            triggered = out.loc[out["trigger"]]
            first = triggered["timestamp_utc"].min() if len(triggered) else pd.NaT
            lead = ((anchor - first - pd.Timedelta(hours=1)).total_seconds()/3600
                    if pd.notna(first) else np.nan)
            episode_rows.append({"rule": name, "episode_id": episode,
                "severity": a["severity"], "status": status,
                "detected": bool(len(triggered)), "lead_hours": lead,
                "observed_pre_alert_hours": len(eligible),
                "trigger_hours": len(triggered)})
    pd.DataFrame(reference).to_csv(OUT / "continuous_reference_alert_burden.csv", index=False)
    episodes = pd.DataFrame(episode_rows)
    episodes.to_csv(OUT / "episode_persistent_warnings.csv", index=False)
    valid = episodes.loc[episodes["status"].eq("available_trace")]
    if not valid.empty:
        summary = valid.groupby(["rule", "severity"], dropna=False).agg(
            episodes=("episode_id", "nunique"),
            detected=("detected", "sum"),
            median_lead_hours=("lead_hours", "median")
        ).reset_index()
    else:
        summary = pd.DataFrame()
    summary.to_csv(OUT / "episode_summary.csv", index=False)
    (OUT / "audit.json").write_text(json.dumps({
        "status": "exploratory; no operational validation",
        "detector": DETECTOR, "quantile": Q, "rules": RULES,
        "reference": "Oct-Dec 2021; complete chronological regime-aware replay",
        "first_alert_missing": anchors.loc[~anchors["first_alert_available"],
                                           "episode_id"].tolist(),
        "warnings": [
            "S3 first public alert timestamps absent; cannot compute S3 lead time",
            "Event traces are truncated at prior mixed anchors; incomplete windows are flagged",
            "Public alert timestamps and sources require manual archival verification",
            "2021 normalization overlaps calibration replay; not independent",
            "Persistence starts cold at first available trace hour; 48h truncation",
            "Missing hours are treated as non-warning; trigger requires current-hour warning",
            "Reference 2021 has not been certified free of documented alerts",
            "No point-in-time data availability or operator intervention history"
        ]
    }, indent=2) + "\n")
    print("\nFirst-alert timestamp availability:")
    print(anchors[["episode_id","severity","first_alert_available"]].to_string(index=False))
    print("\nContinuous chronological reference warning burden:")
    print(pd.DataFrame(reference).to_string(index=False))
    print("\nEpisode persistence summary (comparable available traces only):")
    print(summary.to_string(index=False))
    print(f"\nSaved {OUT}/")


if __name__ == "__main__":
    run()
