# OpenAgentFabric migration — phase 1

Status: isolated implementation branch; no scientific methodology changes.

## Research invariants

- `research_spec.yaml` remains the append-only methodological authority.
- Preserve frozen feature definitions, episode classifications, baseline, and evaluation gates.
- Scientific functions remain independently executable without Redis or OpenAgentFabric.
- Agent wrappers orchestrate existing implementations rather than reimplement calculations.
- Record episode ID, research specification hash, input hashes, and code revision for every run.
- Never silently substitute missing source data, relabel an episode, or treat retries as new independent observations.

## Proposed boundaries

1. EIA-930 acquisition — source retrieval, validation, raw artifact and provenance.
2. NOAA acquisition — weather observations with station and timestamp provenance.
3. PJM operational evidence — actions, notices, and episode references.
4. Feature computation — invoke existing frozen feature calculations.
5. Regime analysis and evaluation — invoke research routines with episode-level validation.
6. Coordinator — correlate episode workflows and assemble versioned artifacts.

These boundaries are provisional until actual source modules and framework interfaces are inventoried.

## Phase 1 scope

Add a dependency-free provenance helper and unit tests. This is preparation for agent adapters, not yet OpenAgentFabric runtime integration.

## Next gate

Inspect the exact OpenAgentFabric agent interfaces, message schema, and lifecycle before writing an adapter. Identify the existing EIA-930 entrypoint; compare its original outputs with the wrapped path using identical inputs.

## Acceptance criteria

- Existing research tests pass with Python 3.12.
- Same inputs, specification, episode, and code revision produce the same fingerprint.
- Changed input or specification changes the fingerprint.
- Duplicate delivery does not publish duplicate artifacts.
- Crash recovery is observable and reproducible.
- The migration does not alter the research model or scientific results.


## Phase 2: EIA-930 adapter (implementation branch)

The source tree was inspected on 2026-11-07:

- OAF: `framework/shared/agent/base.py`, `framework/shared/eventbus/events.py`,
  `framework/shared/correlation/registry.py`, `framework/shared/eventbus/base.py`.
- PJM: `src/gridregime/ingest/eia930.py`, `src/gridregime/ingest/eia930_bulk.py`,
  `tests/test_ingest.py`.

The adapter at `src/gridregime/oaf/eia930_agent.py` subclasses
`shared.agent.base.BaseAgent` and consumes `grid.eia930.requested` events.
It delegates acquisition to the existing `fetch_window`, validates the required
demand/forecast/interchange series, and writes a content-addressed CSV artifact.
It emits `grid.eia930.fetched` with the original correlation ID and request
event as causation ID. BaseAgent is responsible for transport-level retries,
lease/heartbeat, terminal commit, and dead-letter handling.

**Important:** The existing EIA fetcher may continue after some API errors.
The adapter rejects missing/null required columns, but does not yet verify
complete expected hourly coverage or source-specific quality flags. This must
be added before claiming production-quality ingestion.

**Runtime:** PJM's pyproject supports Python 3.10+, while OAF requires Python
3.12+. Run this integration on Python 3.12+ with both packages importable.
The adapter is not imported by the scientific core.

**Validation pending:** Tests are committed but have not been run against a
real OAF installation or Redis. To run from a checkout with OAF alongside PJM:

```bash
python -m pip install -e '.[dev]'
python -m pip install -e ../OpenAgentFabric
PYTHONPATH=../OpenAgentFabric/framework pytest -q tests/test_provenance.py tests/test_oaf_eia930.py
```

Do not merge this draft PR until these tests and existing PJM tests pass.
