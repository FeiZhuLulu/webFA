"""Contract tests: MCP security invariants."""

from pathlib import Path

from fastapi.testclient import TestClient

from apps.runtime.main import create_app
from storage.db import reset_engine_for_tests


def test_mcp_discover_no_credential_leak(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        resp = client.get("/v1/providers")
        providers = resp.json()["providers"]
        for p in providers:
            assert "credential_ref" not in str(p)
            assert "token" not in str(p).lower()


def test_mcp_status_has_no_sensitive_data(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        resp = client.get("/v1/mcp/status")
        body = resp.json()
        body_str = str(body).lower()
        assert "token" not in body_str
        assert "credential" not in body_str
        assert "secret" not in body_str


def test_mcp_config_no_sensitive_data(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        resp = client.get("/v1/mcp/config")
        body_str = str(resp.json()).lower()
        assert "token" not in body_str
        assert "credential" not in body_str
        assert "secret" not in body_str


def test_mcp_tools_not_in_electron():
    """Verify Electron main process does not contain MCP tool dispatch logic."""
    source = (Path(__file__).resolve().parents[2] / "apps/desktop/electron/main.ts").read_text(encoding="utf-8")
    assert "webfa.plan" not in source
    assert "webfa.execute" not in source
    assert "approval_token" not in source
    assert "plan_hash" not in source
