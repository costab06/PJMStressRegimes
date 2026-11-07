# OpenAgentFabric migration — operational development

Status: **main is the active development branch**. The original implementation is preserved at `legacy/pre-oaf`. CI runs the OAF adapter tests with Redis and the existing scientific suite.

## Long-term objective

A continuously running PJM grid-risk intelligence platform, with OAF handling durable agent execution, acquisition agents gathering EIA/PJM/weather data, replaceable statistical or machine-learning models, and an evidence-backed intelligence and alert layer. SECAgents-style intelligence may be integrated later; no predictive model or live alerting is claimed yet.

## Scientific invariants

- `research_spec.yaml` is the methodological authority; do not rewrite the frozen v1 feature definitions or episode classifications.
- Frozen v1 is LoadZ, ForecastErrorZ, RampZ, InterchangeZ, using the 2021 PJM hour-by-month baseline.
- Keep scientific calculations independently runnable without OAF or Redis.
- Distinguish S3 operational emergencies from actual customer interruptions; these are not identical prediction targets.
- Prevent lookahead: feature inputs must contain only observations available at prediction time. Source timestamps alone do not prove publication-time availability; future work must capture release/ingestion timestamps and revisions.
- Preserve hashes, source versions, baseline versions, episode IDs and model versions. No silent filling of missing inputs or double counting retried events.
- Historical event-relative features (which use an eventual event t=0) must never be used as if t=0 were known in live inference.

## Implemented

1. `oaf/eia930_agent.py`: OAF BaseAgent wrapper around existing EIA-930 acquisition, coverage checks, content-addressed artifacts, durable completion event.
2. `oaf/compare_historical.py`: API or offline monthly-cache ingestion comparison, source hashes and evidence reports; real historical source parity remains to be demonstrated.
3. `oaf/feature_agent.py`: point-in-time feature adapter wrapping `features.seasonal.apply_zscore`. Requires a four-hour contiguous window ending at as_of, rejects future rows, duplicate timestamps, missing data and non-finite output, and publishes a hashed feature artifact. This is a feature calculation, **not a disruption-risk prediction**.
4. `oaf/acquisition_coordinator.py`: OAF BaseAgent handling `grid.acquisition.cycle.requested`; validates an explicit UTC decision hour, computes an inclusive EIA window using configurable lookback and publication-lag assumptions, and emits `grid.eia930.requested` plus `grid.acquisition.cycle.dispatched` atomically under OAF. This is dispatch only, not an autonomous scheduler, a completed ingestion cycle, or verified data freshness.\n5. Unit tests, Redis integration tests, and main-branch CI.

## Next implementation milestones

1. Verify numerical parity on archived real PJM windows with a frozen baseline. Record source availability timestamps, including data revisions, for defensible replay.
2. Complete acquisition orchestration: add an external recurring scheduler, durable cycle identity, per-source freshness checks, completion aggregation, gap detection and evidence. The current coordinator only dispatches one explicit cycle.
3. Implement PJM operating-notice acquisition as the second agent; NOAA and adjacent-BA acquisition follow.
4. Introduce versioned model interfaces for training and point-in-time inference. Start with transparent stress indicators; calibrate predictive probabilities only with sufficient independent outcomes and temporal validation.
5. Add an intelligence/alert layer that distinguishes missing data from normal risk, provides evidence and uncertainty, and audits alert decisions.

## Validation gates

- Existing research suite stays green; scientific output is not silently changed.
- OAF retries/recovery/idempotence tested with Redis.
- Same inputs and baseline yield identical feature artifacts; modified inputs or baseline change fingerprints.
- No future observations, missing hourly coverage or invalid baseline cells accepted.
- No production forecasting, alerting, or real-data parity claims until those capabilities are tested.
