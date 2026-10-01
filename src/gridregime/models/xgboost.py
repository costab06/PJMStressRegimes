"""XGBoost classifier for supervised regime/stress labeling."""

from __future__ import annotations

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import roc_auc_score


def fit(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    params: dict | None = None,
) -> xgb.XGBClassifier:
    """Fit XGBoost classifier with early stopping.

    Args:
        X_train: Training features.
        y_train: Binary labels (1 = stress event).
        X_val: Validation features for early stopping.
        y_val: Validation labels.
        params: Override default hyperparameters.

    Returns:
        Fitted XGBClassifier.
    """
    defaults = dict(
        n_estimators=500,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        use_label_encoder=False,
        eval_metric="logloss",
        early_stopping_rounds=50,
        random_state=42,
        n_jobs=-1,
    )
    if params:
        defaults.update(params)

    model = xgb.XGBClassifier(**defaults)
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    return model


def feature_importance(model: xgb.XGBClassifier, feature_names: list[str]) -> pd.Series:
    """Return feature importances as a sorted Series."""
    return pd.Series(model.feature_importances_, index=feature_names).sort_values(ascending=False)
