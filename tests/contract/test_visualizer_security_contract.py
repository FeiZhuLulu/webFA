from pathlib import Path

from fastapi.testclient import TestClient

from apps.runtime.main import create_app
from storage.db import reset_engine_for_tests

FIXTURE_PAGE = Path(__file__).resolve().parents[1] / "fixtures" / "agent_validation_page.html"


def test_visualizer_state_has_no_sensitive_fields(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        body_str = str(client.get("/v1/visualizer/state").json()).lower()

    for forbidden in ("cookie", "localstorage", "sessionstorage", "authorization", "devtools", "websocket"):
        assert forbidden not in body_str


def test_open_host_compat_points_to_auth_surface_not_external_window(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_AUTH_SURFACE_MODE", "electron")
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        body = client.post("/v1/visualizer/open-host").json()

    assert body["auth_surface"]["mode"] == "electron"
    assert body["runtime"]["visible_window"] is False
    assert "chromium window" not in str(body).lower()


def test_mcp_tool_count_unchanged_after_visualizer_route(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        tools = client.get("/v1/mcp/status").json()["tools"]

    assert tools == [
        "webfa.open_url",
        "webfa.observe",
        "webfa.act",
        "webfa.get_tabs",
        "webfa.switch_tab",
    ]