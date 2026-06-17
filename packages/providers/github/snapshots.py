"""Resource snapshot creation with content_hash and taint tracking."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from storage.models import ResourceSnapshot, new_id


def canonical_json_hash(payload: dict[str, Any]) -> str:
    """Compute sha256 of canonical JSON."""
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_hash(content: str) -> str:
    """Compute sha256 of raw content string."""
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def create_snapshot(
    session: Session,
    workspace_id: str | None,
    provider: str,
    resource_type: str,
    resource_id: str,
    snapshot_data: dict[str, Any],
    resource_url: str | None = None,
    taint_level: str = "external",
    etag: str | None = None,
    last_modified: str | None = None,
) -> ResourceSnapshot:
    """Create a resource snapshot with content hash."""
    # Compute hash based on resource type
    if resource_type == "github.file":
        raw_content = snapshot_data.get("content", "")
        c_hash = content_hash(raw_content)
    else:
        c_hash = canonical_json_hash(snapshot_data)

    snap = ResourceSnapshot(
        id=new_id("snap"),
        workspace_id=workspace_id,
        provider=provider,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_url=resource_url,
        snapshot_json=snapshot_data,
        content_hash=c_hash,
        taint_level=taint_level,
        etag=etag,
        last_modified=last_modified,
        fetched_at=datetime.now(timezone.utc),
    )
    session.add(snap)
    session.flush()
    return snap
