# Grid Regime Study

Research project for detecting and characterizing electricity grid stress regimes using EIA-930, NOAA weather, and PJM operational data.

## Structure

- `config/` — Research specs, data source configs, model hyperparameters
- `data/` — Raw, interim, and processed data (not versioned)
- `metadata/` — Event catalog, controls, data dictionary
- `src/gridregime/` — Core Python package
- `notebooks/` — Exploratory and analysis notebooks
- `experiments/` — Model run outputs and configs
- `results/` — Figures, tables, and metrics for reporting
- `paper/` — Manuscript and supporting materials
- `tests/` — Unit tests

## Setup

```bash
pip install -e ".[dev]"
```

## Data Sources

- **EIA-930**: Hourly grid balance authority demand, generation, interchange
- **NOAA**: Station weather observations and forecasts
- **PJM**: Regional transmission operator operational data
- **Historical**: 2003 Northeast Blackout, 2014 Polar Vortex event archives
