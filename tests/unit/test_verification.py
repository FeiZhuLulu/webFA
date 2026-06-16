"""Unit tests for VerificationService."""

from verification.engine import VerificationService


def test_verify_all_pass():
    svc = VerificationService()
    result = svc.verify(
        execution_result={
            "branch": "webfa/issue-1-fix",
            "commit_sha": "commit_abc123",
            "pr_url": "mock://github/test/repo/pull/1",
            "diff_hash": "sha256:abc",
        },
        expected_diff_hash="sha256:abc",
    )
    assert result.passed is True
    assert len(result.checks) == 4
    assert all(c.passed for c in result.checks)


def test_verify_diff_hash_mismatch():
    svc = VerificationService()
    result = svc.verify(
        execution_result={
            "branch": "webfa/issue-1-fix",
            "commit_sha": "commit_abc123",
            "pr_url": "mock://github/test/repo/pull/1",
            "diff_hash": "sha256:wrong",
        },
        expected_diff_hash="sha256:abc",
    )
    assert result.passed is False
    diff_check = next(c for c in result.checks if c.name == "diff_hash_matches")
    assert diff_check.passed is False


def test_verify_missing_pr():
    svc = VerificationService()
    result = svc.verify(
        execution_result={
            "branch": "webfa/issue-1-fix",
            "commit_sha": "commit_abc123",
        },
    )
    assert result.passed is False
    pr_check = next(c for c in result.checks if c.name == "mock_pr_exists")
    assert pr_check.passed is False
