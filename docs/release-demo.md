# Offline reproducibility

This demonstration uses **synthetic measurements**, not historical PJM data.
It tests data contracts and deterministic descriptive analysis, not emergency prediction.

```bash
python -m pip install -e '.[dev]'
python tools/prepare_release_demo.py
python -m gridregime.demo
python -m pytest tests/ -q
```

The generated input is `data/raw/eia930/PJM_2026-07.parquet`; output is
`results/demo/case_study.json`. Neither should be committed.

Optional OAF handler demonstration (requires a compatible OpenAgentFabric installation):

```bash
python -m pip install -e ../OpenAgentFabric
python -m gridregime.oaf_demo
```

This is a handler-level walkthrough, not a Redis reliability test.
