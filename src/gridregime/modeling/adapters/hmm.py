"""Gaussian HMM adapter; operational inference uses causal filtering, not Viterbi."""
import numpy as np
from gridregime.models import hmm
from gridregime.modeling.contracts import FeatureDataset, ModelResult

class HMMAdapter:
    model_id = "gaussian-hmm"
    model_version = "0.1.0"

    def __init__(self, **params):
        self.params = params
        self.model = None
        self.scaler = None

    def fit(self, dataset: FeatureDataset):
        self.model, self.scaler = hmm.fit(dataset.matrix(), **self.params)
        return self

    def infer(self, dataset: FeatureDataset, *, decision_as_of: str) -> ModelResult:
        if self.model is None:
            raise RuntimeError("Model has not been fitted")
        X = self.scaler.transform(dataset.matrix().to_numpy())
        # Forward-only recursion: posterior at t uses observations through t, never later hours.
        log_emissions = self.model._compute_log_likelihood(X)
        from scipy.special import logsumexp
        alpha = np.log(self.model.startprob_) + log_emissions[0]
        alpha -= logsumexp(alpha)
        for emission in log_emissions[1:]:
            alpha = logsumexp(alpha[:, None] + np.log(self.model.transmat_), axis=0) + emission
            alpha -= logsumexp(alpha)
        probabilities = np.exp(alpha)
        return ModelResult(self.model_id, self.model_version, "latent_regime",
            str(dataset.frame["timestamp_utc"].iloc[-1]), decision_as_of,
            {"state_probabilities": probabilities.tolist(), "state_id": int(np.argmax(probabilities))})
