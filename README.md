# GridRegime: A Small Cross-Domain Architecture Example

This repository began as a research project investigating operational stress in the PJM electricity grid. The reader-facing demonstration is now deliberately much smaller.

**Purpose:** Show how a familiar analytical workflow—acquire, validate, transform, analyze, and preserve evidence—can be applied to power-grid measurements as well as to financial intelligence.

**Not the purpose:** Predict grid emergencies or claim that an anomaly detector outperforms simpler weather-and-demand analysis. Earlier experiments did not establish that result.

## Run the example

Install the package and its dependencies, and provide the existing local EIA-930 file at `data/raw/eia930/PJM_2026-07.parquet`.

```bash
pip install -e .
python -m gridregime.demo
```

The script writes `results/demo/case_study.json`, containing its input path, data contract, method, and descriptive measurements. It does not train a model or require weather downloads.

## Read the code in five minutes

The entire reader-facing workflow is in [`src/gridregime/demo.py`](src/gridregime/demo.py):

1. `load` — read the existing hourly EIA-930 dataset
2. `validate` — check schema, timestamps, and plausible demand
3. `analyze` — calculate peak demand, hourly changes, and forecast error
4. `main` — save a reproducible result with source and method information

## Relationship to InvestmentIntelligence and OpenAgentFabric

Both financial and grid analysis need input contracts, deterministic transformations, execution coordination, and evidence records. Their domain-specific sources and analytical methods differ.

**Important distinction:** This demonstration illustrates architectural portability. It does **not** currently prove that this repository imports or executes OpenAgentFabric. That integration should only be claimed after it is verified in code.

## Research history

The prior modeling work is preserved on the `modeling/01-core-contracts-and-adapters` branch. It includes anomaly models, weather/demand comparisons, calibration experiments, and their limitations. Those are not necessary to understand this example.

This demonstration is maintained separately on `demo/architecture-case-study` so the research history remains intact while the audience-facing presentation can be simplified.
