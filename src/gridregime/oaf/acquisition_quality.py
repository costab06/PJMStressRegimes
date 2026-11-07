"""Evaluate acquisition evidence without equating observed timestamps to publication freshness."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pandas as pd
from shared.agent.base import BaseAgent
from shared.eventbus.events import EventEnvelope

FETCHED = "grid.eia930.fetched"
ASSESSED = "grid.acquisition.quality.assessed"


def assess_eia_artifact(*, artifact_path: str | Path, end: str,
                        ba: str, max_lag_hours: int = 3,
                        checked_at: str | None = None) -> dict:
    """Check coverage and staleness of an artifact, not upstream publication time."""
    if not isinstance(max_lag_hours, int) or isinstance(max_lag_hours, bool) or max_lag_hours < 0:
        raise ValueError("max_lag_hours must be nonnegative integer")
    now = pd.Timestamp.now(tz="UTC") if checked_at is None else pd.Timestamp(checked_at)
    now = now.tz_localize("UTC") if now.tzinfo is None else now.tz_convert("UTC")
    target = pd.Timestamp(end)
    target = target.tz_localize("UTC") if target.tzinfo is None else target.tz_convert("UTC")
    frame = pd.read_csv(artifact_path)
    required = ("timestamp_utc", "ba", "demand_mwh", "forecast_mwh", "interchange_mwh")
    if frame.empty or any(c not in frame for c in required):
        raise ValueError("Missing required EIA columns")
    if frame[list(required)].isna().any().any() or not frame["ba"].eq(ba).all():
        raise ValueError("Invalid EIA observations")
    times = pd.to_datetime(frame["timestamp_utc"], utc=True)
    if times.duplicated().any():
        raise ValueError("Duplicate observation hours")
    latest = times.max()
    lag = (now - latest).total_seconds() / 3600
    if latest > now:
        status = "invalid-future-observation"
    elif latest < target:
        status = "incomplete-window"
    elif lag > max_lag_hours:
        status = "stale"
    else:
        status = "observations-current-publication-unverified"
    return {
        "ba": ba, "latest_observation_utc": latest.isoformat(),
        "expected_end_utc": target.isoformat(), "checked_at_utc": now.isoformat(),
        "lag_hours": lag, "status": status,
        "source_publication_time_verified": False,
    }


class AcquisitionQualityAgent(BaseAgent):
    def __init__(self, **kwargs):
        super().__init__(
            name="grid-acquisition-quality",
            subscribed_event_types={FETCHED},
            completion_event_type=ASSESSED, **kwargs,
        )

    async def handle_event(self, event: EventEnvelope) -> list[EventEnvelope]:
        if event.event_type != FETCHED or not isinstance(event.payload, dict):
            raise ValueError("Expected EIA acquisition completion")
        p = event.payload
        result = await asyncio.to_thread(
            assess_eia_artifact, artifact_path=p["artifact_path"],
            end=p["end"], ba=p["ba"],
        )
        return [EventEnvelope(
            event_type=ASSESSED, source_agent=str(self.name),
            correlation_id=event.correlation_id, causation_id=event.event_id,
            payload=result,
        )]
