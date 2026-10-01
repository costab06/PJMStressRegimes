"""Milestone 1A pipeline: ingest → validate → event windows → coverage.

Entry point:
    python -m gridregime.pipeline.milestone_1a [--skip-generation] [--dry-run]
                                               [--halt-on-fail]

Steps
-----
1. Load events catalog (metadata/events.csv).
2. For each event, determine the fetch window:
     [window_start - PRE_HOURS, event_end + POST_HOURS]
3. Fetch EIA-930 for each required (BA, month) using the disk cache.
4. Run post-ingest validation checks (timezone, DST, sentinels, gaps, bounds).
   FAIL results are printed and, with --halt-on-fail, abort the run before
   writing any downstream artifacts.
5. Build the PJM hourly state table: one wide parquet per event under
     data/interim/eia930/{event_id}.parquet
6. Annotate hours_to_event and collect event windows.
7. Write data/processed/event_windows.parquet.
8. Compute and write results/tables/event_data_coverage.csv.

No modelling occurs here. All validation checks must pass before the coverage
table is accepted as a Milestone 1A artifact.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from gridregime.clean.validate import validate, print_report, has_failures

# Resolve project root from this file's location: src/gridregime/pipeline/
_HERE = Path(__file__).resolve()
PROJECT_ROOT = _HERE.parents[3]

EVENTS_CSV = PROJECT_ROOT / "metadata" / "events.csv"
INTERIM_DIR = PROJECT_ROOT / "data" / "interim" / "eia930"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
RESULTS_TABLES = PROJECT_ROOT / "results" / "tables"

# Hours of context included before window_start and after event_end
PRE_HOURS = 72
POST_HOURS = 72

# EIA-930 balance authority to use for each region token in events.csv.
# Add entries here as new regions are added to the catalog.
REGION_TO_BA: dict[str, list[str]] = {
    "PJM-RTO": ["PJM"],
    "MIDATL+SOUTHERN": ["PJM"],   # PJM-RTO covers both sub-regions in EIA-930
}


def _ba_for_event(region: str) -> list[str]:
    bas = REGION_TO_BA.get(region)
    if bas is None:
        raise ValueError(
            f"No BA mapping for region '{region}'. "
            f"Add it to REGION_TO_BA in milestone_1a.py."
        )
    return bas


def load_events() -> pd.DataFrame:
    df = pd.read_csv(EVENTS_CSV, parse_dates=["window_start", "event_end"])
    # Coerce timezone-aware strings
    for col in ["window_start", "event_end", "operator_action_time", "first_alert_time"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
    return df


def fetch_event_data(event: pd.Series, skip_generation: bool = False) -> pd.DataFrame:
    """Fetch EIA-930 for the full analysis window around one event."""
    from gridregime.ingest.eia930 import fetch_window

    bas = _ba_for_event(event["region"])
    fetch_start = (event["window_start"] - pd.Timedelta(hours=PRE_HOURS)).strftime("%Y-%m-%dT%H")
    fetch_end = (event["event_end"] + pd.Timedelta(hours=POST_HOURS)).strftime("%Y-%m-%dT%H")

    frames = []
    for ba in bas:
        print(f"  Fetching {ba} {fetch_start} → {fetch_end}")
        df = fetch_window(ba, fetch_start, fetch_end, skip_generation=skip_generation)
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]


def annotate_window(df: pd.DataFrame, event: pd.Series) -> pd.DataFrame:
    """Add hours_to_event column aligned to operator_action_time (or window_start)."""
    ref = event.get("operator_action_time")
    if pd.isna(ref):
        ref = event["window_start"]
    df = df.copy()
    df["hours_to_event"] = (df["timestamp_utc"] - ref).dt.total_seconds() / 3600
    df["event_id"] = event["event_id"]
    return df


def compute_coverage(df: pd.DataFrame, event: pd.Series) -> dict:
    """Compute per-event data coverage statistics."""
    # Window we expect to be populated
    win_start = event["window_start"] - pd.Timedelta(hours=PRE_HOURS)
    win_end = event["event_end"] + pd.Timedelta(hours=POST_HOURS)
    expected_hours = int((win_end - win_start).total_seconds() / 3600) + 1

    def _count(col: str) -> int:
        if col not in df.columns:
            return 0
        return int(df[col].notna().sum())

    demand_h = _count("demand_mwh")
    forecast_h = _count("forecast_mwh")
    generation_h = _count("generation_mwh")
    interchange_h = _count("interchange_mwh")

    # Weather hours will be filled in by the NOAA ingest step (future)
    weather_h = 0

    core_min = min(demand_h, forecast_h, interchange_h)
    missing_pct = round((1 - core_min / max(expected_hours, 1)) * 100, 1)

    return {
        "event_id": event["event_id"],
        "window_start": win_start.isoformat(),
        "window_end": win_end.isoformat(),
        "expected_hours": expected_hours,
        "demand_hours": demand_h,
        "forecast_hours": forecast_h,
        "generation_hours": generation_h,
        "interchange_hours": interchange_h,
        "weather_hours": weather_h,
        "missing_pct": missing_pct,
        "notes": "",
    }


def run(
    skip_generation: bool = False,
    dry_run: bool = False,
    halt_on_fail: bool = False,
) -> pd.DataFrame:
    """Execute the full Milestone 1A pipeline.

    Args:
        skip_generation: Skip fuel-type breakdown fetch (faster for testing).
        dry_run: Load events and print plan without hitting the API.
        halt_on_fail: Abort (sys.exit 2) if any validation check FAILs,
                      before writing any downstream artifacts.

    Returns:
        Coverage DataFrame (also written to results/tables/event_data_coverage.csv).
    """
    for d in [INTERIM_DIR, PROCESSED_DIR, RESULTS_TABLES]:
        d.mkdir(parents=True, exist_ok=True)

    events = load_events()
    print(f"Loaded {len(events)} events from {EVENTS_CSV.name}")

    coverage_rows = []
    all_windows: list[pd.DataFrame] = []
    any_validation_failure = False

    for _, event in events.iterrows():
        print(f"\n{'='*60}")
        print(f"Event: {event['event_id']}  ({event['event_name']})")

        if dry_run:
            fetch_start = event["window_start"] - pd.Timedelta(hours=PRE_HOURS)
            fetch_end = event["event_end"] + pd.Timedelta(hours=POST_HOURS)
            bas = _ba_for_event(event["region"])
            n_hours = int((fetch_end - fetch_start).total_seconds() / 3600) + 1
            print(f"  [dry-run] BA={','.join(bas)}  "
                  f"{fetch_start.strftime('%Y-%m-%dT%H:%MZ')} → "
                  f"{fetch_end.strftime('%Y-%m-%dT%H:%MZ')}  "
                  f"({n_hours}h)")
            continue

        try:
            df = fetch_event_data(event, skip_generation=skip_generation)
        except ValueError as exc:
            # Pre-2019 data not available via EIA v2 API
            print(f"  SKIP: {exc}")
            coverage_rows.append({
                "event_id": event["event_id"],
                "window_start": (event["window_start"] - pd.Timedelta(hours=PRE_HOURS)).isoformat(),
                "window_end": (event["event_end"] + pd.Timedelta(hours=POST_HOURS)).isoformat(),
                "expected_hours": None,
                "demand_hours": 0,
                "forecast_hours": 0,
                "generation_hours": 0,
                "interchange_hours": 0,
                "weather_hours": 0,
                "missing_pct": None,
                "notes": str(exc),
            })
            continue
        except Exception as exc:
            print(f"  ERROR fetching data: {exc}")
            continue

        # ------------------------------------------------------------------
        # Validate before writing anything
        # ------------------------------------------------------------------
        win_start = event["window_start"] - pd.Timedelta(hours=PRE_HOURS)
        win_end = event["event_end"] + pd.Timedelta(hours=POST_HOURS)
        checks = validate(df, event["event_id"], win_start, win_end)
        print_report(checks, event["event_id"])

        if has_failures(checks):
            any_validation_failure = True
            if halt_on_fail:
                print(f"\n  HALTING: validation FAIL on {event['event_id']}. "
                      f"No downstream artifacts written.")
                sys.exit(2)
            else:
                print(f"  Continuing despite FAIL (use --halt-on-fail to stop here).")

        # Cache the raw hourly state table for this event
        interim_path = INTERIM_DIR / f"{event['event_id']}.parquet"
        df.to_parquet(interim_path, index=False)
        print(f"  Saved → {interim_path.relative_to(PROJECT_ROOT)}")

        # Annotate and collect window
        windowed = annotate_window(df, event)
        all_windows.append(windowed)

        # Coverage
        row = compute_coverage(df, event)
        coverage_rows.append(row)
        status = "OK" if row["missing_pct"] < 5 else "WARN"
        print(f"  Coverage: demand={row['demand_hours']}h  forecast={row['forecast_hours']}h  "
              f"interchange={row['interchange_hours']}h  missing={row['missing_pct']}%  [{status}]")

    if not dry_run and all_windows:
        windows_path = PROCESSED_DIR / "event_windows.parquet"
        pd.concat(all_windows, ignore_index=True).to_parquet(windows_path, index=False)
        print(f"\nEvent windows → {windows_path.relative_to(PROJECT_ROOT)}")

    coverage_df = pd.DataFrame(coverage_rows)
    if not dry_run and not coverage_df.empty:
        cov_path = RESULTS_TABLES / "event_data_coverage.csv"
        coverage_df.to_csv(cov_path, index=False)
        print(f"\nCoverage table → {cov_path.relative_to(PROJECT_ROOT)}")
        print(coverage_df.to_string(index=False))

        incomplete = coverage_df[coverage_df["missing_pct"] >= 5]
        if not incomplete.empty:
            print("\nWARNING: the following events have >5% missing core data:")
            print(incomplete[["event_id", "missing_pct"]].to_string(index=False))
            print("Resolve gaps before proceeding to feature engineering.")

    if any_validation_failure:
        print("\nWARNING: one or more validation FAILs occurred. "
              "Inspect the output above before accepting these results.")

    return coverage_df


def main() -> None:
    parser = argparse.ArgumentParser(description="Milestone 1A: ingest and event windows")
    parser.add_argument("--skip-generation", action="store_true",
                        help="Skip fuel-type breakdown (faster for testing)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print plan without hitting the API")
    parser.add_argument("--halt-on-fail", action="store_true",
                        help="Abort on first validation FAIL before writing artifacts")
    args = parser.parse_args()

    coverage = run(
        skip_generation=args.skip_generation,
        dry_run=args.dry_run,
        halt_on_fail=args.halt_on_fail,
    )
    if not coverage.empty:
        incomplete = coverage[coverage["missing_pct"] >= 5]
        sys.exit(1 if not incomplete.empty else 0)


if __name__ == "__main__":
    main()
