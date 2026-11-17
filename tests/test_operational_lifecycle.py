import dataclasses
import json
import pytest
from gridregime.operational import FeatureSnapshot
from gridregime.operational.lifecycle import train_reference_model, promote_candidate, infer_active


def samples():
    return [FeatureSnapshot(observation_as_of=f'2026-07-{i+1:02d}T00:00:00Z',feature_version='frozen-v1',source_sha256='a'*64,values={'load_z':float(i%5),'fe_z':1.,'ramp3_z':0.,'ic_z':0.}) for i in range(24)]


def test_train_candidate_not_auto_promoted(tmp_path):
    candidate=train_reference_model(samples(),artifact_dir=tmp_path,model_version='test')
    assert not candidate.approved
    assert not (tmp_path/'active.json').exists()
    with pytest.raises(PermissionError):
        promote_candidate(candidate,artifact_dir=tmp_path)
    with pytest.raises(ValueError,match='independent validation'):
        promote_candidate(candidate,artifact_dir=tmp_path,approval=True)


def test_explicit_validated_promotion_and_inference(tmp_path):
    candidate=train_reference_model(samples(),artifact_dir=tmp_path,model_version='test')
    validated=dataclasses.replace(candidate,evaluation={**candidate.evaluation,'independent_validation':'passed'})
    promote_candidate(validated,artifact_dir=tmp_path,approval=True)
    signal=infer_active(samples()[0],artifact_dir=tmp_path,decision_as_of='2026-08-01T00:00:00Z')
    assert signal.model_version=='test'
    assert signal.predictive_validation_status=='not_established'


def test_tampering_fails_closed(tmp_path):
    candidate=train_reference_model(samples(),artifact_dir=tmp_path,model_version='test')
    validated=dataclasses.replace(candidate,evaluation={**candidate.evaluation,'independent_validation':'passed'})
    promote_candidate(validated,artifact_dir=tmp_path,approval=True)
    (tmp_path/f'model-{candidate.artifact_sha256}.json').write_text('{}')
    with pytest.raises(ValueError,match='checksum'):
        infer_active(samples()[0],artifact_dir=tmp_path)
