"""Descriptive HMM experiment runner with held-out episode predictions.

    Produces experiment artifacts; does not evaluate or assert emergency prediction.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.special import logsumexp
from .contracts import FeatureDataset
from .training import fit_episode_hmm
from .experiments import record_experiment


def causal_state_probabilities(model, scaler, dataset: FeatureDataset) -> np.ndarray:
    """Forward filter at each hour; never smooth using future observations."""
    X = scaler.transform(dataset.matrix().to_numpy(dtype=float))
    emissions = model._compute_log_likelihood(X)
    with np.errstate(divide="ignore"):
        log_start = np.log(model.startprob_)
        log_trans = np.log(model.transmat_)
    alpha = log_start + emissions[0]
    alpha -= logsumexp(alpha)
    result = [np.exp(alpha)]
    for emission in emissions[1:]:
        alpha = logsumexp(alpha[:, None] + log_trans, axis=0) + emission
        alpha -= logsumexp(alpha)
        result.append(np.exp(alpha))
    return np.asarray(result)


def run_descriptive_hmm_experiment(episodes: list[FeatureDataset], *, output_dir: str | Path,
                                   code_revision: str, n_components: int = 3,
                                   random_state: int = 42) -> dict:
    """Run LOEO descriptive state estimation; no predictive outcome labels used."""
    if len(episodes) < 3:
        raise ValueError("At least three episodes needed to train on >=2 while holding one out")
    ids = [e.episode_id for e in episodes]
    if any(not x for x in ids) or len(set(ids)) != len(ids):
        raise ValueError("Distinct nonempty episode IDs required")
    if len({e.baseline_sha256 for e in episodes}) != 1 or len({e.ba for e in episodes}) != 1:
        raise ValueError("Incompatible baseline or BA across episodes")
    # Hash the actual ordered modeling inputs, not only the source version labels.
    hasher = hashlib.sha256()
    for episode in sorted(episodes, key=lambda e:e.episode_id):
        hasher.update(json.dumps({"id":episode.episode_id,"source":episode.source_sha256,
          "times":[str(t) for t in episode.frame["timestamp_utc"]],
          "features":episode.matrix().to_numpy(dtype=float).tolist()},sort_keys=True).encode())
    dataset_hash = hasher.hexdigest()
    root = Path(output_dir)
    manifest = record_experiment(output_dir=root,model_id="gaussian-hmm",
        dataset_sha256=dataset_hash,baseline_sha256=episodes[0].baseline_sha256,
        code_revision=code_revision,parameters={"n_components":n_components,"random_state":random_state},
        evaluation_design="leave-one-episode-out descriptive state estimation")
    experiment_dir = root / manifest["sha256"]
    experiment_dir.mkdir(parents=True,exist_ok=True)
    rows = []
    for held_out in episodes:
        train = [e for e in episodes if e.episode_id != held_out.episode_id]
        fitted = fit_episode_hmm(train,n_components=n_components,random_state=random_state)
        probabilities = causal_state_probabilities(fitted.model,fitted.scaler,held_out)
        for timestamp, probability in zip(held_out.frame["timestamp_utc"], probabilities):
            row = {"episode_id":held_out.episode_id,"timestamp_utc":str(timestamp),
                   "latent_state":int(np.argmax(probability))}
            row.update({f"state_{i}_probability":float(p) for i,p in enumerate(probability)})
            rows.append(row)
    predictions = pd.DataFrame(rows)
    # Models are refitted in each fold: latent state numbers are NOT aligned across folds.
    destination = experiment_dir / "held_out_latent_states.parquet"
    predictions.to_parquet(destination,index=False)
    return {"manifest":manifest,"predictions_path":str(destination),
            "episodes":len(episodes),"rows":len(predictions),
            "warning":"Latent state IDs are fold-local and must not be compared across folds."}
