# Reproducible acquisition and frozen-v1 feature milestone

This document describes the current acquisition-to-feature contract and the
remaining work required before a scientifically defensible historical replay.

## Inputs and invariants

* A cycle has a balancing authority, a **decision time** (`as_of`), a
  lookback, an assumed publication lag, and immutable required-source settings.
* The coordinator's inclusive **observation end** is
  `decision_as_of - publication_lag_hours`. This lag is an operational
  assumption, **not proof of upstream publication time**.
* The EIA-930 adapter rejects incomplete, extra, duplicate, null, or
  wrong-balancing-authority hourly observations and persists content-addressed
  CSV artifacts.
* The feature adapter requires four contiguous hours ending at its observation
  `as_of`. The optional `decision_as_of` separately records the decision
  timestamp and must not precede the observation end.
* The frozen-v1 vector is `load_z`, `fe_z`, `ramp3_z`, and `ic_z`.
  Source CSV and baseline Parquet hashes are included in each feature report.
* Archived and live PJM evidence are stored separately in the acquisition
  status hash. Neither currently verifies complete source coverage.
* Offline historical comparison rejects duplicate observation timestamps
  rather than silently selecting one of potentially conflicting revisions.

## Feature invocation

```python
from gridregime.oaf.feature_agent import compute_point_in_time_features

report = compute_point_in_time_features(
    source_path="path/to/eia930-content-addressed.csv",
    baseline_path="path/to/approved-frozen-baseline.parquet",
    as_of="2022-12-20T04:00Z",          # observation end
    decision_as_of="2022-12-20T06:00Z", # decision timestamp
    ba="PJM",
    output_dir="data/derived/features",
)
```

Re-running with identical source bytes, baseline bytes and timestamps produces
the same feature artifact hash. This is a deterministic calculation contract;
it is **not** a validated risk prediction.

## Explicitly unresolved

1. The `AcquisitionFeatureBridgeAgent` now consumes cycle dispatch, EIA-fetched
   and cycle-status events and emits `grid.features.requested` when the
   evidence is observation-ready. Its pure planner validates the artifact hash,
   source window and baseline hash. The bridge has event-order tests and a
   Redis-backed handler integration test; it is not yet deployed as a worker.
2. No repository-managed persistent worker deployment currently establishes continuous end-to-end operation. The Redis-backed test drives the agents' handlers directly; it does not run persistent OAF worker loops or establish exactly-once publication.
3. EIA and PJM publication/revision timestamps are not verified. A historical
   source snapshot can contain revisions unavailable at the decision time.
4. Redis evidence writes still need source-specific revision ordering and
   stale-event replay protection. The cycle's dispatch requirements are now
   rejected if conflicting dispatch payloads are received.
5. The scientific baseline requires explicit approval, frozen reference-period
   provenance and an independent numerical feature oracle.
6. The status policy deliberately reports
   `ready_for_predictive_inference=False`.

## Verification

CI runs the OAF adapter tests with Redis and OpenAgentFabric. The regression
suite includes tests for scheduler PJM propagation, observation-versus-decision
time, duplicate archival EIA hours and separation of live/archived PJM state.

A passing adapter test suite is **not** a substitute for a full-cycle replay
test, point-in-time availability verification or scientific validation.

## Deployment readiness and recovery

The existing `python -m gridregime.oaf.schedule_once` command submits a
single cycle to Redis. It does **not** start OAF workers. A production runner
must start and supervise these agents with a shared event bus and Redis:

1. `AcquisitionCoordinatorAgent` for cycle requests.
2. `EIA930AcquisitionAgent` for source acquisition.
3. `AcquisitionQualityAgent` for observation quality.
4. `PJMLiveAcquisitionAgent` if PJM is required.
5. `AcquisitionCycleStatusAgent` for evidence aggregation.
6. `AcquisitionFeatureBridgeAgent` with a pinned baseline path.
7. `PointInTimeFeatureAgent` with the same pinned baseline and an output directory.

No repository-managed worker runner is yet provided, and the external OAF
framework's worker lifecycle API must be verified before adding one. Workers
must share durable Redis, persistent artifact storage and an immutable baseline
snapshot. Operators must monitor dead-letter queues, pending cycles, worker
restarts, storage failures and replay attempts.

### Replay semantics

The bridge now rejects conflicting dispatch contracts for the same correlation
ID. A feature request uses a deterministic event ID derived from correlation,
source hash and baseline hash. This **does not** establish exactly-once
publication: the bridge can emit the same event ID more than once on replay,
and the downstream worker must handle duplicate delivery safely. The evidence
aggregator still needs revision-aware ordering; a stale assessment may replace
a newer assessment. Do not treat current readiness snapshots as an audited
publication-time evidence ledger.
