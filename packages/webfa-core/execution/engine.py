"""Execution Service: validates approval, runs mock steps, produces execution."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from approvals.service import ApprovalService
from planner.plan_hash import compute_diff_hash
from proof.store import ProofService
from providers.mock.adapter import MockAdapter
from schemas.execution import ExecutionRead, ExecutionStepRead, ExecuteRequest
from storage.models import AuditEvent, Execution, ExecutionStep, Plan, new_id
from verification.engine import VerificationService


# Execution state transitions
VALID_TRANSITIONS: dict[str, list[str]] = {
    "queued": ["running", "failed"],
    "running": ["verifying", "failed"],
    "verifying": ["verified", "failed"],
    "verified": [],
    "failed": [],
}


def can_transition(current: str, target: str) -> bool:
    return target in VALID_TRANSITIONS.get(current, [])


class ExecutionService:
    def __init__(self) -> None:
        self._approval_service = ApprovalService()
        self._mock_adapter = MockAdapter()
        self._verification_service = VerificationService()
        self._proof_service = ProofService()

    def execute(self, session: Session, request: ExecuteRequest) -> ExecutionRead:
        """Execute a plan with an approved approval token."""
        # Check idempotency
        if request.idempotency_key:
            existing = session.scalars(
                select(Execution).where(Execution.idempotency_key == request.idempotency_key)
            ).first()
            if existing:
                return self._to_read(session, existing)

        # Load plan
        plan = session.get(Plan, request.plan_id)
        if plan is None:
            raise ValueError(f"Plan not found: {request.plan_id}")

        # Block plan_only plans (GitHub in P3)
        if plan.status == "plan_only":
            raise ValueError("Execution not available: this transaction is plan-only in P3. GitHub write execution is reserved for Phase 4.")

        # Get diff_hash from target_json
        expected_diff_hash = None
        if plan.target_json:
            expected_diff_hash = plan.target_json.get("diff_hash")

        # Validate approval
        approval = self._approval_service.validate_for_execution(
            session=session,
            plan_id=request.plan_id,
            approval_token=request.approval_token,
            expected_plan_hash=plan.plan_hash or "",
            expected_diff_hash=expected_diff_hash,
        )

        inp = plan.input_json
        owner = inp.get("owner", "mock-owner")
        repo = inp.get("repo", "mock-repo")
        issue_number = inp.get("issue_number", 0)
        task_description = inp.get("task_description", "")
        base_branch = inp.get("base_branch", "main")
        branch_name = f"webfa/issue-{issue_number}-fix"

        # Create execution
        execution = Execution(
            id=new_id("exec"),
            plan_id=plan.id,
            approval_id=approval.id,
            status="queued",
            idempotency_key=request.idempotency_key,
        )
        session.add(execution)
        session.flush()

        # Audit: execution.created
        session.add(AuditEvent(
            id=new_id("audit"),
            workspace_id=plan.workspace_id,
            plan_id=plan.id,
            execution_id=execution.id,
            event_type="execution.created",
            event_payload_json={"execution_id": execution.id},
        ))

        # Transition to running
        execution.status = "running"
        execution.started_at = datetime.now(timezone.utc)
        session.add(AuditEvent(
            id=new_id("audit"),
            workspace_id=plan.workspace_id,
            plan_id=plan.id,
            execution_id=execution.id,
            event_type="execution.started",
            event_payload_json={"execution_id": execution.id},
        ))

        # Execute mock steps
        plan_seed = plan.id
        steps_config = [
            ("mock.branch.create", lambda: self._mock_adapter.create_branch(owner, repo, branch_name, plan_seed)),
            ("mock.commit.create", lambda: self._mock_adapter.create_commit(owner, repo, branch_name, f"Fix #{issue_number}", plan_seed)),
            ("mock.pr.create", lambda: self._mock_adapter.create_pr(owner, repo, branch_name, f"Fix #{issue_number}: {task_description}", plan_seed)),
        ]

        step_results: list[dict[str, Any]] = []
        for step_name, step_fn in steps_config:
            step = ExecutionStep(
                id=new_id("step"),
                execution_id=execution.id,
                step_name=step_name,
                capability_id=step_name,
                status="running",
                started_at=datetime.now(timezone.utc),
            )
            session.add(step)
            session.flush()

            # Audit: step started
            session.add(AuditEvent(
                id=new_id("audit"),
                workspace_id=plan.workspace_id,
                plan_id=plan.id,
                execution_id=execution.id,
                event_type="execution.step.started",
                event_payload_json={"step_name": step_name, "step_id": step.id},
            ))

            try:
                result = step_fn()
                step.output_json = result
                step.status = "succeeded"
                step.finished_at = datetime.now(timezone.utc)
                step_results.append(result)

                # Audit: step succeeded
                session.add(AuditEvent(
                    id=new_id("audit"),
                    workspace_id=plan.workspace_id,
                    plan_id=plan.id,
                    execution_id=execution.id,
                    event_type="execution.step.succeeded",
                    event_payload_json={"step_name": step_name, "step_id": step.id},
                ))
            except Exception as e:
                step.status = "failed"
                step.error_json = {"error": str(e)}
                step.finished_at = datetime.now(timezone.utc)
                execution.status = "failed"
                execution.error_json = {"failed_step": step_name, "error": str(e)}
                execution.finished_at = datetime.now(timezone.utc)

                session.add(AuditEvent(
                    id=new_id("audit"),
                    workspace_id=plan.workspace_id,
                    plan_id=plan.id,
                    execution_id=execution.id,
                    event_type="execution.failed",
                    event_payload_json={"failed_step": step_name, "error": str(e)},
                ))
                session.flush()
                return self._to_read(session, execution)

        # Build result
        mock_diff = self._mock_adapter.generate_diff(owner, repo, issue_number, task_description)
        diff_hash = compute_diff_hash(mock_diff)
        pr_result = step_results[2] if len(step_results) >= 3 else {}
        commit_result = step_results[1] if len(step_results) >= 2 else {}

        result_payload = {
            "pr_url": pr_result.get("url", ""),
            "pr_number": pr_result.get("number", 0),
            "commit_sha": commit_result.get("sha", ""),
            "branch": branch_name,
            "diff_hash": diff_hash,
        }

        # Transition to verifying
        execution.status = "verifying"
        session.add(AuditEvent(
            id=new_id("audit"),
            workspace_id=plan.workspace_id,
            plan_id=plan.id,
            execution_id=execution.id,
            event_type="execution.verifying",
            event_payload_json={"execution_id": execution.id},
        ))

        # Verify
        verification = self._verification_service.verify(
            execution_result=result_payload,
            expected_diff_hash=expected_diff_hash,
        )

        if not verification.passed:
            execution.status = "failed"
            execution.error_json = {"verification": verification.model_dump()}
            execution.finished_at = datetime.now(timezone.utc)
            session.add(AuditEvent(
                id=new_id("audit"),
                workspace_id=plan.workspace_id,
                plan_id=plan.id,
                execution_id=execution.id,
                event_type="execution.failed",
                event_payload_json={"reason": "verification_failed", "checks": [c.model_dump() for c in verification.checks]},
            ))
            session.flush()
            return self._to_read(session, execution)

        # Generate proof
        pr_result = step_results[2] if len(step_results) >= 3 else {}
        proof_read = self._proof_service.create_proof(
            session=session,
            execution_id=execution.id,
            provider="mock",
            transaction_id=plan.transaction_id,
            plan_id=plan.id,
            resource_type="mock_pull_request",
            resource_id=f"mock_pr_{pr_result.get('number', 0)}",
            resource_url=pr_result.get("url"),
            plan_hash=plan.plan_hash or "",
            diff_hash=diff_hash,
            verification=verification,
            workspace_id=plan.workspace_id,
        )

        # Transition to verified
        execution.status = "verified"
        execution.finished_at = datetime.now(timezone.utc)
        session.add(AuditEvent(
            id=new_id("audit"),
            workspace_id=plan.workspace_id,
            plan_id=plan.id,
            execution_id=execution.id,
            event_type="execution.verified",
            event_payload_json={"execution_id": execution.id, "result": result_payload},
        ))

        # Update plan status
        plan.status = "verified"

        session.flush()

        return ExecutionRead(
            id=execution.id,
            plan_id=plan.id,
            approval_id=approval.id,
            status="verified",
            idempotency_key=execution.idempotency_key,
            steps=[
                ExecutionStepRead(step_name=s.step_name, status=s.status)
                for s in execution.steps
            ],
            result=result_payload,
            proof_id=proof_read.id,
            started_at=execution.started_at.isoformat() if execution.started_at else None,
            finished_at=execution.finished_at.isoformat() if execution.finished_at else None,
            created_at=execution.created_at.isoformat() if execution.created_at else None,
        )

    def get_execution(self, session: Session, execution_id: str) -> ExecutionRead | None:
        execution = session.get(Execution, execution_id)
        if execution is None:
            return None
        return self._to_read(session, execution)

    def _to_read(self, session: Session, execution: Execution) -> ExecutionRead:
        steps = [
            ExecutionStepRead(
                step_name=s.step_name,
                capability_id=s.capability_id,
                status=s.status,
                input_json=s.input_json,
                output_json=s.output_json,
                error_json=s.error_json,
                started_at=s.started_at.isoformat() if s.started_at else None,
                finished_at=s.finished_at.isoformat() if s.finished_at else None,
            )
            for s in execution.steps
        ]

        # Build result from steps
        result: dict[str, Any] = {}
        for s in execution.steps:
            if s.output_json and "url" in s.output_json:
                result["pr_url"] = s.output_json["url"]
            if s.output_json and "sha" in s.output_json:
                result["commit_sha"] = s.output_json["sha"]

        # Find proof_id if exists
        proof_id = None
        if execution.proofs:
            proof_id = execution.proofs[0].id

        return ExecutionRead(
            id=execution.id,
            plan_id=execution.plan_id,
            approval_id=execution.approval_id,
            status=execution.status,
            idempotency_key=execution.idempotency_key,
            steps=steps,
            result=result,
            proof_id=proof_id,
            started_at=execution.started_at.isoformat() if execution.started_at else None,
            finished_at=execution.finished_at.isoformat() if execution.finished_at else None,
            created_at=execution.created_at.isoformat() if execution.created_at else None,
        )
