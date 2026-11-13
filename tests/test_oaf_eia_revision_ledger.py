"""EIA snapshot revision and source-availability contract tests."""
import pytest

from gridregime.oaf.eia_revision_ledger import (
    assert_point_in_time_eligible, list_versions, record_snapshot,
)


def test_revisions_preserve_both_versions_and_first_observed_time(tmp_path):
    args = dict(ledger_dir=tmp_path, ba="PJM", start="2022-12-20T00:00:00+00:00",
                end="2022-12-20T01:00:00+00:00")
    first = record_snapshot(**args, sha256="a" * 64,
                            observed_at="2022-12-21T00:00:00Z")
    replay = record_snapshot(**args, sha256="a" * 64,
                             observed_at="2022-12-22T00:00:00Z")
    assert replay == first
    second = record_snapshot(**args, sha256="b" * 64,
                             observed_at="2022-12-23T00:00:00Z")
    versions = list_versions(**args)
    assert [v["sha256"] for v in versions] == ["a" * 64, "b" * 64]
    assert second["collector_observed_at_utc"] != first["collector_observed_at_utc"]
    assert all(v["publication_time_verified"] is False for v in versions)


def test_source_availability_fails_closed_without_publication_proof(tmp_path):
    record = record_snapshot(
        ledger_dir=tmp_path, ba="PJM",
        start="2022-12-20T00:00:00Z", end="2022-12-20T01:00:00Z",
        sha256="a" * 64, observed_at="2022-12-20T06:00:00Z",
    )
    with pytest.raises(ValueError, match="publication time is unverified"):
        assert_point_in_time_eligible(record, "2022-12-20T07:00:00Z")
    approved = {**record, "publication_time_verified": True,
                "revision_history_verified": True,
                "source_published_at_utc": "2022-12-20T08:00:00Z"}
    with pytest.raises(ValueError, match="after decision"):
        assert_point_in_time_eligible(approved, "2022-12-20T07:00:00Z")
    assert_point_in_time_eligible(approved, "2022-12-20T09:00:00Z") is None
    with pytest.raises(ValueError, match="revision history is unverified"):
        assert_point_in_time_eligible(
            {**approved, "revision_history_verified": False},
            "2022-12-20T09:00:00Z",
        )
