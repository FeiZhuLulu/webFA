"""Unit tests for plan hashing."""

from planner.plan_hash import canonical_json, compute_diff_hash, compute_plan_hash


def test_canonical_json_sorted_keys():
    result = canonical_json({"b": 2, "a": 1})
    assert result == '{"a":1,"b":2}'


def test_canonical_json_no_whitespace():
    result = canonical_json({"key": "value", "num": 42})
    assert " " not in result


def test_plan_hash_deterministic():
    h1 = compute_plan_hash("mock.patch_and_open_pr", {"owner": "test"}, {}, [], "high")
    h2 = compute_plan_hash("mock.patch_and_open_pr", {"owner": "test"}, {}, [], "high")
    assert h1 == h2
    assert h1.startswith("sha256:")


def test_plan_hash_changes_with_input():
    h1 = compute_plan_hash("mock.patch_and_open_pr", {"owner": "a"}, {}, [], "high")
    h2 = compute_plan_hash("mock.patch_and_open_pr", {"owner": "b"}, {}, [], "high")
    assert h1 != h2


def test_plan_hash_changes_with_risk():
    h1 = compute_plan_hash("mock.patch_and_open_pr", {}, {}, [], "high")
    h2 = compute_plan_hash("mock.patch_and_open_pr", {}, {}, [], "low")
    assert h1 != h2


def test_plan_hash_changes_with_steps():
    h1 = compute_plan_hash("mock.patch_and_open_pr", {}, {}, [], "high")
    h2 = compute_plan_hash("mock.patch_and_open_pr", {}, {}, [{"step": "a"}], "high")
    assert h1 != h2


def test_diff_hash_deterministic():
    h1 = compute_diff_hash("--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new")
    h2 = compute_diff_hash("--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new")
    assert h1 == h2
    assert h1.startswith("sha256:")


def test_diff_hash_changes_with_content():
    h1 = compute_diff_hash("diff A")
    h2 = compute_diff_hash("diff B")
    assert h1 != h2
