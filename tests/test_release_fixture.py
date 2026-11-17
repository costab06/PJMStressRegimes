import pandas as pd
from gridregime.demo import validate, analyze
from tools.prepare_release_demo import make_fixture

def test_synthetic_fixture_runs_offline(tmp_path):
    path = make_fixture(tmp_path / "sample.parquet")
    result = analyze(validate(pd.read_parquet(path)))
    assert result["observed_hours"] == 25
    assert result["maximum_hourly_demand_increase_mwh"] > 0
