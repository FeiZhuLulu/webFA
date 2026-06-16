"""REST API: Audit endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from audit.store import AuditService
from storage.db import session_scope

router = APIRouter()
_service = AuditService()


@router.get("/audits")
def list_audits(
    workspace_id: str | None = None,
    plan_id: str | None = None,
    execution_id: str | None = None,
):
    with session_scope() as session:
        result = _service.list_events(
            session,
            workspace_id=workspace_id,
            plan_id=plan_id,
            execution_id=execution_id,
        )
        return result.model_dump(mode="json")
