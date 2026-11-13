"""Offline changepoint adapter; not an operational online detector."""
from gridregime.models import changepoint
from gridregime.modeling.contracts import FeatureDataset, ModelResult

class ChangepointAdapter:
    model_id = "changepoint-pelt"
    model_version = "0.1.0"

    def __init__(self, *, feature: str = "load_z", **params):
        from gridregime.modeling.contracts import FROZEN_FEATURES
        if feature not in FROZEN_FEATURES:
            raise ValueError("Feature must belong to frozen-v1")
        self.feature = feature
        self.params = params

    def fit(self, dataset: FeatureDataset):
        return self

    def infer(self, dataset: FeatureDataset, *, decision_as_of: str) -> ModelResult:
        indices = changepoint.detect(dataset.frame[self.feature], **self.params)
        # PELT is an offline segmentation of the supplied window; do not call it an online alarm.
        return ModelResult(self.model_id, self.model_version, "retrospective_changepoints",
            str(dataset.frame["timestamp_utc"].iloc[-1]), decision_as_of,
            {"feature": self.feature, "indices": [int(i) for i in indices]})
