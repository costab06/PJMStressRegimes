"""Post-ingest validation checks for EIA-930 hourly data.

Called automatically by the pipeline after each event fetch, before the
coverage table is written. Any FAIL result should be investigated and
resolved before proceeding to feature engineering.

Checks
------
tz_utc       Is the timestamp column timezone-aware UTC?
no_dst       No 23h or 25h days (DST artifact from wrong timezone handling).
no_dups      No duplicate timestamps within the window.
no_gaps      No gaps longer than GAP_WARN_HOURS in the core series.
sentinels    No EIA sentinel values (9999, -9999) in numeric columns.
demand_pos   All demand values are positive.
interchange  Interchange is bounded to a plausible MW range.
df_era       Forecast column is NaN-only before DF_START (expected absence).
monotone     Timestamps are strictly increasing.
"""

from __future__ import annotations

import dataclasses
from typing import Optional

import pandas as pd
import numpy as np

# EIA-930 day-ahead demand forecast first became available for PJM
DF_START = pd.Timestamp("2015-07-01", tz="UTC")

# Gaps longer than this in demand/forecast/interchange are flagged
GAP_WARN_HOURS = 3

# EIA sentinel values that should be treated as missing, not real data
EIA_SENTINELS = {9999, -9999, 99999, -99999}

# Demand sanity bounds for PJM (MW). Extreme cold/heat peaks are ~165 GW.
DEMAND_MIN_MW = 10_000
DEMAND_MAX_MW = 200_000

# Interchange sanity bounds (PJM net interchange, MW)
INTERCHANGE_MIN_MW = -60_000
INTERCHANGE_MAX_MW = 60_000


@dataclasses.dataclass
class CheckResult:
    name: str
    passed: bool
    level: str          # "FAIL" | "WARN" | "INFO"
    detail: str

    def __str__(self) -> str:
        icon = "✓" if self.passed else ("✗" if self.level == "FAIL" else "⚠")
        return f"  [{self.level:4s}] {icon} {self.name}: {self.detail}"


