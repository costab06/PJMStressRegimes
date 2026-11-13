"""Modeling boundary: validated feature inputs, algorithm adapters, and results."""
from .contracts import FeatureDataset, ModelResult, FROZEN_FEATURES
from .registry import available_models, create_adapter

__all__ = ["FeatureDataset", "ModelResult", "FROZEN_FEATURES", "available_models", "create_adapter"]
