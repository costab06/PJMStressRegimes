# Public release checklist

This is a working release gate, not a claim that all checks are complete.

## Verified by maintainer on 2026-11-17

- [x] Consolidated development branches into `main` before cleanup
- [x] Existing test suite passed locally: 123 passed (maintainer report)
- [x] Opt-in Redis integration test passed before latest documentation/CI updates (maintainer report)
- [x] Apache License 2.0 added

## Before merging the open-source preparation PR

- [x] Review the tracked **filename inventory** supplied by the maintainer (`git ls-files`, 2026-11-17): source, tests, docs, configuration and license only; no filenames indicating tracked raw datasets, notebooks, model binaries or generated results. **Content inspection and history scanning remain pending.**
- [ ] Inspect tracked file contents for secrets, private identifiers, copied third-party code, and nonredistributable material.
- [ ] Inspect Git history for secrets and restricted data; deleting files in a new commit does **not** erase old history.
- [ ] Verify third-party dataset and copied-code redistribution permissions and document required notices.
- [ ] Verify clean checkout installation in a fresh virtual environment, including the pinned OAF checkout in GitHub Actions.
- [ ] Run full pytest suite and opt-in Redis integration against the final PR head; check CI success.
- [ ] Review model-promotion policy. Current `approval=True` plus caller-supplied `independent_validation=passed` is a research-only gate, not authenticated governance.
- [ ] Enable `GRID_SNAPSHOT_INPUT_DIR` for any deployed worker and restrict Redis access. This setting is opt-in for compatibility.
- [ ] Review dependency versions, vulnerability advisories, and reproducibility of external services.
- [ ] Review public-facing documentation for stale branch references and unsupported predictive claims.

## Release

After the checks above, merge PR #43, verify `main` again, and tag `v0.1.0`. A public GitHub repository and an Apache license do not establish production suitability or redistribution rights for independently licensed datasets.
