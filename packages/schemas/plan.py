"""Plan schemas for request/response."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from schemas.common import ChangedFile, PolicyResult, RiskFlag


class CreatePlanRequest(BaseModel):
    transaction_id: str
    input: dict[str, Any] = Field(default_factory=dict)


class PlanTarget(BaseModel):
    provider: str
    repo: str | None = None
    resource: str | None = None


class PlanStep(BaseModel):
    step_name: str
    capability_id: str
    description: str = ""


class PlanRead(BaseModel):
    id: str
    workspace_id: str
    transaction_id: str
    input: dict[str, Any] = Field(default_factory=dict)
    target: PlanTarget | None = None
    steps: list[PlanStep] = Field(default_factory=list)
    risk: str
    plan_hash: str
    status: str
    created_at: str | None = None
    updated_at: str | None = None


class PreviewDetail(BaseModel):
    provider: str
    target: str
    read_set: list[str] = Field(default_factory=list)
    write_set: list[str] = Field(default_factory=list)
    changed_files: list[ChangedFile] = Field(default_factory=list)
    diff_summary: str = ""
    diff_text: str = ""
    risk_flags: list[RiskFlag] = Field(default_factory=list)


class PlanPreview(BaseModel):
    plan_id: str
    status: str
    risk: str
    approval_required: bool
    approval_id: str | None = None
    plan_hash: str
    diff_hash: str | None = None
    policy: PolicyResult | None = None
    preview: PreviewDetail | None = None
