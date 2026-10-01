"""Cross-validation and scoring utilities for time series models."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, precision_score, recall_score, f1_score
from sklearn.model_selection import TimeSeriesSplit


def time_series_cv(
    model,
    X: pd.DataFrame,
    y: pd.Series,
    n_splits: int = 5,
) -> pd.DataFrame:
    """Walk-forward cross-validation.

    Args:
        model: Sklearn-compatible classifier with fit/predict_proba.
        X: Feature matrix (must be chronologically ordered).
        y: Binary labels.
        n_splits: Number of folds.

    Returns:
        DataFrame with per-fold metrics.
    """
    tscv = TimeSeriesSplit(n_splits=n_splits)
    rows = []
    for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
        X_tr, X_val = X.iloc[train_idx], X.iloc[val_idx]
        y_tr, y_val = y.iloc[train_idx], y.iloc[val_idx]
        model.fit(X_tr, y_tr)
        proba = model.predict_proba(X_val)[:, 1]
        pred = (proba >= 0.5).astype(int)
        rows.append({
            "fold": fold,
            "roc_auc": roc_auc_score(y_val, proba) if y_val.nunique() > 1 else float("nan"),
            "precision": precision_score(y_val, pred, zero_division=0),
            "recall": recall_score(y_val, pred, zero_division=0),
            "f1": f1_score(y_val, pred, zero_division=0),
        })
    return pd.DataFrame(rows)