def validate(
    df: pd.DataFrame,
    event_id: str,
    window_start: Optional[pd.Timestamp] = None,
    window_end: Optional[pd.Timestamp] = None,
) -> list[CheckResult]:
    """Run all validation checks on a fetched EIA-930 DataFrame.

    Args:
        df: DataFrame with at minimum [timestamp_utc, ba] and one or more
            of [demand_mwh, forecast_mwh, interchange_mwh].
        event_id: Used in diagnostic messages only.
        window_start: Expected start of the analysis window.
        window_end: Expected end of the analysis window.

    Returns:
        List of CheckResult objects. Print them or inspect .passed / .level.
    """
    results: list[CheckResult] = []

    # ------------------------------------------------------------------
    # 0. Ensure timestamp_utc is datetime — all subsequent checks depend on it
    # ------------------------------------------------------------------
    raw_ts = df["timestamp_utc"]
    if not pd.api.types.is_datetime64_any_dtype(raw_ts):
        # Try to coerce; if it fails, report and skip remaining checks
        try:
            df = df.copy()
            df["timestamp_utc"] = pd.to_datetime(raw_ts, utc=True)
            results.append(CheckResult(
                "ts_parse", False, "WARN",
                f"timestamp_utc dtype was {raw_ts.dtype}; coerced to datetime. "
                f"Check that ingest applies pd.to_datetime(..., utc=True) before returning."
            ))
        except Exception as exc:
            results.append(CheckResult(
                "ts_parse", False, "FAIL",
                f"Cannot parse timestamp_utc as datetime (dtype={raw_ts.dtype}): {exc}"
            ))
            return results

    # ------------------------------------------------------------------
    # 1. Timezone check — must be UTC-aware, not naive or wrong zone
    # ------------------------------------------------------------------
    ts = df["timestamp_utc"]
    if hasattr(ts.dtype, "tz") and ts.dtype.tz is not None:
        tz_name = str(ts.dtype.tz)
        is_utc = tz_name in ("UTC", "utc", "Etc/UTC")
        results.append(CheckResult(
            "tz_utc", is_utc, "FAIL" if not is_utc else "INFO",
            f"timezone={tz_name}" if is_utc else
            f"WRONG TIMEZONE: {tz_name}. "
            f"EIA-930 period strings may be local Eastern time — re-check _paginate() conversion."
        ))
    else:
        results.append(CheckResult(
            "tz_utc", False, "FAIL",
            "timestamp_utc is timezone-naive. "
            "pd.to_datetime(..., utc=True) must be applied at ingest time."
        ))

    # ------------------------------------------------------------------
    # 2. Monotone timestamps
    # ------------------------------------------------------------------
    sorted_ts = ts.sort_values().reset_index(drop=True)
    is_monotone = (ts.reset_index(drop=True) == sorted_ts).all()
    n_ooo = int((ts.reset_index(drop=True) != sorted_ts).sum())
    results.append(CheckResult(
        "monotone", bool(is_monotone), "WARN" if not is_monotone else "INFO",
        "OK" if is_monotone else f"{n_ooo} out-of-order rows"
    ))

    # ------------------------------------------------------------------
    # 3. Duplicate timestamps
    # ------------------------------------------------------------------
    n_dups = int(ts.duplicated().sum())
    results.append(CheckResult(
        "no_dups", n_dups == 0, "FAIL" if n_dups > 0 else "INFO",
        "OK" if n_dups == 0 else
        f"{n_dups} duplicate timestamps — likely DST local-time confusion. "
        f"First duplicate: {ts[ts.duplicated()].iloc[0]}"
    ))

    # ------------------------------------------------------------------
    # 4. DST artifact — no 23h or 25h days (interior days only)
    # ------------------------------------------------------------------
    ts_sorted = ts.sort_values()
    daily = ts_sorted.dt.floor("D").value_counts()
    # The first and last calendar days of the window are naturally truncated
    # when the fetch window doesn't start/end on a midnight boundary. Exclude
    # them; only interior days must have exactly 24 rows.
    first_day = ts_sorted.iloc[0].floor("D")
    last_day = ts_sorted.iloc[-1].floor("D")
    interior = daily[(daily.index != first_day) & (daily.index != last_day)]
    bad_interior = interior[interior != 24]
    if bad_interior.empty:
        n_edge = int((daily != 24).sum())
        edge_note = f" ({n_edge} edge-truncated day(s) excluded)" if n_edge else ""
        results.append(CheckResult("no_dst", True, "INFO",
                                   f"all interior days have exactly 24 hours{edge_note}"))
    else:
        results.append(CheckResult(
            "no_dst", False, "FAIL",
            f"Interior days with ≠24 rows: {dict(bad_interior)}. "
            f"This is the signature of local-time timestamps mishandled as UTC."
        ))

    # ------------------------------------------------------------------
    # 5. Gaps in demand series (most reliable completeness indicator)
    # ------------------------------------------------------------------
    if "demand_mwh" in df.columns:
        ts_sorted = ts.sort_values().reset_index(drop=True)
        diffs = ts_sorted.diff().dropna()
        one_h = pd.Timedelta("1h")
        gap_mask = diffs > one_h * (GAP_WARN_HOURS + 0.5)
        n_gaps = int(gap_mask.sum())
        if n_gaps == 0:
            results.append(CheckResult("no_gaps", True, "INFO", "no gaps > 3h in demand series"))
        else:
            gap_sizes = (diffs[gap_mask] / one_h).astype(int)
            worst = int(gap_sizes.max())
            results.append(CheckResult(
                "no_gaps", False, "WARN" if worst < 24 else "FAIL",
                f"{n_gaps} gap(s) > {GAP_WARN_HOURS}h; worst={worst}h. "
                f"Gaps ≤3h will be linearly interpolated; longer ones will remain NaN."
            ))

    # ------------------------------------------------------------------
    # 6. EIA sentinel values
    # ------------------------------------------------------------------
    numeric_cols = [c for c in ["demand_mwh", "forecast_mwh", "interchange_mwh", "generation_mwh"]
                    if c in df.columns]
    sentinel_hits: dict[str, int] = {}
    for col in numeric_cols:
        n = int(df[col].isin(EIA_SENTINELS).sum())
        if n:
            sentinel_hits[col] = n
    if sentinel_hits:
        results.append(CheckResult(
            "sentinels", False, "FAIL",
            f"Sentinel values found: {sentinel_hits}. "
            f"These must be replaced with NaN before interpolation."
        ))
    else:
        results.append(CheckResult(
            "sentinels", True, "INFO",
            f"No sentinel values in {numeric_cols}"
        ))

    # ------------------------------------------------------------------
    # 7. Demand positivity and range
    # ------------------------------------------------------------------
    if "demand_mwh" in df.columns:
        d = df["demand_mwh"].dropna()
        if d.empty:
            results.append(CheckResult(
                "demand_pos", False, "FAIL",
                "demand_mwh column is entirely NaN — API returned no demand data."
            ))
        else:
            n_neg = int((d < 0).sum())
            n_low = int((d < DEMAND_MIN_MW).sum())
            n_high = int((d > DEMAND_MAX_MW).sum())
            if n_neg:
                results.append(CheckResult(
                    "demand_pos", False, "FAIL",
                    f"{n_neg} negative demand values — likely sentinel or unit error."
                ))
            elif n_low or n_high:
                results.append(CheckResult(
                    "demand_pos", False, "WARN",
                    f"{n_low} values below {DEMAND_MIN_MW:,} MW, "
                    f"{n_high} above {DEMAND_MAX_MW:,} MW. "
                    f"Check for unit mismatch (GW vs MW) or bad data."
                ))
            else:
                results.append(CheckResult(
                    "demand_pos", True, "INFO",
                    f"range [{int(d.min()):,}, {int(d.max()):,}] MW — plausible"
                ))

    # ------------------------------------------------------------------
    # 8. Interchange bounds
    # ------------------------------------------------------------------
    if "interchange_mwh" in df.columns:
        ic = df["interchange_mwh"].dropna()
        if ic.empty:
            results.append(CheckResult(
                "interchange", False, "FAIL",
                "interchange_mwh column is entirely NaN — API returned no interchange data."
            ))
        else:
            n_out = int(((ic < INTERCHANGE_MIN_MW) | (ic > INTERCHANGE_MAX_MW)).sum())
            if n_out:
                results.append(CheckResult(
                    "interchange", False, "WARN",
                    f"{n_out} interchange values outside [{INTERCHANGE_MIN_MW:,}, {INTERCHANGE_MAX_MW:,}] MW."
                ))
            else:
                results.append(CheckResult(
                    "interchange", True, "INFO",
                    f"range [{int(ic.min()):,}, {int(ic.max()):,}] MW — plausible"
                ))

    # ------------------------------------------------------------------
    # 9. Forecast availability era check
    # ------------------------------------------------------------------
    if "forecast_mwh" in df.columns:
        raw_min = ts.min()
        # Normalise to UTC for comparison regardless of input tz state
        first_ts = pd.Timestamp(raw_min).tz_localize("UTC") if raw_min.tzinfo is None else raw_min.tz_convert("UTC")
        n_fc = int(df["forecast_mwh"].notna().sum())
        if first_ts < DF_START and n_fc == 0:
            results.append(CheckResult(
                "df_era", True, "INFO",
                f"Window predates DF_START ({DF_START.date()}); forecast absence is expected."
            ))
        elif first_ts < DF_START and n_fc > 0:
            results.append(CheckResult(
                "df_era", False, "WARN",
                f"Window predates DF_START ({DF_START.date()}) but {n_fc} forecast rows present — verify."
            ))
        elif n_fc == 0:
            results.append(CheckResult(
                "df_era", False, "FAIL",
                f"No forecast values in post-{DF_START.date()} window. "
                f"API type='DF' may have failed silently."
            ))
        else:
            results.append(CheckResult("df_era", True, "INFO", f"{n_fc} forecast hours present"))

    return results


def print_report(results: list[CheckResult], event_id: str) -> None:
    """Print a formatted validation report."""
    n_fail = sum(1 for r in results if not r.passed and r.level == "FAIL")
    n_warn = sum(1 for r in results if not r.passed and r.level == "WARN")
    status = "FAIL" if n_fail else ("WARN" if n_warn else "OK")
    print(f"  Validation [{status}]  {n_fail} fail  {n_warn} warn  —  {event_id}")
    for r in results:
        if not r.passed or r.level != "INFO":
            print(r)


def has_failures(results: list[CheckResult]) -> bool:
    return any(not r.passed and r.level == "FAIL" for r in results)
