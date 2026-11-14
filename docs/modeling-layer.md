# Modeling layer — milestone 01

The data layer owns acquisition, normalization, source provenance, and the frozen-v1 feature schema. The modeling layer accepts an explicit validated `FeatureDataset` and returns a `ModelResult`. Future intelligence code must interpret results without importing algorithm internals.

## Implemented

- `gridregime.modeling.contracts.FeatureDataset`: contiguous, strictly ordered UTC hourly rows with finite `load_z, fe_z, ramp3_z, ic_z`, a BA and source/baseline SHA-256 identities.
- `ModelResult`: algorithm identity, observation/decision times, typed result name and unvalidated scientific status.
- `registry.create_adapter`: allowlisted wrappers around existing Isolation Forest, Gaussian HMM, retrospective PELT changepoints, and supervised XGBoost.
- HMM inference uses a forward-only recursion, rather than Viterbi decoding over future observations. Hidden state numbers are not S1/S2/S3 labels.
- Tests use synthetic fixtures; no real historical emergency prediction is asserted.

## Explicit limitations

- A `FeatureDataset` holds one continuous sequence. Multi-episode training must pass episode lengths to HMM fitting and enforce independent episode partitions; this first milestone does not implement it.
- XGBoost requires external labeled data and a distinct validation episode; the adapter alone does not establish valid LOEO cross-validation or a sufficient catalog.
- PELT results are retrospective segmentation, not a streaming alarm.
- The anomaly adapter preserves the original scaler+IsolationForest implementation; it is not a calibrated emergency probability.
- The registry is a code-level allowlist, not a persistent artifact registry. Model serialization, experiment manifests, immutable model checksums, artifact-based dataset loading, and deployment are subsequent milestones.
- The research specification defers scientific HMM evaluation until enough independent episodes are cataloged. Do not bypass this gate because synthetic tests pass.

## Next milestone

Connect pinned historical feature artifacts to the contracts, add episode-aware training/evaluation and reproducible experiment manifests, and verify no temporal leakage across splits.
