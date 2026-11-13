"""Supervised XGBoost adapter. Requires externally curated labels and validation split."""
import pandas as pd
from gridregime.models import xgboost
from gridregime.modeling.contracts import FeatureDataset, ModelResult

class XGBoostAdapter:
    model_id = "xgboost"
    model_version = "0.1.0"

    def __init__(self, **params):
        self.params = params
        self.model = None

    def fit(self, dataset: FeatureDataset, *, labels: pd.Series, validation: FeatureDataset,
            validation_labels: pd.Series):
        if len(labels) != len(dataset.frame) or len(validation_labels) != len(validation.frame):
            raise ValueError("Labels must align to dataset rows")
        if set(labels.dropna().unique()) != {0, 1} or set(validation_labels.dropna().unique()) != {0, 1}:
            raise ValueError("Training and validation must contain both binary classes")
        if dataset.episode_id is None or validation.episode_id is None or dataset.episode_id == validation.episode_id:
            raise ValueError("Training and validation require disjoint episode identities")
        self.model = xgboost.fit(dataset.matrix(), labels, validation.matrix(), validation_labels, self.params)
        return self

    def infer(self, dataset: FeatureDataset, *, decision_as_of: str) -> ModelResult:
        if self.model is None:
            raise RuntimeError("Model has not been fitted")
        proba = self.model.predict_proba(dataset.matrix())[:, 1]
        return ModelResult(self.model_id, self.model_version, "unvalidated_classification_score",
            str(dataset.frame["timestamp_utc"].iloc[-1]), decision_as_of,
            {"scores": proba.tolist()})
