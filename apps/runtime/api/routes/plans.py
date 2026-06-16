"""REST API: Plan endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from planner.service import PlanService
from schemas.plan import CreatePlanRequest
from storage.db import session_scope

router = APIRouter()


def _get_plan_service(request: Request) -> PlanService:
    return PlanService(registry=request.app.state.transaction_registry)


@router.post("/plans", status_code=201)
def create_plan(body: CreatePlanRequest, request: Request):
    service = _get_plan_service(request)
    with session_scope() as session:
        try:
            plan = service.create_plan(session, body)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return JSONResponse(status_code=201, content=plan.model_dump(mode="json"))


@router.get("/plans/{plan_id}")
def get_plan(plan_id: str, request: Request):
    service = _get_plan_service(request)
    with session_scope() as session:
        plan = service.get_plan(session, plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="Plan not found")
        return plan.model_dump(mode="json")
