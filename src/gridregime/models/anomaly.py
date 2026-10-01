"""Anomaly detection models: Isolation Forest and LOF."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import StandardScaler


def fit_isolation_forest(
    X: pd.DataFrame,
    contamination: float = 0.02,
    n_estimators: int = 200,
    random_state: int = 42,
) -> IsolationForest:
    """Fit an Isolation Forest on feature matrix X."""
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    model = IsolationForest(
        n_estimators=n_estimators,
        contamination=contamination,
        random_state=random_state,
        n_jobs=-1,
    )
    model.fit(X_scaled)
    model._scaler = scaler  # attach for predict convenience
    return model


def predict(model: IsolationForest, X: pd.DataFrame) -> np.ndarray:
    """Return anomaly scores (-1 = anomaly, 1 = normal)."""
    X_scaled = model._scaler.transform(X)
    return model.predict(X_scaled)


def anomaly_scores(model: IsolationForest, X: pd.DataFrame) -> np.ndarray:
    """Return raw decision function scores (lower = more anomalous)."""
    X_scaled = model._scaler.transform(X)
    return model.decision_function(X_scaled)
