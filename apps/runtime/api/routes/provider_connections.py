"""REST API: GitHub provider connection endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from providers.github.auth import GitHubAuth, redact_tokens
from schemas.github import GitHubConnectionRequest
from storage.credential_store import CredentialStore
from storage.db import session_scope
from storage.models import ProviderConnection, AuditEvent, new_id

router = APIRouter()


def _get_auth() -> GitHubAuth:
    return GitHubAuth(CredentialStore())


@router.post("/providers/github/connect")
def github_connect(body: GitHubConnectionRequest):
    auth = _get_auth()
    credential_ref = auth.connect(body.token, body.resource_scope)

    # Test connection
    test_result = auth.test_connection()

    with session_scope() as session:
        conn = session.get(ProviderConnection, "github")
        if conn is None:
            conn = ProviderConnection(provider="github", id="conn_github_default")
            session.add(conn)
        conn.auth_mode = "fine_grained_pat"
        conn.credential_ref = credential_ref
        conn.status = test_result.status
        conn.last_verified_at = datetime.now(timezone.utc) if test_result.status == "connected" else None
        if body.resource_scope:
            conn.resource_scope_json = body.resource_scope

        session.add(AuditEvent(
            id=new_id("audit"),
            event_type="provider.github.connected" if test_result.status == "connected" else "provider.github.connection_failed",
            event_payload_json={"provider": "github", "status": test_result.status},
        ))

    return {
        "provider": "github",
        "status": test_result.status,
        "auth_mode": "fine_grained_pat",
        "credential_ref": credential_ref,
        "last_verified_at": datetime.now(timezone.utc).isoformat() if test_result.status == "connected" else None,
        "token_stored": True,
        "message": test_result.message,
    }


@router.post("/providers/github/test")
def github_test():
    auth = _get_auth()
    result = auth.test_connection()

    with session_scope() as session:
        conn = session.get(ProviderConnection, "github")
        if conn:
            conn.status = result.status
            if result.status == "connected":
                conn.last_verified_at = datetime.now(timezone.utc)

        session.add(AuditEvent(
            id=new_id("audit"),
            event_type="provider.github.tested",
            event_payload_json={"provider": "github", "status": result.status},
        ))

    return result.model_dump(mode="json")


@router.delete("/providers/github/disconnect")
def github_disconnect():
    auth = _get_auth()
    auth.disconnect()

    with session_scope() as session:
        conn = session.get(ProviderConnection, "github")
        if conn:
            conn.status = "disconnected"
            conn.credential_ref = None
            conn.last_verified_at = None

        session.add(AuditEvent(
            id=new_id("audit"),
            event_type="provider.github.disconnected",
            event_payload_json={"provider": "github"},
        ))

    return {"provider": "github", "status": "disconnected"}


@router.get("/providers/github")
def github_status():
    with session_scope() as session:
        conn = session.get(ProviderConnection, "github")
        if conn is None:
            return {"provider": "github", "status": "disconnected", "auth_mode": None}
        return {
            "provider": conn.provider,
            "status": conn.status,
            "auth_mode": conn.auth_mode,
            "credential_ref": conn.credential_ref,
            "last_verified_at": conn.last_verified_at.isoformat() if conn.last_verified_at else None,
            "resource_scope": conn.resource_scope_json,
        }
