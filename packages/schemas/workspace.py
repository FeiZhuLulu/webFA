"""Workspace schemas for request/response."""

from __future__ import annotations

from pydantic import BaseModel


class WorkspaceRead(BaseModel):
    id: str
    title: str
    user_goal: str | None = None
    status: str
    context_summary: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
