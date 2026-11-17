# GridRegime — A Cross-Domain Architecture Example

A small, reproducible example of how the same application architecture can be applied to **financial intelligence** and **electric-grid measurements**.

This is **not** a grid-emergency predictor. The earlier detector research did not demonstrate an advantage over a simpler weather-and-demand model. The research and modeling code are preserved in the repository history and consolidated on `main`.

## Project status and scope

This repository contains a reproducible historical PJM case study, deterministic evidence/claim verification, OAF acquisition adapters, and optional Redis-backed operational training/inference. The operational stress score is descriptive and **not** an independently validated emergency forecast. Publication-time availability is not established for all historical observations. The model-promotion test simulates external validation; it is not an approval system.

Python 3.12 is recommended when using the OAF integration. The standalone data demonstration supports the Python version declared in `pyproject.toml`. OAF is an optional sibling project and must be installed separately for OAF workflows.

## Reproducible synthetic demonstration

Run `python tools/prepare_release_demo.py` before `python -m gridregime.demo`
to create a local **synthetic** EIA-930-shaped input. This is not historical
PJM evidence. See [offline demo instructions](docs/release-demo.md).

## Start here: four steps

| Step | What it does | Where |
| --- | --- | --- |
| 1. Acquire | Read historical PJM hourly EIA-930 data | `demo.load` |
| 2. Validate | Check timestamps and measurement contract | `demo.validate` |
| 3. Analyze | Compute transparent demand and forecast-error statistics | `demo.analyze` |
| 4. Preserve | Write an auditable JSON result | `demo.main` |

Run with an existing July 2026 EIA-930 parquet at `data/raw/eia930/PJM_2026-07.parquet`:

```bash
pip install -e .
python -m gridregime.demo
```

Output: `results/demo/case_study.json`. This local example needs no network, Redis, or machine-learning dependencies.

## Local-model intelligence layer

The intelligence example adds deterministic comparisons and a **local Ollama interpretation**, followed by a model-selected, bounded hypothesis investigation and reassessment.
It evaluates forecast accuracy under high versus ordinary demand, signed forecast bias,
the largest contiguous hourly ramp, and the descriptive association between ramps and
interchange. The model receives only these computed observations and must cite their
evidence IDs, identify alternative explanations, and name missing evidence.

```bash
# Start Ollama separately and ensure the chosen model is available.
ollama pull qwen3:8b
pip install -e ../OpenAgentFabric
python -m gridregime.grid_intelligence
python -m gridregime.grid_interpretation_agent --model qwen3:8b
```

Outputs: `results/demo/grid_evidence.json`, `grid_interpretation.json`,
`grid_investigation.json`, and the readable `grid_interpretation.md`.
The model chooses between predefined forecast-accuracy and ramp/interchange
investigations. Python calculates the follow-up comparisons; the model then
reassesses its hypothesis using those measurements. It cannot run arbitrary tools.
The investigation checks MWh versus percentage errors and within-UTC-hour
comparisons, or demand-ramp versus interchange-change correlation. Use `--base-url` to change the
OpenAI-compatible local endpoint.

The interpretation validator rejects missing/unknown evidence IDs, numeric claims
invented by the model, and some overconfident causal language. **This is a limited
structural guardrail, not semantic verification**: a human should still review the
model's qualitative interpretations. Failed validation stops report generation;
there is no silent fallback to an unsupported answer.

## The real OpenAgentFabric integration

The second walkthrough shows the **actual OAF BaseAgent adapters and EventEnvelope contracts**, not a hypothetical architecture:

```bash
# Install the sibling OpenAgentFabric project first (or place its framework on PYTHONPATH).
pip install -e ../OpenAgentFabric
python -m gridregime.oaf_demo
```

The walkthrough calls existing OAF agent handlers in-process:

```text
grid.acquisition.cycle.requested
          |
          v
AcquisitionCoordinatorAgent (OAF BaseAgent)
          |
          v
grid.eia930.requested
          |
          v
EIA930AcquisitionAgent (OAF BaseAgent)
          |
          v
grid.eia930.fetched --> content-addressed CSV + provenance + revision record
```

Output: `results/demo/oaf_event_trace.json`, plus a hash-named data artifact. Correlation and causation identifiers are carried across events. The EIA acquisition adapter also checks coverage and preserves source evidence.

**Scope boundary:** This is a handler-level demonstration. It does not start Redis, exercise durable retries, prove publication-time availability, or demonstrate live production scheduling. Those capabilities belong to the wider OpenAgentFabric runtime, not this short walkthrough.

## Why this belongs beside InvestmentIntelligence

InvestmentIntelligence uses domain-specific financial retrieval and interpretation; GridRegime uses hourly grid observations. Both can be organized around event-driven acquisition, explicit data contracts, traceable transformations, and durable evidence. The OAF adapters in this repository are actual implementations of that pattern.

The article's claim is **architectural portability**, not predictive performance.

## Where the experiments went

The historical modeling experiments, data catalogs, and architecture demonstration have been consolidated into `main`. They remain research artifacts, not evidence of predictive accuracy.

### Deterministic semantic verification

The follow-up local model now supplies structured comparison directions. The
application independently calculates the expected directions and rejects
contradictory or missing claims. Verified numerical comparisons are generated
by deterministic Python code; free-form model prose is explicitly **not**
semantically verified. If the model fails the comparison check, its reassessment
is withheld from the Markdown report while raw output and verification status
remain available in `grid_followup_raw.txt` and `grid_investigation.json`.

## Test the consolidated repository

```bash
python -m pip install -e '.[dev]'
python -m pytest tests/ -q
```

For the optional OAF tests, install the sibling `OpenAgentFabric` project into the same environment. To run the real Redis integration test, start a local Redis instance and then:

```bash
REDIS_URL=redis://localhost:6380/0 GRID_OAF_REDIS_TEST=1 \
  python -m pytest tests/test_operational_redis_integration.py -v
```

The live Ollama smoke test is opt-in (`RUN_LIVE_LLM=1`) and requires a local model. Tests marked as skipped do not establish coverage of the corresponding external service.

## Contributing and responsible use

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). Avoid committing raw source datasets, API credentials, model artifacts, local results, or personal information. This code is a research demonstration; it is not intended for grid dispatch or other safety-critical decisions.

**License:** [Apache License, Version 2.0](LICENSE). See the license terms for reuse and redistribution. Third-party datasets and dependencies remain subject to their own licenses.

## Operational worker input safety

For Redis-backed workers, set `GRID_SNAPSHOT_INPUT_DIR` to a dedicated directory containing approved snapshot artifacts, or pass `--input-dir` to `gridregime.operational.run_worker`. The worker rejects snapshot paths outside that directory, including symlink escapes. Without this setting, path access remains unrestricted for compatibility with existing research runs. Do not expose Redis to untrusted publishers.
