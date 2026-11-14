import hashlib
import json
import pandas as pd
import pytest
from gridregime.modeling.datasets import load_feature_sequence, load_episode_catalog
from gridregime.modeling.evaluation import leave_one_episode_out, episode_inventory
from gridregime.modeling.experiments import record_experiment

SHA = "a"*64

def test_load_real_contract_snapshots(tmp_path):
    paths=[]
    for i in range(4):
        p=tmp_path/f"feature-{i}.json"
        p.write_text(json.dumps({"as_of":f"2022-12-20T0{i}:00:00Z","ba":"PJM",
          "feature_version":"frozen-v1","status":"features-only-not-a-risk-prediction",
          "source_sha256":SHA,"baseline_sha256":SHA,
          "features":{"load_z":i,"fe_z":i+1,"ramp3_z":i+2,"ic_z":i+3}}))
        paths.append(p)
    hashes=[hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
    d=load_feature_sequence(paths[::-1],expected_hashes=hashes[::-1],episode_id="ELL_2022")
    assert d.matrix().shape==(4,4)
    assert d.episode_id=="ELL_2022"
    assert not d.publication_time_verified
    with pytest.raises(ValueError,match="SHA-256"):
        load_feature_sequence(paths,expected_hashes=[SHA]*4)

def test_catalog_episode_count_and_grouped_splits():
    catalog=load_episode_catalog("metadata/events.csv")
    inventory=episode_inventory(catalog)
    assert inventory["independent_episodes"].sum() < len(catalog)
    ids=catalog["episode_id"].tolist()
    for train,test,held_out in leave_one_episode_out(ids):
        assert held_out not in set(catalog.iloc[train]["episode_id"])
        assert set(catalog.iloc[test]["episode_id"])=={held_out}

def test_experiment_immutable(tmp_path):
    kw=dict(output_dir=tmp_path,model_id="isolation-forest",dataset_sha256=SHA,
        baseline_sha256=SHA,code_revision="test",parameters={"seed":42},evaluation_design="LOEO")
    first=record_experiment(**kw)
    second=record_experiment(**kw)
    assert first["sha256"]==second["sha256"]
    with pytest.raises(ValueError,match="Predictive"):
        record_experiment(**kw,status="validated")
