"""REST API: Approval endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from approvals.service import ApprovalService
from schemas.approval import ApprovalApproveRequest, ApprovalRejectRequest
from storage.db import session_scope

router = APIRouter()
_service = ApprovalService()


@router.get("/approvals")
def list_approvals(status: str | None = None):
    with session_scope() as session:
        items = _service.list_approvals(session, status=status)
        return {"items": [a.model_dump(mode="json") for a in items]}


@router.get("/approvals/{approval_id}")
def get_approval(approval_id: str):
    with session_scope() as session:
        approval = _service.get_approval(session, approval_id)
        if approval is None:
            raise HTTPException(status_code=404, detail="Approval not found")
        return approval.model_dump(mode="json")


@router.post("/approvals/{approval_id}/approve")
def approve(approval_id: str, body: ApprovalApproveRequest | None = None):
    user_note = body.user_note if body else None
    with session_scope() as session:
        try:
            result = _service.approve(session, approval_id, user_note=user_note)
        except ValueError as e:
            detail = str(e)
            status = 404 if "not found" in detail.lower() else 400
            raise HTTPException(status_code=status, detail=detail)
        return result.model_dump(mode="json")


@router.post("/approvals/{approval_id}/reject")
def reject(approval_id: str, body: ApprovalRejectRequest | None = None):
    reason = body.reason if body else None
    with session_scope() as session:
        try:
            result = _service.reject(session, approval_id, reason=reason)
        except ValueError as e:
            detail = str(e)
            status = 404 if "not found" in detail.lower() else 400
            raise HTTPException(status_code=status, detail=detail)
        return result.model_dump(mode="json")
