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
2. A repository-managed worker runner now starts the seven OAF consumers using\n   a shared Redis event bus. Its construction has smoke tests; a deployed\n   persistent end-to-end run, restart/recovery test, and operations monitoring\n   are not yet verified. The Redis-backed integration test drives handlers\n   directly and does not establish exactly-once publication.
3. EIA and PJM publication/revision timestamps are not verified. A historical
   source snapshot can contain revisions unavailable at the decision time.
4. Redis evidence now rejects conflicting per-source payloads for a correlation
   ID instead of silently overwriting them. This is a conservative interim
   rule, **not revision-aware ordering**: legitimate source updates require a
   new cycle or an explicit versioned evidence policy. Status snapshots can
   still advance from pending to ready in the feature bridge, but status-event
   revision ordering and exactly-once publication are not established.
5. The feature worker now verifies the planner-supplied baseline and source
   hashes again at execution, rejecting modified inputs. Formal baseline
   approval, frozen reference-period provenance and an independent numerical
   feature oracle are still required.
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

The repository now includes a worker runner using OAF's verified `BaseAgent.run`\nAPI and `RedisEventBus`. Start it with:\n\n```bash\npython -m gridregime.oaf.run_workers \\\n  --redis-url redis://localhost:6379/0 \\\n  --baseline-path /persistent/baseline/frozen-v1.parquet \\\n  --artifact-dir /persistent/gridregime/artifacts\n```\n\nSubmit cycles separately using `python -m gridregime.oaf.schedule_once`.\nThe runner has not yet been validated under a process supervisor or with\ncrash/restart and network-partition tests. The live PJM adapter also needs\n`gridstatus` installed if PJM is enabled. Workers
must share durable Redis, persistent artifact storage and an immutable baseline
snapshot. Operators must monitor dead-letter queues, pending cycles, worker
restarts, storage failures and replay attempts.

### Replay semantics

The status aggregator and bridge reject conflicting immutable evidence for
one correlation ID; the bridge permits status snapshot transitions. A feature request uses a deterministic event ID derived from correlation,
source hash and baseline hash. This **does not** establish exactly-once
publication: the bridge can emit the same event ID more than once on replay,
and the downstream worker must handle duplicate delivery safely. The evidence
aggregator still needs revision-aware ordering; a stale assessment may replace
a newer assessment. Do not treat current readiness snapshots as an audited
publication-time evidence ledger.


## Dependency reproducibility

The targeted CI suite explicitly includes the planner, bridge, Redis-backed\nintegration and worker-runner tests, in addition to the full test suite.\n\nCI pins OpenAgentFabric to commit
`1cb2680cfc78df271726dc17be3434e120012f6c` rather than following
its mutable default branch. The runtime deployment must use that same commit
until an explicit upgrade and regression test. The worker requires source and
baseline SHA-256 pins on every feature request and checks the baseline path
against its configured baseline before computing features. This protects
against accidental artifact substitution; it is not formal scientific
approval of the baseline.
