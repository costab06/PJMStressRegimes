"""Tests for real-data episode alignment and coverage without invented PJM data."""
import numpy as np
import pandas as pd
import pytest

from gridregime.episode_timeseries_audit import FEATURES, audit_timeseries, episode_anchors


def events():
    return pd.DataFrame([
        {"episode_id":"ELL_2022","severity":"S3",
         "operator_action_time":"2022-12-23T17:30:00-05:00",
         "first_alert_time":"","window_start":"2022-12-20T17:30:00-05:00"},
        {"episode_id":"ELL_2022","severity":"S3",
         "operator_action_time":"2022-12-24T04:25:00-05:00",
         "first_alert_time":"","window_start":"2022-12-21T04:25:00-05:00"},
        {"episode_id":"HEAT_2023","severity":"S2",
         "operator_action_time":"","first_alert_time":"2023-07-26T21:28:00-04:00",
         "window_start":"2023-07-24T00:00:00-04:00"},
        {"episode_id":"COLD_2018","severity":"S1",
         "operator_action_time":"","first_alert_time":"",
         "window_start":"2018-01-02T00:00:00-05:00"},
    ])


def hourly(anchor="2022-12-23T22:30:00Z"):
    end=pd.Timestamp(anchor).floor("h")
    stamps=pd.date_range(end=end-pd.Timedelta(hours=1),periods=24,freq="h",tz="UTC")
    frame=pd.DataFrame({"timestamp_utc":stamps})
    for feature in FEATURES:
        frame[feature]=np.arange(24,dtype=float)
    return frame


def test_repeated_elliott_actions_are_one_episode():
    anchors=episode_anchors(events())
    assert len(anchors)==3
    ell=anchors.set_index("episode_id").loc["ELL_2022"]
    assert ell["catalog_rows"]==2
    assert ell["anchor_utc"]==pd.Timestamp("2022-12-23T22:30:00Z")


def test_complete_window_excludes_action_hour():
    report=audit_timeseries(hourly(),events())
    ell=next(e for e in report["episodes"] if e["episode_id"]=="ELL_2022")
    assert ell["status"]=="complete"
    assert ell["complete_hours"]==24
    assert ell["LoadZ_delta"]==23.0
    assert report["independent_episodes"]==3
    assert report["by_severity"]=={"S1":1,"S2":1,"S3":1}


def test_missing_hour_detected_without_interpolation():
    data=hourly().drop(index=4)
    report=audit_timeseries(data,events())
    ell=next(e for e in report["episodes"] if e["episode_id"]=="ELL_2022")
    assert ell["status"]=="incomplete"
    assert ell["missing_hours"]==1


def test_missing_s1_anchor_not_fabricated():
    report=audit_timeseries(hourly(),events())
    cold=next(e for e in report["episodes"] if e["episode_id"]=="COLD_2018")
    assert cold["status"]=="missing_anchor"
    assert cold["anchor_utc"] is None


def test_duplicate_hourly_timestamp_rejected():
    data=hourly()
    with pytest.raises(ValueError,match="duplicate_hourly_timestamp"):
        audit_timeseries(pd.concat([data,data.iloc[:1]]),events())


def test_conflicting_episode_severity_rejected():
    catalog=events()
    catalog.loc[1,"severity"]="S2"
    with pytest.raises(ValueError,match="inconsistent_episode_severity"):
        episode_anchors(catalog)
