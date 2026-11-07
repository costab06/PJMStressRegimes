"""Unit tests for research workflow provenance."""
from gridregime.provenance import build_manifest, sha256_file


def test_file_digest_changes_with_contents(tmp_path):
    path = tmp_path / "input.csv"
    path.write_bytes(b"a,b\n1,2\n")
    first = sha256_file(path)
    assert first == sha256_file(path)
    path.write_bytes(b"a,b\n1,3\n")
    assert sha256_file(path) != first


def test_manifest_is_order_independent_and_detects_changes(tmp_path):
    spec = tmp_path / "research_spec.yaml"
    spec.write_text("feature_freeze: FROZEN\n")
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.write_text("a\n")
    b.write_text("b\n")
    first = build_manifest("ELL_2022", spec, [a, b], code_revision="abc")
    reordered = build_manifest("ELL_2022", spec, [b, a], code_revision="abc")
    assert first == reordered
    b.write_text("changed\n")
    changed = build_manifest("ELL_2022", spec, [a, b], code_revision="abc")
    assert changed["fingerprint_sha256"] != first["fingerprint_sha256"]


def test_episode_and_specification_change_fingerprint(tmp_path):
    spec = tmp_path / "spec.yaml"
    spec.write_text("v1")
    first = build_manifest("ELL_2022", spec, [])
    other = build_manifest("COLD_2018", spec, [])
    assert first["fingerprint_sha256"] != other["fingerprint_sha256"]
    spec.write_text("v2")
    updated = build_manifest("ELL_2022", spec, [])
    assert first["fingerprint_sha256"] != updated["fingerprint_sha256"]
