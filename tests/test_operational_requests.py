import json
import pytest
from gridregime.operational.requests import request_for_artifact


def test_scheduler_request_includes_checksum(tmp_path):
    path=tmp_path/'features.json'
    path.write_text('[]')
    request=request_for_artifact(kind='train',path=path,model_version='v1')
    assert request['event_type']=='grid.model.training.requested'
    assert len(request['payload']['snapshot_sha256'])==64
    assert request['payload']['model_version']=='v1'
    infer=request_for_artifact(kind='infer',path=path)
    assert infer['event_type']=='grid.model.inference.requested'
    assert 'model_version' not in infer['payload']


def test_training_version_required(tmp_path):
    path=tmp_path/'features.json'
    path.write_text('[]')
    with pytest.raises(ValueError):
        request_for_artifact(kind='train',path=path)
