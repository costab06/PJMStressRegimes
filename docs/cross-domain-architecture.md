# Cross-domain implementation architecture

This application follows the same three-layer separation as InvestmentIntelligence + SECAgents + OpenAgentFabric.

| Responsibility | Financial application | Grid application |
|---|---|---|
| Distributed orchestration | OpenAgentFabric | OpenAgentFabric (same dependency) |
| Acquisition/normalization | SECAgents watcher/fetcher/parser | Grid acquisition/validation/feature agents |
| Domain application | InvestmentIntelligence | GridRegime training/inference/interpretation |
| Evidence | SEC filing and facts provenance | Timestamped EIA/PJM/weather observations and feature provenance |
| Deterministic analysis | Financial metrics | Grid stress features and descriptive model outputs |
| LLM | Evidence-constrained research interpretation | Evidence-constrained stress interpretation |

## Operational topology

```text
Scheduler / event source
    |-- acquisition.requested -> OAF acquisition agents -> source artifacts
    |-- training.requested  -> validated historical features -> train/evaluate
    |                                                   -> candidate artifact
    |                                                   -> promotion gate
    |
    +-- observation.available -> feature validation -> active model inference
                                            |                |
                                            |           stress.signal
                                            |                |
                                            |       +--------+----------+
                                            |       |                   |
                                            |   deterministic       optional LLM
                                            |   alert/report         explanation
                                            |       |                   |
                                            +-------+-------------------+
                                                    |
                                             evidence/audit record
```

## Rules

- OAF events transport **artifact identities and references**, not mutable in-memory model objects.
- The feature and signal contracts are domain-owned, independent of Redis or LLM libraries, and can be tested without infrastructure.
- The data/feature layer must carry source hash, feature version, UTC observation time, coverage and publication verification.
- Training and inference never share a mutable model instance. Training creates an immutable candidate; only a separate promotion gate can activate it.
- A failed or unavailable LLM cannot suppress a deterministic stress signal.
- The initial joint-L2 baseline in `gridregime.operational` is illustrative and unvalidated. It cannot establish emergency probabilities or S2/S3 outcome prediction.
- Live operation requires tested publication-lag policy, source freshness, signal calibration, and real OAF worker/retry/recovery integration.

## Implemented on integration branch

- `gridregime.operational.contracts`: strict feature, training-candidate and signal contracts.
- `gridregime.operational.service`: deterministic reference scoring and candidate checksum.
- `tests/test_operational_contracts.py`: unit tests for numerical evidence, timestamp/feature validation and unapproved candidates.

## Not yet implemented

- Selective migration of demo OAF adapters, model training modules and interpretation pipeline.
- Durable model artifact storage, version registry, approval/promotion/rollback.
- Actual periodic training scheduler, continuous inference workers and Redis integration.
- End-to-end tests, performance/false-alert calibration, publication-ready demonstration.

Do not describe these missing components as operational until they are implemented and tested.
