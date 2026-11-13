import json
import pandas as pd
import pytest
from gridregime.modeling.replay import prepare_episodes

SHA = "a"*64

def write_snapshot(folder, time, value):
    folder.mkdir(exist_ok=True,parents=True)
    p=folder/f"features-{time.strftime('%Y%m%d%H')}.json"
    p.write_text(json.dumps({"as_of":time.isoformat(),"ba":"PJM","feature_version":"frozen-v1",
      "status":"features-only-not-a-risk-prediction","source_sha256":SHA,
      "baseline_sha256":SHA,"features":{"load_z":value,"fe_z":value,
      "ramp3_z":value,"ic_z":value}}))
    return p

def test_missing_artifacts_fail_closed(tmp_path):
    with pytest.raises(ValueError,match="No frozen-v1"):
        prepare_episodes(feature_dir=tmp_path,events_csv="metadata/events.csv")

def test_episode_coverage_requires_every_hour(tmp_path):
    catalog=tmp_path/"events.csv"
    catalog.write_text("event_id,episode_id,severity,window_start,event_end\n"
      "E1,EP1,S2,2022-01-01T00:00Z,2022-01-01T03:00Z\n"
      "E2,EP2,S3,2022-01-02T00:00Z,2022-01-02T03:00Z\n")
    root=tmp_path/"features"
    for t in pd.date_range("2022-01-01",periods=4,freq="h",tz="UTC"):
        write_snapshot(root,t,1.0)
    write_snapshot(root,pd.Timestamp("2022-01-02T00:00Z"),1.0)
    episodes,coverage=prepare_episodes(feature_dir=root,events_csv=catalog)
    assert len(episodes)==1
    assert coverage.set_index("episode_id").loc["EP2","missing_hours"]==3
