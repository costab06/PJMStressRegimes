"""Seasonal (hour-of-day × month) baseline for demand normalization.

Builds a lookup table of μ and σ for each (hour_of_day, month) cell from a
set of "normal" reference parquet files, then applies it to produce z-scored
versions of demand, forecast error, 3-hour ramp, and interchange.

The baseline is intentionally computed from years that contain no events in
our catalog, so the reference distribution is not contaminated by stressed
periods.

Usage:
    from gridregime.features.seasonal import build_baseline, apply_zscore

    baseline = build_baseline(
        parquet_paths=list(Path("data/raw/eia930").glob("PJM_2021-*.parquet")),
    )
    df_z = apply_zscore(event_df, baseline)
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd


# Minimum samples per (hour, month) cell below which we report NaN rather than
# a noisy estimate.
MIN_CELL_N = 20


# Plausible PJM demand bounds — values outside this range are API artifacts
_DEMAND_MIN_MW = 10_000
_DEMAND_MAX_MW = 200_000


def build_baseline(
    parquet_paths: Sequence[Path],
    min_cell_n: int = MIN_CELL_N,
) -> pd.DataFrame:
    """Compute (hour_of_day, month) means and standard deviations.

    Loads all supplied parquet files, stacks them, and groups by
    (hour_of_day, month) to compute statistics for:
      demand_mwh, forecast_error_pct, ramp_3h, interchange_mwh

    Args:
        parquet_paths: Paths to monthly or annual parquet files containing
            at minimum [timestamp_utc, demand_mwh, forecast_mwh,
            interchange_mwh].
        min_cell_n: Cells with fewer observations return NaN stats.

    Returns:
        DataFrame indexed by (hour_of_day, month) with columns:
            demand_mean, demand_std,
            fe_mean, fe_std,
            ramp3_mean, ramp3_std,
            ic_mean, ic_std
    """
    frames: list[pd.DataFrame] = []
    for p in parquet_paths:
        df = pd.read_parquet(p)
        if "timestamp_utc" not in df.columns:
            continue
        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
        frames.append(df)

    if not frames:
        raise ValueError("No valid parquet files found for baseline computation")

    raw = pd.concat(frames, ignore_index=True)
    raw = raw.sort_values("timestamp_utc").drop_duplicates("timestamp_utc").reset_index(drop=True)

    # Drop rows with impossible demand values (EIA API artifacts / sentinels)
    n_before = len(raw)
    raw = raw[
        raw["demand_mwh"].isna() |
        ((raw["demand_mwh"] >= _DEMAND_MIN_MW) & (raw["demand_mwh"] <= _DEMAND_MAX_MW))
    ].copy()
    n_dropped = n_before - len(raw)
    if n_dropped:
        print(f"  build_baseline: dropped {n_dropped} rows with out-of-bounds demand")

    raw["hour_of_day"] = raw["timestamp_utc"].dt.hour
    raw["month"]       = raw["timestamp_utc"].dt.month

    # Forecast error (%)
    raw["fe_pct"] = (
        100.0 * (raw["demand_mwh"] - raw["forecast_mwh"]) / raw["forecast_mwh"]
    )

    # 3-hour ramp: compute from sorted hourly series
    d = raw["demand_mwh"].values.astype(float)
    ts = raw["timestamp_utc"].values
    ramp3 = np.full(len(d), np.nan)
    one_h = np.timedelta64(1, "h")
    for i in range(3, len(d)):
        if (ts[i] - ts[i - 3]) == 3 * one_h:
            ramp3[i] = (d[i] - d[i - 3]) / 3.0
    raw["ramp_3h"] = ramp3

    def _cell_stats(group: pd.DataFrame) -> pd.Series:
        n = len(group)
        if n < min_cell_n:
            return pd.Series({
                "demand_mean": np.nan, "demand_std": np.nan,
                "fe_mean":     np.nan, "fe_std":     np.nan,
                "ramp3_mean":  np.nan, "ramp3_std":  np.nan,
                "ic_mean":     np.nan, "ic_std":     np.nan,
                "n": n,
            })
        return pd.Series({
            "demand_mean": group["demand_mwh"].mean(),
            "demand_std":  group["demand_mwh"].std(ddof=1),
            "fe_mean":     group["fe_pct"].mean(),
            "fe_std":      group["fe_pct"].std(ddof=1),
            "ramp3_mean":  group["ramp_3h"].mean(),
            "ramp3_std":   group["ramp_3h"].std(ddof=1),
            "ic_mean":     group["interchange_mwh"].mean(),
            "ic_std":      group["interchange_mwh"].std(ddof=1),
            "n": n,
        })

    baseline = (
        raw.groupby(["hour_of_day", "month"])
        .apply(_cell_stats, include_groups=False)
        .reset_index()
    )
    return baseline


def apply_zscore(
    df: pd.DataFrame,
    baseline: pd.DataFrame,
) -> pd.DataFrame:
    """Add z-scored columns to df using the precomputed baseline.

    Args:
        df: DataFrame with columns [timestamp_utc, demand_mwh, forecast_mwh,
            interchange_mwh].  Must have a "t" column (hours relative to t=0).
        baseline: Output of build_baseline().

    Returns:
        df with added columns:
            load_z, fe_z, ramp3_z, ic_z
            forecast_error_pct (raw %)
            ramp_3h            (raw MW/h)
    """
    df = df.copy().sort_values("t").reset_index(drop=True)

    df["hour_of_day"] = df["timestamp_utc"].dt.hour
    df["month"]       = df["timestamp_utc"].dt.month

    # Raw derived signals
    df["forecast_error_pct"] = (
        100.0 * (df["demand_mwh"] - df["forecast_mwh"]) / df["forecast_mwh"]
    )
    d_vals = df["demand_mwh"].values.astype(float)
    t_vals = df["t"].values.astype(float)
    ramp3 = np.full(len(d_vals), np.nan)
    for i in range(3, len(d_vals)):
        if abs(t_vals[i] - t_vals[i - 3] - 3.0) < 0.02:
            ramp3[i] = (d_vals[i] - d_vals[i - 3]) / 3.0
    df["ramp_3h"] = ramp3

    # Merge baseline stats
    df = df.merge(baseline[["hour_of_day", "month",
                             "demand_mean", "demand_std",
                             "fe_mean",     "fe_std",
                             "ramp3_mean",  "ramp3_std",
                             "ic_mean",     "ic_std"]],
                  on=["hour_of_day", "month"], how="left")

    def _z(val_col: str, mean_col: str, std_col: str) -> pd.Series:
        std = df[std_col].replace(0, np.nan)
        return (df[val_col] - df[mean_col]) / std

    df["load_z"]  = _z("demand_mwh",         "demand_mean", "demand_std")
    df["fe_z"]    = _z("forecast_error_pct", "fe_mean",     "fe_std")
    df["ramp3_z"] = _z("ramp_3h",            "ramp3_mean",  "ramp3_std")
    df["ic_z"]    = _z("interchange_mwh",    "ic_mean",     "ic_std")

    return df.drop(columns=["demand_mean", "demand_std", "fe_mean", "fe_std",
                             "ramp3_mean",  "ramp3_std",  "ic_mean", "ic_std"])


def save_baseline(baseline: pd.DataFrame, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    baseline.to_parquet(path, index=False)


def load_baseline(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)
