"""Isolation Forest adapter around the existing implementation."""
from gridregime.models import anomaly
from gridregime.modeling.contracts import FeatureDataset, ModelResult

class IsolationForestAdapter:
    model_id = "isolation-forest"
    model_version = "0.1.0"

    def __init__(self, **params):
        self.params = params
        self.model = None

    def fit(self, dataset: FeatureDataset):
        self.model = anomaly.fit_isolation_forest(dataset.matrix(), **self.params)
        return self

    def infer(self, dataset: FeatureDataset, *, decision_as_of: str) -> ModelResult:
        if self.model is None:
            raise RuntimeError("Model has not been fitted")
        scores = anomaly.anomaly_scores(self.model, dataset.matrix())
        flags = anomaly.predict(self.model, dataset.matrix())
        return ModelResult(self.model_id, self.model_version, "anomaly_scores",
            str(dataset.frame["timestamp_utc"].iloc[-1]), decision_as_of,
            {"scores": scores.tolist(), "flags": flags.tolist()})
