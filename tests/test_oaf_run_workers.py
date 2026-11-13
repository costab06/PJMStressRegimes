"""Worker runner construction smoke test for pinned OAF API."""
from pathlib import Path

import pytest

from gridregime.oaf.run_workers import build_agents


class Bus:
    redis = object()


def test_build_all_pipeline_workers(tmp_path):
    baseline = tmp_path / "frozen.parquet"
    baseline.write_bytes(b"pinned-baseline")
    agents = build_agents(
        bus=Bus(), registry=object(), baseline_path=baseline,
        artifact_dir=tmp_path / "artifacts",
    )
    assert len(agents) == 7
    assert len({str(agent.name) for agent in agents}) == 7
    assert all(callable(agent.run) for agent in agents)
    assert agents[-1].baseline_path == baseline
    assert agents[-2].baseline_path == baseline


def test_runner_rejects_missing_baseline(tmp_path):
    with pytest.raises(FileNotFoundError, match="Frozen baseline"):
        build_agents(
            bus=Bus(), registry=object(),
            baseline_path=tmp_path / "missing.parquet",
            artifact_dir=tmp_path / "artifacts",
        )


@pytest.mark.asyncio
async def test_runner_rejects_python_without_taskgroup(monkeypatch, tmp_path):
    import sys
    from gridregime.oaf.run_workers import run

    monkeypatch.setattr(sys, "version_info", (3, 10, 0))
    with pytest.raises(RuntimeError, match="Python 3.11"):
        await run(
            redis_url="redis://localhost:6379/0",
            baseline_path=tmp_path / "baseline.parquet",
            artifact_dir=tmp_path / "artifacts",
        )
