"""Approval schemas for request/response."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from schemas.common import ChangedFile, RiskFlag


class ApprovalPayload(BaseModel):
    provider: str
    transaction: str
    target: str
    risk: str
    read_set: list[str] = Field(default_factory=list)
    write_set: list[str] = Field(default_factory=list)
    changed_files: list[ChangedFile] = Field(default_factory=list)
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    proof_types: list[str] = Field(default_factory=list)


class ApprovalRead(BaseModel):
    id: str
    plan_id: str
    status: str
    approval_level: str
    plan_hash: str
    diff_hash: str | None = None
    approval_payload: dict[str, Any] = Field(default_factory=dict)
    expires_at: str | None = None
    created_at: str | None = None


class ApprovalApproveRequest(BaseModel):
    user_note: str | None = None


class ApprovalRejectRequest(BaseModel):
    reason: str | None = None


class ApprovalApproveResult(BaseModel):
    approval_id: str
    plan_id: str
    status: str
    approval_token: str


class ApprovalRejectResult(BaseModel):
    approval_id: str
    plan_id: str
    status: str
