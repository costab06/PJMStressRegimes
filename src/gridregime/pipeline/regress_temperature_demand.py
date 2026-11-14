"""Simple OLS: PJM hourly demand versus temperature, separately cold/hot.

Run: python -m gridregime.pipeline.regress_temperature_demand
Uses the same trailing 24-hour temperature proxy and 40/70 F cutoffs as
fit_temperature_regimes. Reports 2021 reference and deduplicated event-window
samples separately to avoid pooling an event-enriched sample with normal hours.
This is descriptive association, not causation or out-of-sample prediction.
"""
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score

from gridregime.pipeline.fit_temperature_regimes import ROOT, WEATHER, weather_regimes

OUT = ROOT / "results/temperature_demand_regression_v1"


def data():
    weather = weather_regimes(WEATHER)
    raw = pd.concat([
        pd.read_parquet(ROOT / f"data/raw/eia930/PJM_2021-{m:02d}.parquet")
        for m in range(1, 13)], ignore_index=True)
    raw["timestamp_utc"] = pd.to_datetime(raw["timestamp_utc"], utc=True)
    if raw["timestamp_utc"].duplicated().any():
        raise ValueError("Duplicate 2021 reference hours")
    reference = raw[["timestamp_utc", "demand_mwh"]].copy()
    reference["sample"] = "reference_2021"
    catalog = pd.read_csv(ROOT / "metadata/events.csv")
    frames = []
    for eid in catalog["event_id"]:
        f = pd.read_parquet(ROOT / "data/interim/eia930" / f"{eid}.parquet")
        f["timestamp_utc"] = pd.to_datetime(f["timestamp_utc"], utc=True)
        frames.append(f[["timestamp_utc", "demand_mwh"]])
    events = pd.concat(frames, ignore_index=True)
    # Overlapping windows must not double-weight the same hour.
    disagreement = events.groupby("timestamp_utc")["demand_mwh"].agg(
        lambda x: x.max() - x.min())
    if disagreement.gt(1e-6).any():
        raise ValueError("Overlapping event windows disagree on demand values")
    events = events.drop_duplicates("timestamp_utc")
    events["sample"] = "event_windows_unique_hours"
    joined = pd.concat([reference, events], ignore_index=True)
    joined = joined.merge(weather, on="timestamp_utc", how="left", validate="many_to_one")
    # Same hour can occur in both groups; analyze groups separately.
    joined["demand_mwh"] = pd.to_numeric(joined["demand_mwh"], errors="coerce")
    return joined


def run():
    df = data()
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    for sample in ("reference_2021", "event_windows_unique_hours"):
        for regime in ("cold", "hot"):
            sub = df.loc[(df["sample"] == sample) &
                         (df["weather_regime"] == regime) &
                         df["demand_mwh"].between(10000, 200000)].dropna(
                             subset=["temperature_24h_f", "demand_mwh"]).copy()
            if len(sub) < 3:
                raise ValueError(f"{sample}/{regime}: only {len(sub)} valid observations")
            x = sub[["temperature_24h_f"]].to_numpy()
            y = sub["demand_mwh"].to_numpy()
            model = LinearRegression().fit(x, y)
            prediction = model.predict(x)
            results.append({
                "sample": sample, "regime": regime, "hours": len(sub),
                "temperature_min_f": float(x.min()),
                "temperature_max_f": float(x.max()),
                "slope_mwh_per_f": float(model.coef_[0]),
                "intercept_mwh": float(model.intercept_),
                "pearson_r": float(np.corrcoef(x[:, 0], y)[0, 1]),
                "r_squared": float(r2_score(y, prediction)),
                "rmse_mwh": float(np.sqrt(np.mean((y - prediction)**2)))
            })
    summary = pd.DataFrame(results)
    summary.to_csv(OUT / "temperature_demand_ols.csv", index=False)
    print("\nDemand ~ trailing 24h temperature (separate OLS per regime):")
    print(summary.to_string(index=False, float_format=lambda v: f"{v:,.3f}"))
    print(f"\nSaved {OUT / 'temperature_demand_ols.csv'}")
    print("Caution: hourly demand has strong diurnal/weekly structure; R² is in-sample.")
    return summary


if __name__ == "__main__":
    run()
