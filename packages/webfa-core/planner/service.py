"""Plan Service: creates workspaces and plans, computes plan_hash."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from planner.plan_hash import compute_diff_hash, compute_plan_hash
from policy.engine import PolicyEngine
from registry.transaction_registry import TransactionRegistry
from schemas.approval import ApprovalPayload
from schemas.common import ChangedFile
from schemas.plan import CreatePlanRequest, PlanPreview, PlanRead, PlanStep, PlanTarget, PreviewDetail
from storage.models import Approval, AuditEvent, Plan, Workspace, new_id


class PlanService:
    def __init__(self, registry: TransactionRegistry) -> None:
        self._registry = registry

    def create_plan(self, session: Session, request: CreatePlanRequest) -> PlanRead:
        # Look up transaction definition
        txn_def = self._registry.get(request.transaction_id)
        if txn_def is None:
            raise ValueError(f"Unknown transaction: {request.transaction_id}")

        # Derive target from input
        inp = request.input
        target = PlanTarget(
            provider=txn_def.provider,
            repo=f"{inp.get('owner', 'unknown')}/{inp.get('repo', 'unknown')}",
        )

        # Generate steps from required_capabilities
        steps = [
            PlanStep(
                step_name=cap,
                capability_id=cap,
                description=f"Execute {cap}",
            )
            for cap in txn_def.required_capabilities
        ]

        # Compute plan_hash
        steps_json = [s.model_dump() for s in steps]
        plan_hash = compute_plan_hash(
            transaction_id=request.transaction_id,
            input_json=inp,
            target_json=target.model_dump(),
            steps_json=steps_json,
            risk=txn_def.risk,
        )

        # Create workspace
        workspace = Workspace(
            id=new_id("workspace"),
            title=f"{txn_def.name}: {inp.get('task_description', '')[:100]}",
            user_goal=inp.get("task_description", ""),
            status="active",
        )
        session.add(workspace)

        # Determine plan status: GitHub transactions are plan-only in P3
        plan_status = "pending_preview"
        if txn_def.provider == "github":
            plan_status = "plan_only"

        # Create plan
        plan = Plan(
            id=new_id("plan"),
            workspace_id=workspace.id,
            transaction_id=request.transaction_id,
            input_json=inp,
            target_json=target.model_dump(),
            steps_json=steps_json,
            risk=txn_def.risk,
            plan_hash=plan_hash,
            status=plan_status,
        )
        session.add(plan)

        # Audit: workspace.created
        session.add(AuditEvent(
            id=new_id("audit"),
            workspace_id=workspace.id,
            event_type="workspace.created",
            event_payload_json={"workspace_id": workspace.id, "title": workspace.title},
        ))

        # Audit: plan.created
        session.add(AuditEvent(
            id=new_id("audit"),
            workspace_id=workspace.id,
            plan_id=plan.id,
            event_type="plan.created",
            event_payload_json={
                "plan_id": plan.id,
                "transaction_id": plan.transaction_id,
                "risk": plan.risk,
                "plan_hash": plan.plan_hash,
            },
        ))

        session.flush()

        return PlanRead(
            id=plan.id,
            workspace_id=workspace.id,
            transaction_id=plan.transaction_id,
            input=plan.input_json,
            target=target,
            steps=steps,
            risk=plan.risk,
            plan_hash=plan.plan_hash,
            status=plan.status,
            created_at=plan.created_at.isoformat() if plan.created_at else None,
            updated_at=plan.updated_at.isoformat() if plan.updated_at else None,
        )

    def preview_plan(self, session: Session, plan_id: str) -> PlanPreview:
        """Generate mock preview, run policy check, create approval."""
        plan = session.get(Plan, plan_id)
        if plan is None:
            raise ValueError(f"Plan not found: {plan_id}")
        if plan.status not in ("pending_preview", "plan_only"):
            raise ValueError(f"Plan status is '{plan.status}', expected 'pending_preview' or 'plan_only'")

        txn_def = self._registry.get(plan.transaction_id)
        if txn_def is None:
            raise ValueError(f"Unknown transaction: {plan.transaction_id}")

        inp = plan.input_json
        target = plan.target_json or {}

        # Generate mock diff
        mock_diff_text = self._generate_mock_diff(inp)
        diff_hash = compute_diff_hash(mock_diff_text)

        changed_files = [ChangedFile(path="src/example.py", additions=12, deletions=3)]

        # Policy check
        policy_engine = PolicyEngine()
        policy_result = policy_engine.check(
            transaction_id=plan.transaction_id,
            provider=txn_def.provider,
            risk=plan.risk,
            changed_files=changed_files,
            diff_text=mock_diff_text,
            blocked_paths=inp.get("blocked_paths"),
        )

        if not policy_result.allowed:
            plan.status = "failed"
            session.add(AuditEvent(
                id=new_id("audit"),
                workspace_id=plan.workspace_id,
                plan_id=plan.id,
                event_type="policy.blocked",
                event_payload_json={"blocked": [v.model_dump() for v in policy_result.blocked]},
            ))
            session.flush()
            raise ValueError(f"Policy blocked: {[v.message for v in policy_result.blocked]}")

        # Plan-only: GitHub transactions in P3 are read-only
        if plan.status == "plan_only":
            session.add(AuditEvent(
                id=new_id("audit"),
                workspace_id=plan.workspace_id,
                plan_id=plan.id,
                event_type="github.plan_only.previewed",
                event_payload_json={"plan_id": plan.id, "provider": txn_def.provider},
            ))
            session.flush()

            return PlanPreview(
                plan_id=plan.id,
                status="plan_only_preview",
                risk=plan.risk,
                approval_required=False,
                approval_id=None,
                plan_hash=plan.plan_hash or "",
                diff_hash=diff_hash,
                policy=policy_result,
                preview=PreviewDetail(
                    provider=txn_def.provider,
                    target=target.get("repo", "unknown"),
                    read_set=txn_def.read_set,
                    write_set=txn_def.write_set,
                    changed_files=changed_files,
                    diff_summary="+12 -3",
                    diff_text=mock_diff_text,
                    risk_flags=policy_result.risk_flags,
                ),
            )

        # Create approval
        approval_payload = ApprovalPayload(
            provider=txn_def.provider,
            transaction=plan.transaction_id,
            target=target.get("repo", "unknown"),
            risk=plan.risk,
            read_set=txn_def.read_set,
            write_set=txn_def.write_set,
            changed_files=changed_files,
            risk_flags=policy_result.risk_flags,
            proof_types=txn_def.proof_types,
        )

        now = datetime.now(timezone.utc)
        approval = Approval(
            id=new_id("approval"),
            plan_id=plan.id,
            approval_level="user",
            approval_payload_json=approval_payload.model_dump(mode="json"),
            status="pending",
            expires_at=now + timedelta(minutes=30),
        )
        session.add(approval)

        # Update plan status
        plan.status = "pending_approval"

        # Audit events
        session.add(AuditEvent(
            id=new_id("audit"),
            workspace_id=plan.workspace_id,
            plan_id=plan.id,
            event_type="plan.previewed",
            event_payload_json={"plan_id": plan.id, "diff_hash": diff_hash},
        ))
        session.add(AuditEvent(
            id=new_id("audit"),
            workspace_id=plan.workspace_id,
            plan_id=plan.id,
            event_type="policy.checked",
            event_payload_json={
                "allowed": policy_result.allowed,
                "approval_required": policy_result.approval_required,
                "risk_flags": [f.model_dump() for f in policy_result.risk_flags],
            },
        ))
        session.add(AuditEvent(
            id=new_id("audit"),
            workspace_id=plan.workspace_id,
            plan_id=plan.id,
            event_type="approval.created",
            event_payload_json={"approval_id": approval.id, "status": "pending"},
        ))

        session.flush()

        # Store diff_hash on plan for later validation
        # (We store it in target_json for simplicity in Phase 1)
        if plan.target_json:
            plan.target_json["diff_hash"] = diff_hash

        return PlanPreview(
            plan_id=plan.id,
            status="pending_approval",
            risk=plan.risk,
            approval_required=True,
            approval_id=approval.id,
            plan_hash=plan.plan_hash or "",
            diff_hash=diff_hash,
            policy=policy_result,
            preview=PreviewDetail(
                provider=txn_def.provider,
                target=target.get("repo", "unknown"),
                read_set=txn_def.read_set,
                write_set=txn_def.write_set,
                changed_files=changed_files,
                diff_summary="+12 -3",
                diff_text=mock_diff_text,
                risk_flags=policy_result.risk_flags,
            ),
        )

    def _generate_mock_diff(self, inp: dict[str, Any]) -> str:
        """Generate a deterministic mock diff based on input."""
        owner = inp.get("owner", "unknown")
        repo = inp.get("repo", "unknown")
        issue = inp.get("issue_number", 0)
        return (
            f"--- a/src/example.py\n"
            f"+++ b/src/example.py\n"
            f"@@ -1,5 +1,14 @@\n"
            f" # {owner}/{repo} - fix for issue #{issue}\n"
            f"+import logging\n"
            f"+\n"
            f"+logger = logging.getLogger(__name__)\n"
            f"+\n"
            f" def main():\n"
            f"-    pass\n"
            f"+    logger.info('Fix applied')\n"
            f"+    return True\n"
            f"+\n"
            f"+\n"
            f"+def test_main():\n"
            f"+    assert main() is True\n"
        )

    def get_plan(self, session: Session, plan_id: str) -> PlanRead | None:
        plan = session.get(Plan, plan_id)
        if plan is None:
            return None

        target = PlanTarget(**plan.target_json) if plan.target_json else None
        steps = [PlanStep(**s) for s in (plan.steps_json or [])]

        return PlanRead(
            id=plan.id,
            workspace_id=plan.workspace_id or "",
            transaction_id=plan.transaction_id,
            input=plan.input_json,
            target=target,
            steps=steps,
            risk=plan.risk,
            plan_hash=plan.plan_hash or "",
            status=plan.status,
            created_at=plan.created_at.isoformat() if plan.created_at else None,
            updated_at=plan.updated_at.isoformat() if plan.updated_at else None,
        )
