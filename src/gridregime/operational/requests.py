"""Scheduler-facing request builder; delivery is handled by the OAF event bus.

A cron/systemd scheduler may invoke this to generate a request; generating a
request is not equivalent to publishing it or running a worker.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from .contracts import utc


def request_for_artifact(*, kind: str, path: str | Path, model_version: str | None = None,
                         quantile: float = 0.95) -> dict:
    if kind not in {'train','infer'}:
        raise ValueError('kind must be train or infer')
    artifact = Path(path).resolve(strict=True)
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    payload = {'snapshot_path':str(artifact),'snapshot_sha256':digest}
    if kind == 'train':
        if not model_version:
            raise ValueError('training requires model version')
        payload.update(model_version=model_version,quantile=quantile)
    return {'event_type':'grid.model.training.requested' if kind=='train' else 'grid.model.inference.requested',
            'payload':payload}


def main(argv=None):
    parser=argparse.ArgumentParser(description='Generate an OAF training/inference event request (does not publish)')
    parser.add_argument('kind',choices=['train','infer'])
    parser.add_argument('--snapshots',required=True)
    parser.add_argument('--model-version')
    parser.add_argument('--quantile',type=float,default=0.95)
    args=parser.parse_args(argv)
    print(json.dumps(request_for_artifact(kind=args.kind,path=args.snapshots,
          model_version=args.model_version,quantile=args.quantile),sort_keys=True))


if __name__=='__main__':
    main()
