"""Episode-aware HMM training; no scientific predictive-validation claim."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from sklearn.preprocessing import StandardScaler
from hmmlearn.hmm import GaussianHMM
from .contracts import FeatureDataset

@dataclass
class FittedHMM:
    model: GaussianHMM
    scaler: StandardScaler
    episode_ids: tuple[str, ...]
    feature_version: str = "frozen-v1"


def fit_episode_hmm(episodes: list[FeatureDataset], *, n_components: int = 3,
                    covariance_type: str = "full", n_iter: int = 200,
                    random_state: int = 42) -> FittedHMM:
    """Fit on independent contiguous sequences, passing lengths to hmmlearn.

    Fitting is descriptive; do not interpret latent states as S1/S2/S3 labels.
    """
    if len(episodes) < 2:
        raise ValueError("At least two independent episodes are required")
    ids = [episode.episode_id for episode in episodes]
    if any(not episode_id for episode_id in ids) or len(set(ids)) != len(ids):
        raise ValueError("Each training sequence needs a distinct episode_id")
    if len({episode.baseline_sha256 for episode in episodes}) != 1:
        raise ValueError("Training episodes must share a frozen baseline")
    if len({episode.ba for episode in episodes}) != 1:
        raise ValueError("Training episodes must share a balancing authority")
    lengths = [len(episode.frame) for episode in episodes]
    if any(n < 2 for n in lengths):
        raise ValueError("Each episode requires at least two hours")
    X = np.vstack([episode.matrix().to_numpy(dtype=float) for episode in episodes])
    if len(X) < n_components:
        raise ValueError("Insufficient observations for requested HMM states")
    scaler = StandardScaler().fit(X)
    model = GaussianHMM(n_components=n_components, covariance_type=covariance_type,
                        n_iter=n_iter, random_state=random_state)
    model.fit(scaler.transform(X), lengths=lengths)
    return FittedHMM(model=model, scaler=scaler, episode_ids=tuple(ids))
