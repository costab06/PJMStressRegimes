# GridRegime — A Cross-Domain Architecture Example

A small, reproducible example of how the same application architecture can be applied to **financial intelligence** and **electric-grid measurements**.

This is **not** a grid-emergency predictor. The earlier detector research did not demonstrate an advantage over a simpler weather-and-demand model. The research is preserved on the `modeling/01-core-contracts-and-adapters` branch.

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

All experimental modeling, threshold sweeps, notebooks, historical catalogs, and manuscript material remain in the full research history on `modeling/01-core-contracts-and-adapters`. This branch deliberately contains only the reader-facing example and its essential adapters.

### Deterministic semantic verification

The follow-up local model now supplies structured comparison directions. The
application independently calculates the expected directions and rejects
contradictory or missing claims. Verified numerical comparisons are generated
by deterministic Python code; free-form model prose is explicitly **not**
semantically verified. If the model fails the comparison check, its reassessment
is withheld from the Markdown report while raw output and verification status
remain available in `grid_followup_raw.txt` and `grid_investigation.json`.
