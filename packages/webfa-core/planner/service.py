"""Plan Service: creates workspaces and plans, computes plan_hash."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from planner.plan_hash import compute_plan_hash
from registry.transaction_registry import TransactionRegistry
from schemas.plan import CreatePlanRequest, PlanRead, PlanStep, PlanTarget
from storage.models import AuditEvent, Plan, Workspace, new_id


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
            status="pending_preview",
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
