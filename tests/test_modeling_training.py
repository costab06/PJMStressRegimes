import numpy as np
import pandas as pd
import pytest
from gridregime.modeling.contracts import FeatureDataset
from gridregime.modeling.training import fit_episode_hmm
from gridregime.modeling.runner import causal_state_probabilities, run_descriptive_hmm_experiment

SHA = "a"*64

def episode(name, offset):
    n=32
    rng=np.random.default_rng(offset)
    frame=pd.DataFrame({"timestamp_utc":pd.date_range(f"2022-12-{offset+1:02d}",periods=n,freq="h",tz="UTC"),
      "load_z":rng.normal(size=n),"fe_z":rng.normal(size=n),
      "ramp3_z":rng.normal(size=n),"ic_z":rng.normal(size=n)})
    return FeatureDataset(frame,"PJM",SHA,SHA,episode_id=name)

def test_training_uses_episode_lengths(monkeypatch):
    import gridregime.modeling.training as training
    actual=training.GaussianHMM
    seen=[]
    class CapturingHMM(actual):
        def fit(self,X,lengths=None):
            seen.append(lengths)
            return super().fit(X,lengths=lengths)
    monkeypatch.setattr(training,"GaussianHMM",CapturingHMM)
    fitted=fit_episode_hmm([episode("a",1),episode("b",2)],n_components=2,n_iter=10)
    assert seen==[[32,32]]
    assert fitted.episode_ids==("a","b")

def test_duplicate_episode_rejected():
    with pytest.raises(ValueError,match="distinct"):
        fit_episode_hmm([episode("a",1),episode("a",2)])

def test_causal_prefix_and_runner(tmp_path):
    episodes=[episode("a",1),episode("b",2),episode("c",3)]
    fitted=fit_episode_hmm(episodes[:2],n_components=2,n_iter=15)
    full=causal_state_probabilities(fitted.model,fitted.scaler,episodes[2])
    prefix=FeatureDataset(episodes[2].frame.iloc[:10].copy(),"PJM",SHA,SHA,episode_id="c")
    partial=causal_state_probabilities(fitted.model,fitted.scaler,prefix)
    np.testing.assert_allclose(full[:10],partial,atol=1e-8)
    assert np.allclose(full.sum(axis=1),1)
    result=run_descriptive_hmm_experiment(episodes,output_dir=tmp_path,code_revision="test",n_components=2)
    assert result["rows"]==96
    assert set(pd.read_parquet(result["predictions_path"])["episode_id"])=={"a","b","c"}
    assert result["manifest"]["status"]=="descriptive-only"
