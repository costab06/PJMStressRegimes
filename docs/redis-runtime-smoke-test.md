# Redis runtime smoke test (main)

This runbook follows SECAgents' standalone OAF worker pattern. It is a **manual operational smoke test**. The opt-in Redis integration test exercises the training/promotion/inference path, but does not establish production readiness.

## Prerequisites

- Python 3.12 and compatible OpenAgentFabric 0.2.1 installed in the same environment as GridRegime.
- Redis reachable at `REDIS_URL` (SECAgents development default `redis://localhost:6380/0`).
- A JSON array of at least 24 valid, distinct `FeatureSnapshot` records for training, plus a separate one-record JSON array for inference. These are frozen-v1 **features**, not raw EIA-930 observations.
- Use a dedicated test stream (e.g. `gridregime.smoke`) and isolated model artifact directory. All worker processes must share that directory.
- Put input snapshots in a dedicated directory and set `GRID_SNAPSHOT_INPUT_DIR` to its absolute path in **both** workers. The worker rejects paths outside it.

## Start workers in two terminals

```bash
export REDIS_URL=redis://localhost:6380/0
export OAF_STREAM=gridregime.smoke
export GRID_MODEL_ARTIFACT_DIR=data/operational-smoke/models
export GRID_SNAPSHOT_INPUT_DIR=/absolute/path/to/snapshot-directory
python -m gridregime.operational.run_worker training
```

In another terminal with the same variables:

```bash
python -m gridregime.operational.run_worker inference
```

## Publish training request

```bash
python -m gridregime.operational.publish_request train \\
  --snapshots /absolute/path/training-snapshots.json \\
  --model-version smoke-v1
```

The worker should publish `grid.model.training.candidate` and persist a content-addressed model. Confirm the candidate artifact and inspect the Redis stream. **The model is not automatically activated.**

## Promotion gate

The reference `promote_candidate` function requires explicit approval and an `independent_validation=passed` evaluation field. The current system does not independently verify the authority or provenance of that field; do not treat it as production authorization. For smoke testing only, an operator can explicitly supply a separately reviewed candidate with that field, then invoke `promote_candidate`. Do not use an unreviewed result to justify real alerts.

## Publish inference request

```bash
python -m gridregime.operational.publish_request infer \\
  --snapshots /absolute/path/latest-snapshot.json
```

The inference worker should emit `grid.stress.signal` with the model version, observation timestamp, source hash, feature values, and `predictive_validation_status=not_established`.

## Evidence to capture

- Producer event ID and correlation ID; candidate and signal event lineage
- Redis stream entries and consumer-group pending/lag counts
- Candidate SHA-256, active pointer and model artifact SHA-256
- Restart test: stop/restart a worker during a queued request; verify recovery and no duplicate completion
- Failure test: corrupt a snapshot checksum; verify retries/DLQ behavior
- Missing active model: inference should fail closed rather than silently train/promote

## Remaining gaps

- A timer/cron integration is not configured by this code; scheduling is external.
- No automatic candidate validation, signed approval, rollback, freshness enforcement or alert calibration.
- Acquisition adapters and operational handlers are both present on `main`, but their combined end-to-end production pipeline is not validated.
- Run the opt-in Redis test in your own environment: `GRID_OAF_REDIS_TEST=1 python -m pytest tests/test_operational_redis_integration.py -v`. The manual steps above exercise a separate deployment path.
