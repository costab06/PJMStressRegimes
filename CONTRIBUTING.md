# Contributing

Contributions should preserve the distinction between reproducible descriptive analysis and independently validated prediction. Do not describe stress scores as emergency probabilities.

## Development

Use Python 3.12 for the full OAF integration. Create a virtual environment, install `python -m pip install -e '.[dev]'`, and run `python -m pytest tests/ -q`. Install the sibling OpenAgentFabric package for OAF adapter tests. Redis and Ollama tests are explicitly opt-in.

Open a pull request against `main` with a short rationale, tests for changed behavior, and any changes to event/data contracts. Keep feature-version and provenance compatibility explicit. Do not alter frozen research baselines silently.

Do not commit credentials, personal data, copyrighted third-party datasets without redistribution rights, generated models, or local results. Provide small synthetic fixtures instead.

## Scientific integrity

Document dataset time ranges, missingness, revision handling, publication-time uncertainty, and evaluation boundaries. Do not claim predictive validity from in-sample descriptive scores or from a simulated promotion gate.
