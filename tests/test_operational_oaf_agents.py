import dataclasses
import hashlib
import json
from pathlib import Path
import pytest
from gridregime.operational import FeatureSnapshot
from gridregime.operational.lifecycle import train_reference_model, promote_candidate
from gridregime.operational.artifacts import read_snapshots


def _artifact(path, snapshots):
    data=json.dumps([dataclasses.asdict(s) for s in snapshots]).encode()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _snap(i=1):
    return FeatureSnapshot(observation_as_of=f'2026-07-{i:02d}T00:00:00Z',feature_version='frozen-v1',source_sha256='a'*64,values={'load_z':2.,'fe_z':1.,'ramp3_z':0.,'ic_z':0.})


def test_artifact_identity(tmp_path):
    p=tmp_path/'snapshots.json'
    digest=_artifact(p,[_snap()])
    assert len(read_snapshots(p,expected_sha256=digest))==1
    p.write_text('[]')
    with pytest.raises(ValueError,match='checksum'):
        read_snapshots(p,expected_sha256=digest)


@pytest.mark.asyncio
async def test_oaf_training_and_inference_handler_contract(tmp_path):
    pytest.importorskip('shared.agent.base')
    from shared.eventbus.events import EventEnvelope
    from gridregime.operational.oaf_agents import (GridTrainingAgent,GridInferenceAgent,
        TRAIN_REQUESTED,TRAIN_CANDIDATE,INFER_REQUESTED,STRESS_SIGNAL)
    from uuid import uuid4
    snapshots=[_snap(i) for i in range(1,25)]
    path=tmp_path/'training.json'
    digest=_artifact(path,snapshots)
    trainer=object.__new__(GridTrainingAgent)
    trainer.name='grid-model-trainer'
    trainer.artifact_dir=tmp_path/'models'
    request=EventEnvelope(event_type=TRAIN_REQUESTED,source_agent='test',correlation_id=uuid4(),payload={'snapshot_path':str(path),'snapshot_sha256':digest,'model_version':'v1'})
    candidate_event=(await trainer.handle_event(request))[0]
    assert candidate_event.event_type==TRAIN_CANDIDATE
    assert candidate_event.correlation_id==request.correlation_id
    assert candidate_event.causation_id==request.event_id
    assert candidate_event.payload['approved'] is False
    candidate=train_reference_model(snapshots,artifact_dir=trainer.artifact_dir,model_version='v1')
    approved=dataclasses.replace(candidate,evaluation={**candidate.evaluation,'independent_validation':'passed'})
    promote_candidate(approved,artifact_dir=trainer.artifact_dir,approval=True)
    inference_path=tmp_path/'inference.json'
    inference_digest=_artifact(inference_path,[_snap()])
    worker=object.__new__(GridInferenceAgent)
    worker.name='grid-model-inference'
    worker.artifact_dir=trainer.artifact_dir
    event=EventEnvelope(event_type=INFER_REQUESTED,source_agent='test',correlation_id=uuid4(),payload={'snapshot_path':str(inference_path),'snapshot_sha256':inference_digest})
    result=(await worker.handle_event(event))[0]
    assert result.event_type==STRESS_SIGNAL
    assert result.correlation_id==event.correlation_id
    assert result.payload['predictive_validation_status']=='not_established'
