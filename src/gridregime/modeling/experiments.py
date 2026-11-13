"""Immutable, auditable experiment manifests without executing a predictive model."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import tempfile


def record_experiment(*, output_dir: str | Path, model_id: str, dataset_sha256: str,
                      baseline_sha256: str, code_revision: str, parameters: dict,
                      evaluation_design: str, status: str = "descriptive-only") -> dict:
    if status != "descriptive-only":
        raise ValueError("Predictive validation cannot be asserted by manifest creation")
    for digest in (dataset_sha256, baseline_sha256):
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("Invalid SHA-256")
    if not model_id or not code_revision or not evaluation_design:
        raise ValueError("Missing experiment identity")
    payload = {"schema_version":1,"model_id":model_id,"dataset_sha256":dataset_sha256,
        "baseline_sha256":baseline_sha256,"code_revision":code_revision,
        "parameters":parameters,"evaluation_design":evaluation_design,
        "status":status,"feature_version":"frozen-v1"}
    encoded = (json.dumps(payload,sort_keys=True,allow_nan=False,separators=(",",":"))+"\n").encode()
    digest = hashlib.sha256(encoded).hexdigest()
    directory = Path(output_dir)
    directory.mkdir(parents=True,exist_ok=True)
    target = directory / f"experiment-{digest}.json"
    if target.exists():
        if target.read_bytes() != encoded:
            raise ValueError("Existing experiment manifest differs")
    else:
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(dir=directory,delete=False) as f:
                f.write(encoded)
                tmp = Path(f.name)
            os.replace(tmp,target)
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
    return {"artifact_path":str(target),"sha256":digest,**payload}
