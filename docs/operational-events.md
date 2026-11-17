# OAF operational events and scheduling boundary

The grid application follows SECAgents' independently handled event stages. OpenAgentFabric is the transport/reliability layer; domain code does not implement another message bus.

| Event | Consumer | Output |
|---|---|---|
| `grid.model.training.requested` | `GridTrainingAgent` | `grid.model.training.candidate` |
| `grid.model.inference.requested` | `GridInferenceAgent` | `grid.stress.signal` |

Both request payloads contain `snapshot_path` and `snapshot_sha256`. Training additionally requires `model_version` and optionally `quantile`. Snapshots are JSON arrays of `FeatureSnapshot` records. The handler verifies the artifact hash before reading the data. Inference requires exactly one snapshot. All paths must be accessible to the worker, and shared artifact storage is needed when workers run on different machines.

## Request generation for external scheduling

```bash
python -m gridregime.operational.requests train --snapshots /absolute/path/training-snapshots.json --model-version 2026-11
python -m gridregime.operational.requests infer --snapshots /absolute/path/latest-snapshot.json
```

These commands emit a JSON **request description to stdout**; they do **not** publish events. Wire the output into the configured OpenAgentFabric producer and run its registered workers. A cron, systemd timer, or orchestration service can invoke the producer periodically; do not claim a schedule is active just because a request can be generated.

## Promotion and runtime requirements

The training event produces an **unapproved candidate**. A separate evaluation and authorized promotion workflow must set the active model. The current reference implementation checks a supplied `independent_validation=passed` value, but does not independently authenticate that assessment; this is not yet a production-grade authorization boundary.

A production integration must still demonstrate OAF event publication and consumption, replay/deduplication, durable retries, data freshness, evaluation provenance, atomic promotion/rollback, alert calibration and recovery. The interpretation agent is downstream and optional; an LLM failure must not prevent a deterministic stress signal.
