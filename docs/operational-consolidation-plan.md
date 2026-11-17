# PJMStressRegimes consolidation: architecture and merge gates

## Publication claim
Demonstrate OpenAgentFabric portability between InvestmentIntelligence and PJM grid stress monitoring. No claim of novel grid-emergency prediction or reliable S2/S3 discrimination. Operator interventions are incompletely observed; weather, demand, and reserves already explain much of conventional stress.

## Current branch review (2026-11-17)
- `demo/architecture-case-study`: actual OAF BaseAgent/EventEnvelope handler demonstration and local evidence-grounded LLM investigation; README explicitly says **no Redis, durable retry, live scheduling, or production proof**. Favor its small application-facing API and evidence/report flow.
- `modeling/01-core-contracts-and-adapters`: useful validated FeatureDataset, ModelResult, model allowlist, episode-aware HMM training, replay. Its registry is **not persistent**, HMM is descriptive, PELT retrospective, and XGBoost has no validated emergency target. Preserve contracts, separate training from inference, and avoid unsupported predictive claims.
- `feature/evidence-claim-verification`: preserve typed evidence, provenance and fail-closed numerical checks, but do not make prose verification or benchmark machinery a prerequisite for the operational signal.
- `feature/episode-timeseries-audit`: retain descriptive coverage/trajectory diagnostics outside the hot operational path.
- `feature/oaf-migration-phase1`, `legacy/pre-oaf`, `master`: behind main; no independent commits to merge.

## Target application boundaries
1. **Acquire**: OAF event-driven acquisition with source identity, timestamps, coverage, deduplication and revision handling.
2. **Validate/feature**: deterministic frozen or versioned transformations; immutable feature artifacts with provenance.
3. **Train (scheduled)**: explicit historical window, model/feature version, reproducible training manifest, evaluation, candidate artifact; never silently replace the active model.
4. **Promote (controlled)**: require checks, immutable checksum and explicit approval/policy; atomically publish active model pointer with rollback.
5. **Infer (operational)**: consume current validated features and active model; emit stress state, score, thresholds, timestamps, evidence IDs, model version and data freshness. No emergency-probability claim.
6. **Interpret/report**: optional downstream LLM explanation based on bounded evidence; failure does not suppress deterministic stress signal.
7. **OAF operations**: idempotency, retries, checkpoints, observability, error handling and recovery tested using the real runtime, not only in-process handlers.

## Merge order and acceptance gates
1. **Baseline**: run existing main tests, document dependency/environment requirements and verify demo artifacts without network.
2. **Demo integration**: selectively merge application/OAF adapters from `demo/architecture-case-study`. Verify no research archive or unrelated experimental scripts enter the runtime path.
3. **Model contracts**: integrate only needed contracts, training and registry/adapters from `modeling/01-core-contracts-and-adapters`; remove duplicate entrypoints. Establish explicit `train`, `promote`, `infer` commands.
4. **Interpretation**: integrate bounded evidence verification as a replaceable downstream component; keep benchmark tests as development diagnostics.
5. **Episode audit**: integrate as optional diagnostics, not as an S2/S3 classifier.
6. **Operational tests**: simulate scheduled training, restart, stale data, missing inputs, duplicate events, invalid model artifacts, promotion rollback, and LLM unavailability. Test true OAF runtime behavior separately from handler-only tests.
7. **Publication**: build a reproducible demonstration and cross-domain architecture comparison; document what OAF provides vs what each domain supplies.

## Critical unresolved design decisions
- Actual OAF runtime deployment and scheduler contract must be inspected in the sibling OpenAgentFabric repository before wiring production execution.
- Model choice for operational stress signaling should be descriptive/anomaly based with clear calibration and false-alert burden; S2/S3 labels must not be used as a claimed predictive target.
- Data source freshness and availability for live/near-live inference must be demonstrated. Historical EIA-930 replay is not proof of live operations.
- A branch being ahead of main is not proof of safe merge; compare overlapping files and resolve integration conflicts before any main merge.

## Status
Integration branch created from main. This document is the initial review and implementation contract; no feature branch has been merged and no end-to-end operational capability has yet been validated.
