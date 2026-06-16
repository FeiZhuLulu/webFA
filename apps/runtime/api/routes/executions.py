"""REST API: Execution endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from execution.engine import ExecutionService
from schemas.execution import ExecuteRequest
from storage.db import session_scope

router = APIRouter()
_service = ExecutionService()


@router.post("/executions", status_code=201)
def create_execution(body: ExecuteRequest):
    with session_scope() as session:
        try:
            execution = _service.execute(session, body)
        except ValueError as e:
            detail = str(e)
            if "not found" in detail.lower():
                raise HTTPException(status_code=404, detail=detail)
            if "approval" in detail.lower() or "token" in detail.lower() or "expired" in detail.lower() or "mismatch" in detail.lower():
                raise HTTPException(status_code=403, detail=detail)
            raise HTTPException(status_code=400, detail=detail)
        return execution.model_dump(mode="json")


@router.get("/executions/{execution_id}")
def get_execution(execution_id: str):
    with session_scope() as session:
        execution = _service.get_execution(session, execution_id)
        if execution is None:
            raise HTTPException(status_code=404, detail="Execution not found")
        return execution.model_dump(mode="json")
