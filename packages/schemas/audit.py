"""Audit schemas for request/response."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AuditEventRead(BaseModel):
    id: str
    workspace_id: str | None = None
    plan_id: str | None = None
    execution_id: str | None = None
    event_type: str
    event_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None


class AuditListResponse(BaseModel):
    items: list[AuditEventRead] = Field(default_factory=list)
