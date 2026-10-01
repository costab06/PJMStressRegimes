"""Hidden Markov Model regime detection."""

from __future__ import annotations

import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import StandardScaler


def fit(
    X: pd.DataFrame,
    n_components: int = 3,
    covariance_type: str = "full",
    n_iter: int = 200,
    random_state: int = 42,
) -> tuple[GaussianHMM, StandardScaler]:
    """Fit a Gaussian HMM to the feature matrix.

    Args:
        X: Feature DataFrame (rows = hourly timesteps).
        n_components: Number of hidden states (regimes).
        covariance_type: HMM covariance structure.
        n_iter: EM iterations.
        random_state: Reproducibility seed.

    Returns:
        (fitted model, fitted scaler)
    """
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X.to_numpy())
    model = GaussianHMM(
        n_components=n_components,
        covariance_type=covariance_type,
        n_iter=n_iter,
        random_state=random_state,
    )
    model.fit(X_scaled)
    return model, scaler


def predict_states(
    model: GaussianHMM,
    scaler: StandardScaler,
    X: pd.DataFrame,
) -> np.ndarray:
    """Decode most likely state sequence via Viterbi."""
    X_scaled = scaler.transform(X.to_numpy())
    return model.predict(X_scaled)


def bic(model: GaussianHMM, X_scaled: np.ndarray) -> float:
    """Bayesian Information Criterion for model selection."""
    log_likelihood = model.score(X_scaled)
    n_params = model.n_components ** 2 + model.n_components * X_scaled.shape[1] * 2
    return -2 * log_likelihood * len(X_scaled) + n_params * np.log(len(X_scaled))
