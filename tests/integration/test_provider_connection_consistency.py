from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import apps.runtime.api.routes.provider_connections as provider_routes
from apps.runtime.main import create_app
from providers.github.auth import GitHubAuth
from schemas.github import GitHubConnectionTestResult, GitHubViewer
from storage.credential_store import CredentialStore
from storage.db import reset_engine_for_tests, session_scope
from storage.models import AuditEvent, ProviderConnection


CONTROL_TOKEN = "provider-consistency-control-token"
CONTROL_HEADERS = {"X-WebFA-Visualizer-Token": CONTROL_TOKEN}


def _connected_result(_auth: GitHubAuth) -> GitHubConnectionTestResult:
    return GitHubConnectionTestResult(
        status="connected",
        viewer=GitHubViewer(login="webfa-test", id=17, type="User"),
        message="Connected as webfa-test",
    )


def _set_connected_metadata() -> None:
    with session_scope() as session:
        connections = session.scalars(
            select(ProviderConnection).where(ProviderConnection.provider == "github")
        ).all()
        connection = connections[0]
        assert connection is not None
        assert len(connections) == 1
        connection.status = "connected"
        connection.auth_mode = "fine_grained_pat"
        connection.credential_ref = "github:default"


def _failing_session_scope(real_scope):
    @contextmanager
    def failing_scope():
        with real_scope() as session:
            yield session
            raise RuntimeError("forced provider metadata failure")

    return failing_scope


def test_provider_connection_lifecycle_keeps_token_out_of_responses(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_VISUALIZER_CONTROL_TOKEN", CONTROL_TOKEN)
    monkeypatch.setattr(GitHubAuth, "test_connection", _connected_result)
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        connected = client.post(
            "/v1/providers/github/connect",
            headers=CONTROL_HEADERS,
            json={"token": "new-provider-secret", "resource_scope": {"owner": "webfa"}},
        )
        status = client.get("/v1/providers/github", headers=CONTROL_HEADERS)
        disconnected = client.delete(
            "/v1/providers/github/disconnect",
            headers=CONTROL_HEADERS,
        )

    assert connected.status_code == 200
    assert connected.json()["status"] == "connected"
    assert connected.json()["token_stored"] is True
    assert "new-provider-secret" not in connected.text
    assert status.json()["status"] == "connected"
    assert disconnected.json() == {"provider": "github", "status": "disconnected"}
    assert CredentialStore().exists("github:default") is False

    with session_scope() as session:
        connections = session.scalars(
            select(ProviderConnection).where(ProviderConnection.provider == "github")
        ).all()
        connection = connections[0]
        events = session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type.in_(
                    ["provider.github.connected", "provider.github.disconnected"]
                )
            )
        ).all()
        assert connection is not None
        assert connection.status == "disconnected"
        assert connection.credential_ref is None
        assert len(connections) == 1
        assert len(events) == 2


def test_connect_restores_previous_token_when_metadata_commit_fails(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_VISUALIZER_CONTROL_TOKEN", CONTROL_TOKEN)
    monkeypatch.setattr(GitHubAuth, "test_connection", _connected_result)
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        store = CredentialStore()
        store.put("github", "previous-provider-secret")
        _set_connected_metadata()
        real_scope = provider_routes.session_scope
        monkeypatch.setattr(
            provider_routes,
            "session_scope",
            _failing_session_scope(real_scope),
        )

        with pytest.raises(RuntimeError, match="forced provider metadata failure"):
            client.post(
                "/v1/providers/github/connect",
                headers=CONTROL_HEADERS,
                json={"token": "replacement-provider-secret", "resource_scope": {}},
            )

    assert CredentialStore().get("github:default") == "previous-provider-secret"
    with session_scope() as session:
        connection = session.scalar(
            select(ProviderConnection).where(ProviderConnection.provider == "github")
        )
        assert connection is not None
        assert connection.status == "connected"
        assert connection.credential_ref == "github:default"


def test_disconnect_restores_token_when_metadata_commit_fails(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_VISUALIZER_CONTROL_TOKEN", CONTROL_TOKEN)
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        store = CredentialStore()
        store.put("github", "connected-provider-secret")
        _set_connected_metadata()
        real_scope = provider_routes.session_scope
        monkeypatch.setattr(
            provider_routes,
            "session_scope",
            _failing_session_scope(real_scope),
        )

        with pytest.raises(RuntimeError, match="forced provider metadata failure"):
            client.delete(
                "/v1/providers/github/disconnect",
                headers=CONTROL_HEADERS,
            )

    assert CredentialStore().get("github:default") == "connected-provider-secret"
    with session_scope() as session:
        connection = session.scalar(
            select(ProviderConnection).where(ProviderConnection.provider == "github")
        )
        assert connection is not None
        assert connection.status == "connected"
        assert connection.credential_ref == "github:default"
