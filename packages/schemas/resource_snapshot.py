"""Resource snapshot schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ResourceSnapshotRead(BaseModel):
    id: str
    workspace_id: str | None = None
    provider: str
    resource_type: str
    resource_id: str
    resource_url: str | None = None
    content_hash: str
    taint_level: str
    fetched_at: str | None = None
    created_at: str | None = None


class ResourceSnapshotList(BaseModel):
    items: list[ResourceSnapshotRead] = Field(default_factory=list)
