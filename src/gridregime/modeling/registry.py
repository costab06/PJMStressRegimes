"""Explicit model allowlist; no dynamic imports or arbitrary code from manifests."""
from gridregime.modeling.adapters.anomaly import IsolationForestAdapter
from gridregime.modeling.adapters.changepoint import ChangepointAdapter
from gridregime.modeling.adapters.hmm import HMMAdapter
from gridregime.modeling.adapters.xgboost import XGBoostAdapter

_ADAPTERS = {
    "isolation-forest": IsolationForestAdapter,
    "changepoint-pelt": ChangepointAdapter,
    "gaussian-hmm": HMMAdapter,
    "xgboost": XGBoostAdapter,
}

def available_models() -> tuple[str, ...]:
    return tuple(sorted(_ADAPTERS))

def create_adapter(model_id: str, **params):
    try:
        return _ADAPTERS[model_id](**params)
    except KeyError as exc:
        raise ValueError(f"Unknown model: {model_id}") from exc
