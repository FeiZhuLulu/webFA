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
        assert any(entry["tool"] == "webfa.open_url" for entry in body["recent_actions"])
        assert "password" not in str(body).lower() or "[redacted]" in str(body).lower() or body["browser_state"]["forms"]


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