from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.runtime.main import create_app
from browser.managed_chromium_host import _find_chromium_executable
from storage.db import reset_engine_for_tests

FIXTURE_PAGE = Path(__file__).resolve().parents[1] / "fixtures" / "agent_validation_page.html"


def _require_default_browser() -> None:
    pytest.importorskip("websockets.sync.client")
    try:
        _find_chromium_executable()
    except RuntimeError as exc:
        pytest.skip(str(exc))


def test_visualizer_state_before_browser_start(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        response = client.get("/v1/visualizer/state")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["runtime"]["host_status"] == "not_started"
        assert body["browser_state"] is not None
        assert body["web_state"] is None
        assert body["takeover_surface"]["active"] is False
        assert body["recent_actions"] == []
        assert "cookie" not in str(body).lower()


def test_visualizer_state_after_open_and_action_log(monkeypatch, tmp_path: Path):
    _require_default_browser()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    monkeypatch.delenv("WEBFA_BROWSER_DRIVER", raising=False)
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        opened = client.post("/v1/browser/open", json={"url": FIXTURE_PAGE.as_uri()})
        assert opened.status_code == 200, opened.text

        response = client.get("/v1/visualizer/state")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["page"]["title"] == "WebFA Agent Validation"
        assert body["browser_state"]["url_parts"]["scheme"] == "file"
        assert body["web_state"]["document_id"]
        assert body["web_state"]["object_count"] >= len(body["web_state"]["objects"])
        assert body["takeover_surface"]["active"] is False
        assert any(entry["tool"] == "webfa.open_url" for entry in body["recent_actions"])
        assert "password" not in str(body).lower() or "[redacted]" in str(body).lower() or body["browser_state"]["forms"]


def test_visualizer_open_auth_surface_does_not_require_visible_window(monkeypatch, tmp_path: Path):
    _require_default_browser()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    monkeypatch.setenv("WEBFA_AUTH_SURFACE_MODE", "electron")
    monkeypatch.delenv("WEBFA_BROWSER_DRIVER", raising=False)
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        client.post("/v1/browser/open", json={"url": FIXTURE_PAGE.as_uri()})
        response = client.post("/v1/visualizer/open-auth-surface")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["auth_surface"]["active"] is True
        assert body["takeover_surface"]["active"] is True
        assert body["takeover_surface"]["reason"] == "authentication"
        assert body["web_state"]["takeover"]["reason"] == "authentication"
        assert body["browser_state"]["auth"]["takeover"] == "auth_surface"
        assert body["runtime"]["visible_window"] is False
        assert "devtools" not in str(body).lower()

        legacy = client.post("/v1/visualizer/open-host")
        assert legacy.status_code == 200
        assert legacy.json()["auth_surface"]["active"] is True

        closed = client.post("/v1/visualizer/close-auth-surface", json={"url": FIXTURE_PAGE.as_uri()})
        assert closed.status_code == 200
        assert closed.json()["auth_surface"]["active"] is False
        assert closed.json()["takeover_surface"]["active"] is False
        assert closed.json()["runtime"]["host_status"] == "running"


def test_visualizer_restart_host(monkeypatch, tmp_path: Path):
    _require_default_browser()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    monkeypatch.delenv("WEBFA_BROWSER_DRIVER", raising=False)
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        client.post("/v1/browser/open", json={"url": FIXTURE_PAGE.as_uri()})
        response = client.post("/v1/visualizer/restart-host")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["runtime"]["host_status"] == "running"
        assert body["page"]["title"] == "WebFA Agent Validation"
        assert any(entry["tool"] == "visualizer.restart_host" for entry in body["recent_actions"])
