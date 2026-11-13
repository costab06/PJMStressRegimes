import numpy as np
import pandas as pd
import pytest
from gridregime.modeling import FeatureDataset, ModelResult, FROZEN_FEATURES, available_models, create_adapter

SHA = "a" * 64

def sample_frame(n=12):
    frame = pd.DataFrame({"timestamp_utc": pd.date_range("2022-12-20", periods=n, freq="h", tz="UTC"), "ba": ["PJM"] * n})
    for i, feature in enumerate(FROZEN_FEATURES):
        frame[feature] = np.arange(n, dtype=float) / (i + 1)
    return frame

def dataset(frame=None):
    return FeatureDataset(sample_frame() if frame is None else frame, "PJM", SHA, SHA)

def test_contract_and_order():
    d = dataset()
    assert list(d.matrix().columns) == list(FROZEN_FEATURES)
    assert d.matrix().shape == (12, 4)
    assert set(available_models()) == {"isolation-forest", "gaussian-hmm", "changepoint-pelt", "xgboost"}
    with pytest.raises(ValueError, match="Unknown model"):
        create_adapter("unknown")

def test_reject_gaps_duplicates_and_nonfinite():
    for changed in ("gap", "duplicate", "nan"):
        f = sample_frame()
        if changed == "gap":
            f.loc[4, "timestamp_utc"] += pd.Timedelta(hours=2)
        elif changed == "duplicate":
            f.loc[4, "timestamp_utc"] = f.loc[3, "timestamp_utc"]
        else:
            f.loc[4, "load_z"] = np.nan
        with pytest.raises(ValueError):
            dataset(f)

def test_reject_future_decision_and_unvalidated_status():
    with pytest.raises(ValueError, match="Decision time"):
        ModelResult("m", "v1", "score", "2022-12-20T04:00Z", "2022-12-20T03:00Z", {})
    with pytest.raises(ValueError, match="cannot assert predictive validation"):
        ModelResult("m", "v1", "score", "2022-12-20T04:00Z", "2022-12-20T04:00Z", {}, predictive_validation_status="validated")

def test_isolation_forest_adapter_smoke():
    d = dataset()
    adapter = create_adapter("isolation-forest", n_estimators=10).fit(d)
    result = adapter.infer(d, decision_as_of="2022-12-20T12:00Z")
    assert result.result_type == "anomaly_scores"
    assert len(result.values["scores"]) == 12
    assert result.predictive_validation_status == "not_established"

def test_hmm_adapter_causal_prefix_invariance():
    d = dataset()
    adapter = create_adapter("gaussian-hmm", n_components=2, covariance_type="diag", n_iter=20).fit(d)
    first = adapter.infer(FeatureDataset(d.frame.iloc[:8].copy(), "PJM", SHA, SHA), decision_as_of="2022-12-20T08:00Z")
    altered = d.frame.copy()
    altered.loc[8:, "load_z"] += 1000
    second = adapter.infer(FeatureDataset(altered.iloc[:8].copy(), "PJM", SHA, SHA), decision_as_of="2022-12-20T08:00Z")
    np.testing.assert_allclose(first.values["state_probabilities"], second.values["state_probabilities"])
    assert abs(sum(first.values["state_probabilities"]) - 1) < 1e-8
