"""Approval Service: approve, reject, validate for execution."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from planner.plan_hash import compute_plan_hash
from schemas.approval import ApprovalApproveResult, ApprovalRead, ApprovalRejectResult
from storage.models import Approval, AuditEvent, Plan, new_id


def _generate_approval_token() -> str:
    return "approval_token_" + secrets.token_urlsafe(32)


def _hash_token(token: str) -> str:
    return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


class ApprovalService:
    def list_approvals(self, session: Session, status: str | None = None) -> list[ApprovalRead]:
        stmt = select(Approval).order_by(Approval.created_at.desc())
        if status:
            stmt = stmt.where(Approval.status == status)
        rows = session.scalars(stmt).all()
        return [self._to_read(a) for a in rows]

    def get_approval(self, session: Session, approval_id: str) -> ApprovalRead | None:
        approval = session.get(Approval, approval_id)
        if approval is None:
            return None
        return self._to_read(approval)

    def approve(self, session: Session, approval_id: str, user_note: str | None = None) -> ApprovalApproveResult:
        approval = session.get(Approval, approval_id)
        if approval is None:
            raise ValueError(f"Approval not found: {approval_id}")
        if approval.status != "pending":
            raise ValueError(f"Approval status is '{approval.status}', cannot approve")

        # Check expiry
        now = datetime.now(timezone.utc)
        if approval.expires_at and approval.expires_at.replace(tzinfo=timezone.utc) < now:
            approval.status = "expired"
            session.flush()
            raise ValueError("Approval has expired")

        # Generate token
        token = _generate_approval_token()
        approval.approval_token_hash = _hash_token(token)
        approval.status = "approved"
        approval.approved_at = now

        # Update plan status
        plan = session.get(Plan, approval.plan_id)
        if plan:
            plan.status = "approved"

        # Audit
        session.add(AuditEvent(
            id=new_id("audit"),
            workspace_id=plan.workspace_id if plan else None,
            plan_id=approval.plan_id,
            event_type="approval.approved",
            event_payload_json={
                "approval_id": approval.id,
                "user_note": user_note,
            },
        ))

        session.flush()

        return ApprovalApproveResult(
            approval_id=approval.id,
            plan_id=approval.plan_id,
            status="approved",
            approval_token=token,
        )

    def reject(self, session: Session, approval_id: str, reason: str | None = None) -> ApprovalRejectResult:
        approval = session.get(Approval, approval_id)
        if approval is None:
            raise ValueError(f"Approval not found: {approval_id}")
        if approval.status != "pending":
            raise ValueError(f"Approval status is '{approval.status}', cannot reject")

        approval.status = "rejected"
        approval.rejected_at = datetime.now(timezone.utc)

        # Update plan status
        plan = session.get(Plan, approval.plan_id)
        if plan:
            plan.status = "rejected"

        # Audit
        session.add(AuditEvent(
            id=new_id("audit"),
            workspace_id=plan.workspace_id if plan else None,
            plan_id=approval.plan_id,
            event_type="approval.rejected",
            event_payload_json={
                "approval_id": approval.id,
                "reason": reason,
            },
        ))

        session.flush()

        return ApprovalRejectResult(
            approval_id=approval.id,
            plan_id=approval.plan_id,
            status="rejected",
        )

    def validate_for_execution(
        self,
        session: Session,
        plan_id: str,
        approval_token: str,
        expected_plan_hash: str,
        expected_diff_hash: str | None = None,
    ) -> Approval:
        """Validate approval is usable for execution. Returns Approval or raises."""
        # Find approval for this plan
        stmt = select(Approval).where(Approval.plan_id == plan_id, Approval.status == "approved")
        approval = session.scalars(stmt).first()
        if approval is None:
            raise ValueError("No approved approval found for this plan")

        # Check token hash
        if approval.approval_token_hash != _hash_token(approval_token):
            raise ValueError("Invalid approval token")

        # Check expiry
        now = datetime.now(timezone.utc)
        if approval.expires_at and approval.expires_at.replace(tzinfo=timezone.utc) < now:
            raise ValueError("Approval has expired")

        # Check plan_hash: recompute from current fields and compare against stored hash
        plan = session.get(Plan, plan_id)
        if plan:
            recomputed_hash = compute_plan_hash(
                transaction_id=plan.transaction_id,
                input_json=plan.input_json,
                target_json=plan.target_json or {},
                steps_json=plan.steps_json or [],
                risk=plan.risk,
            )
            if recomputed_hash != plan.plan_hash:
                raise ValueError("Plan has been tampered with (plan_hash mismatch)")
            if plan.plan_hash != expected_plan_hash:
                raise ValueError("Plan hash mismatch")

        # Check diff_hash if stored
        if expected_diff_hash and plan and plan.target_json:
            stored_diff_hash = plan.target_json.get("diff_hash")
            if stored_diff_hash and stored_diff_hash != expected_diff_hash:
                raise ValueError("Diff hash mismatch")

        return approval

    def _to_read(self, a: Approval) -> ApprovalRead:
        return ApprovalRead(
            id=a.id,
            plan_id=a.plan_id,
            status=a.status,
            approval_level=a.approval_level,
            plan_hash="",
            diff_hash=None,
            approval_payload=a.approval_payload_json,
            expires_at=a.expires_at.isoformat() if a.expires_at else None,
            created_at=a.created_at.isoformat() if a.created_at else None,
        )
