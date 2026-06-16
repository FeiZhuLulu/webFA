"""Unit tests for PolicyEngine."""

from policy.engine import PolicyEngine
from schemas.common import ChangedFile


def test_high_risk_requires_approval():
    engine = PolicyEngine()
    result = engine.check(
        transaction_id="mock.patch_and_open_pr",
        provider="mock",
        risk="high",
        changed_files=[],
        diff_text="",
    )
    assert result.approval_required is True
    assert len(result.risk_flags) == 1
    assert result.risk_flags[0].code == "high_risk_write"


def test_low_risk_no_approval():
    engine = PolicyEngine()
    result = engine.check(
        transaction_id="mock.patch_and_open_pr",
        provider="mock",
        risk="low",
        changed_files=[],
        diff_text="",
    )
    assert result.approval_required is False
    assert len(result.risk_flags) == 0


def test_blocked_path_returns_not_allowed():
    engine = PolicyEngine()
    result = engine.check(
        transaction_id="mock.patch_and_open_pr",
        provider="mock",
        risk="high",
        changed_files=[ChangedFile(path=".env")],
        diff_text="",
    )
    assert result.allowed is False
    assert any(v.code == "blocked_path" for v in result.blocked)


def test_too_many_files_returns_not_allowed():
    engine = PolicyEngine()
    files = [ChangedFile(path=f"src/file{i}.py") for i in range(6)]
    result = engine.check(
        transaction_id="mock.patch_and_open_pr",
        provider="mock",
        risk="high",
        changed_files=files,
        diff_text="",
    )
    assert result.allowed is False
    assert any(v.code == "too_many_files" for v in result.blocked)


def test_diff_too_large_returns_not_allowed():
    engine = PolicyEngine()
    big_diff = "\n".join([f"+line {i}" for i in range(801)])
    result = engine.check(
        transaction_id="mock.patch_and_open_pr",
        provider="mock",
        risk="high",
        changed_files=[],
        diff_text=big_diff,
    )
    assert result.allowed is False
    assert any(v.code == "diff_too_large" for v in result.blocked)


def test_normal_mock_diff_returns_allowed():
    engine = PolicyEngine()
    result = engine.check(
        transaction_id="mock.patch_and_open_pr",
        provider="mock",
        risk="high",
        changed_files=[ChangedFile(path="src/example.py", additions=12, deletions=3)],
        diff_text="--- a/src/example.py\n+++ b/src/example.py\n@@ -1 +1 @@\n-old\n+new",
    )
    assert result.allowed is True
    assert result.approval_required is True


def test_custom_blocked_paths():
    engine = PolicyEngine()
    result = engine.check(
        transaction_id="mock.patch_and_open_pr",
        provider="mock",
        risk="high",
        changed_files=[ChangedFile(path="secret/config.yaml")],
        diff_text="",
        blocked_paths=["secret/**"],
    )
    assert result.allowed is False
