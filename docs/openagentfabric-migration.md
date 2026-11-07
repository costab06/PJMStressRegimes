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
