"""Execution schemas for request/response."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ExecuteRequest(BaseModel):
    plan_id: str
    approval_token: str
    idempotency_key: str | None = None


class ExecutionStepRead(BaseModel):
    step_name: str
    capability_id: str | None = None
    status: str
    input_json: dict[str, Any] | None = None
    output_json: dict[str, Any] | None = None
    error_json: dict[str, Any] | None = None
    started_at: str | None = None
    finished_at: str | None = None


class ExecutionRead(BaseModel):
    id: str
    plan_id: str
    approval_id: str | None = None
    status: str
    idempotency_key: str | None = None
    steps: list[ExecutionStepRead] = Field(default_factory=list)
    result: dict[str, Any] = Field(default_factory=dict)
    proof_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    created_at: str | None = None
