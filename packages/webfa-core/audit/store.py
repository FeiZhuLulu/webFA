"""Audit Service: query and manage audit events."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from schemas.audit import AuditEventRead, AuditListResponse
from storage.models import AuditEvent

# Sensitive fields that must be redacted from audit payloads
SENSITIVE_PATTERNS = [
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"authorization", re.IGNORECASE),
    re.compile(r"private.?key", re.IGNORECASE),
    re.compile(r"credential", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
]


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove sensitive fields from audit payload."""
    redacted: dict[str, Any] = {}
    for key, value in payload.items():
        is_sensitive = any(p.search(key) for p in SENSITIVE_PATTERNS)
        if is_sensitive:
            redacted[key] = "[REDACTED]"
        elif isinstance(value, dict):
            redacted[key] = redact_payload(value)
        else:
            redacted[key] = value
    return redacted


class AuditService:
    def list_events(
        self,
        session: Session,
        workspace_id: str | None = None,
        plan_id: str | None = None,
        execution_id: str | None = None,
    ) -> AuditListResponse:
        stmt = select(AuditEvent).order_by(AuditEvent.created_at.asc())
        if workspace_id:
            stmt = stmt.where(AuditEvent.workspace_id == workspace_id)
        if plan_id:
            stmt = stmt.where(AuditEvent.plan_id == plan_id)
        if execution_id:
            stmt = stmt.where(AuditEvent.execution_id == execution_id)

        rows = session.scalars(stmt).all()
        items = [
            AuditEventRead(
                id=r.id,
                workspace_id=r.workspace_id,
                plan_id=r.plan_id,
                execution_id=r.execution_id,
                event_type=r.event_type,
                event_payload=redact_payload(r.event_payload_json),
                created_at=r.created_at.isoformat() if r.created_at else None,
            )
            for r in rows
        ]
        return AuditListResponse(items=items)
