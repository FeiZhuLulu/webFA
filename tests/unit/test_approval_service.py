"""Unit tests for ApprovalService."""

from datetime import datetime, timedelta, timezone

from approvals.service import ApprovalService, _hash_token
from schemas.approval import ApprovalApproveRequest
from storage.db import session_scope
from storage.models import Approval, Plan, Workspace, new_id


def _create_test_plan_and_approval(session):
    """Helper to create a plan and pending approval for testing."""
    workspace = Workspace(id=new_id("workspace"), title="Test", status="active")
    session.add(workspace)
    plan = Plan(
        id=new_id("plan"),
        workspace_id=workspace.id,
        transaction_id="mock.patch_and_open_pr",
        input_json={},
        risk="high",
        plan_hash="sha256:testhash",
        status="pending_approval",
    )
    session.add(plan)
    approval = Approval(
        id=new_id("approval"),
        plan_id=plan.id,
        approval_level="user",
        approval_payload_json={"provider": "mock"},
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    session.add(approval)
    session.flush()
    return plan, approval


def test_approve_changes_status(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    from storage.db import init_db, reset_engine_for_tests
    reset_engine_for_tests()
    init_db()

    service = ApprovalService()
    with session_scope() as session:
        plan, approval = _create_test_plan_and_approval(session)
        result = service.approve(session, approval.id, user_note="LGTM")

    assert result.status == "approved"
    assert result.approval_token.startswith("approval_token_")
    assert result.approval_id == approval.id


def test_reject_changes_status(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    from storage.db import init_db, reset_engine_for_tests
    reset_engine_for_tests()
    init_db()

    service = ApprovalService()
    with session_scope() as session:
        plan, approval = _create_test_plan_and_approval(session)
        result = service.reject(session, approval.id, reason="Not needed")

    assert result.status == "rejected"


def test_approve_already_approved_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    from storage.db import init_db, reset_engine_for_tests
    reset_engine_for_tests()
    init_db()

    service = ApprovalService()
    with session_scope() as session:
        plan, approval = _create_test_plan_and_approval(session)
        service.approve(session, approval.id)

    import pytest
    with session_scope() as session, pytest.raises(ValueError, match="cannot approve"):
        service.approve(session, approval.id)


def test_token_hash_not_stored_in_plaintext(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    from storage.db import init_db, reset_engine_for_tests
    reset_engine_for_tests()
    init_db()

    service = ApprovalService()
    with session_scope() as session:
        plan, approval = _create_test_plan_and_approval(session)
        result = service.approve(session, approval.id)

    # Verify token hash is stored, not plaintext
    with session_scope() as session:
        a = session.get(Approval, approval.id)
        assert a.approval_token_hash is not None
        assert a.approval_token_hash.startswith("sha256:")
        assert a.approval_token_hash != result.approval_token
