"""Regression test: plan_hash tamper detection (P0-6).

This test ensures that if a plan's input_json is tampered with via SQLite
after approval, execution is rejected with plan_hash mismatch.
"""

from datetime import datetime, timedelta, timezone

from approvals.service import ApprovalService, _hash_token
from execution.engine import ExecutionService
from planner.plan_hash import compute_plan_hash
from schemas.execution import ExecuteRequest
from storage.db import session_scope
from storage.models import Approval, Plan, Workspace, new_id


def test_execute_rejects_tampered_plan_hash_after_approval(tmp_path, monkeypatch):
    """P0-6 regression: tamper plan.input_json after approve, execute must fail."""
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    from storage.db import init_db, reset_engine_for_tests
    reset_engine_for_tests()
    init_db()

    # Create plan and approval via services
    with session_scope() as session:
        workspace = Workspace(id=new_id("workspace"), title="Test", status="active")
        session.add(workspace)

        original_input = {"owner": "test", "repo": "repo", "issue_number": 1, "task_description": "Fix."}
        target = {"provider": "mock", "repo": "test/repo"}
        steps = [{"step_name": "mock.branch.create", "capability_id": "mock.branch.create"}]

        plan_hash = compute_plan_hash(
            transaction_id="mock.patch_and_open_pr",
            input_json=original_input,
            target_json=target,
            steps_json=steps,
            risk="high",
        )

        plan = Plan(
            id=new_id("plan"),
            workspace_id=workspace.id,
            transaction_id="mock.patch_and_open_pr",
            input_json=original_input,
            target_json=target,
            steps_json=steps,
            risk="high",
            plan_hash=plan_hash,
            status="approved",
        )
        session.add(plan)

        approval = Approval(
            id=new_id("approval"),
            plan_id=plan.id,
            approval_level="user",
            approval_payload_json={"provider": "mock"},
            approval_token_hash=_hash_token("valid_token_123"),
            status="approved",
            approved_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        session.add(approval)
        session.flush()
        plan_id = plan.id

    # Tamper: change input_json directly in DB
    with session_scope() as session:
        plan = session.get(Plan, plan_id)
        plan.input_json = {"owner": "attacker", "repo": "evil", "issue_number": 999, "task_description": "tampered"}

    # Try execute with original token — must fail
    exec_service = ExecutionService()
    import pytest
    with session_scope() as session, pytest.raises(ValueError, match="tampered"):
        exec_service.execute(session, ExecuteRequest(
            plan_id=plan_id,
            approval_token="valid_token_123",
        ))
