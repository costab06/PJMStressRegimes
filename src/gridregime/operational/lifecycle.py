"""Artifact-based training, controlled promotion, and deterministic inference.

This is a local reference lifecycle suitable for OAF worker handlers. Scheduling,
Redis event delivery, calibration, and production deployment are separate concerns.
"""
from __future__ import annotations
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from math import sqrt
from .contracts import FEATURES, FeatureSnapshot, TrainingCandidate
from .service import evaluate_stress


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.candidate-', delete=False) as handle:
        tmp = Path(handle.name)
        try:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def train_reference_model(snapshots: list[FeatureSnapshot], *, artifact_dir: str | Path,
                          model_version: str, quantile: float = 0.95,
                          trained_as_of: str | None = None) -> TrainingCandidate:
    """Fit descriptive empirical L2 threshold; never uses S2/S3 labels.

    Candidate remains unapproved. Caller must supply independent evaluation and
    approval policy before promotion; quantile is not a calibrated false-alert rate.
    """
    if not 0 < quantile < 1 or len(snapshots) < 24:
        raise ValueError('require 24+ observations and a quantile strictly between 0 and 1')
    versions = {s.feature_version for s in snapshots}
    if len(versions) != 1:
        raise ValueError('mixed feature versions')
    times = [s.observation_as_of for s in snapshots]
    if len(times) != len(set(times)):
        raise ValueError('duplicate observation timestamps')
    scores = sorted(sqrt(sum(s.values[k]**2 for k in FEATURES)) for s in snapshots)
    idx = min(len(scores)-1, max(0, int(quantile * len(scores))))
    threshold = scores[idx]
    model = {'schema_version':1,'model_id':'joint-l2-reference','model_version':model_version,
             'feature_version':next(iter(versions)),'threshold':threshold,
             'training_observations':len(scores),'quantile':quantile,
             'predictive_validation_status':'not_established'}
    data = (json.dumps(model, sort_keys=True, separators=(',', ':'))+'\n').encode()
    digest = hashlib.sha256(data).hexdigest()
    root = Path(artifact_dir)
    target = root / f'model-{digest}.json'
    if target.exists() and target.read_bytes() != data:
        raise ValueError('artifact checksum collision or corruption')
    if not target.exists():
        _write_atomic(target, data)
    candidate = TrainingCandidate(model_id=model['model_id'], model_version=model_version,
        feature_version=model['feature_version'], artifact_sha256=digest,
        trained_as_of=trained_as_of or datetime.now(timezone.utc).isoformat(),
        evaluation={'training_observations':len(scores),'quantile':quantile,
                    'independent_validation':'not_performed','operational_calibration':'not_established'})
    _write_atomic(root / f'candidate-{digest}.json', (json.dumps(candidate.__dict__,sort_keys=True)+'\n').encode())
    return candidate


def promote_candidate(candidate: TrainingCandidate, *, artifact_dir: str | Path,
                      approval: bool = False) -> dict:
    """Explicit manual approval; never infer approval from fitting success."""
    if not approval:
        raise PermissionError('explicit approval required')
    if candidate.evaluation.get('independent_validation') != 'passed':
        raise ValueError('independent validation must pass before promotion')
    root = Path(artifact_dir)
    data = (root / f'model-{candidate.artifact_sha256}.json').read_bytes()
    if hashlib.sha256(data).hexdigest() != candidate.artifact_sha256:
        raise ValueError('model artifact checksum mismatch')
    model = json.loads(data)
    if (model['model_id'],model['model_version'],model['feature_version']) != (candidate.model_id,candidate.model_version,candidate.feature_version):
        raise ValueError('candidate/model identity mismatch')
    active = {'sha256':candidate.artifact_sha256,'model_id':candidate.model_id,
              'model_version':candidate.model_version,'feature_version':candidate.feature_version}
    _write_atomic(root/'active.json',(json.dumps(active,sort_keys=True)+'\n').encode())
    return active


def infer_active(snapshot: FeatureSnapshot, *, artifact_dir: str | Path,
                 decision_as_of: str | None = None):
    root = Path(artifact_dir)
    active = json.loads((root/'active.json').read_text())
    digest = active['sha256']
    if len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('invalid active artifact identity')
    data = (root/f'model-{digest}.json').read_bytes()
    if hashlib.sha256(data).hexdigest()!=digest:
        raise ValueError('active model checksum mismatch')
    model = json.loads(data)
    if snapshot.feature_version != model['feature_version'] or any(active[k]!=model[k] for k in ('model_id','model_version','feature_version')):
        raise ValueError('model and features are incompatible')
    return evaluate_stress(snapshot,model_id=model['model_id'],model_version=model['model_version'],
                           threshold=model['threshold'],decision_as_of=decision_as_of)
