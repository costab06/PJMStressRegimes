"""Domain-specific application contracts; OpenAgentFabric owns orchestration."""
from .contracts import FeatureSnapshot, StressSignal, TrainingCandidate
from .service import evaluate_stress, candidate_from_training

__all__ = ["FeatureSnapshot", "StressSignal", "TrainingCandidate", "evaluate_stress", "candidate_from_training"]
