"""REST API: GitHub provider connection endpoints."""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.runtime.api.visualizer_control import require_visualizer_control
from providers.github.auth import GitHubAuth
from schemas.github import GitHubConnectionRequest
from storage.credential_store import CredentialStore, CredentialStoreError
from storage.db import session_scope
from storage.models import ProviderConnection, AuditEvent, new_id

router = APIRouter(
    tags=["provider-connections"],
    dependencies=[Depends(require_visualizer_control)],
)
_PROVIDER_CONNECTION_LOCK = threading.RLock()


def _get_auth() -> GitHubAuth:
    return GitHubAuth(CredentialStore())


def _get_stored_token(auth: GitHubAuth) -> str | None:
    try:
        return auth.get_token()
    except FileNotFoundError:
        return None


def _get_github_connection(session: Session) -> ProviderConnection | None:
    return session.scalar(
        select(ProviderConnection).where(ProviderConnection.provider == "github")
    )


def _restore_stored_token(auth: GitHubAuth, previous_token: str | None) -> None:
    try:
        if previous_token is None:
            auth.disconnect()
        else:
            auth.connect(previous_token)
    except Exception as exc:
        raise CredentialStoreError("GitHub credential rollback failed") from exc


@router.post("/providers/github/connect")
def github_connect(body: GitHubConnectionRequest):
    with _PROVIDER_CONNECTION_LOCK:
        auth = _get_auth()
        previous_token = _get_stored_token(auth)
        credential_ref = auth.connect(body.token, body.resource_scope)

        try:
            test_result = auth.test_connection()

            with session_scope() as session:
                conn = _get_github_connection(session)
                if conn is None:
                    conn = ProviderConnection(provider="github", id="conn_github_default")
                    session.add(conn)
                conn.auth_mode = "fine_grained_pat"
                conn.credential_ref = credential_ref
                conn.status = test_result.status
                conn.last_verified_at = (
                    datetime.now(timezone.utc) if test_result.status == "connected" else None
                )
                if body.resource_scope:
                    conn.resource_scope_json = body.resource_scope

                session.add(AuditEvent(
                    id=new_id("audit"),
                    event_type=(
                        "provider.github.connected"
                        if test_result.status == "connected"
                        else "provider.github.connection_failed"
                    ),
                    event_payload_json={"provider": "github", "status": test_result.status},
                ))
        except Exception:
            _restore_stored_token(auth, previous_token)
            raise

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
    with _PROVIDER_CONNECTION_LOCK:
        auth = _get_auth()
        result = auth.test_connection()

        with session_scope() as session:
            conn = _get_github_connection(session)
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
    with _PROVIDER_CONNECTION_LOCK:
        auth = _get_auth()
        previous_token = _get_stored_token(auth)
        auth.disconnect()

        try:
            with session_scope() as session:
                conn = _get_github_connection(session)
                if conn:
                    conn.status = "disconnected"
                    conn.credential_ref = None
                    conn.last_verified_at = None

                session.add(AuditEvent(
                    id=new_id("audit"),
                    event_type="provider.github.disconnected",
                    event_payload_json={"provider": "github"},
                ))
        except Exception:
            _restore_stored_token(auth, previous_token)
            raise

    return {"provider": "github", "status": "disconnected"}


@router.get("/providers/github")
def github_status():
    with _PROVIDER_CONNECTION_LOCK:
        with session_scope() as session:
            conn = _get_github_connection(session)
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
