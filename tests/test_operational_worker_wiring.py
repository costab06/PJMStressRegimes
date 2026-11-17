"""Verify worker/producer wiring without needing an external Redis server."""
import pytest


def test_worker_invalid_kind_fails_before_connecting():
    pytest.importorskip('shared.eventbus.redis')
    from gridregime.operational.run_worker import run_worker
    import asyncio
    with pytest.raises(ValueError,match='kind'):
        asyncio.run(run_worker('other',redis_url='redis://localhost:1',stream='oaf.events',artifact_dir='data/models'))


def test_producer_event_contract(tmp_path):
    from gridregime.operational.requests import request_for_artifact
    path=tmp_path/'observations.json'
    path.write_text('[]')
    assert request_for_artifact(kind='infer',path=path)['event_type']=='grid.model.inference.requested'
