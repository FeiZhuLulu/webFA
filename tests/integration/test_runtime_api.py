from pathlib import Path

from fastapi.testclient import TestClient

from apps.runtime.main import create_app
from browser.managed_chromium_host import _find_chromium_executable
from storage.db import reset_engine_for_tests


def _require_managed_chromium() -> None:
    import pytest

    pytest.importorskip("websockets.sync.client")
    try:
        _find_chromium_executable()
    except RuntimeError as exc:
        pytest.skip(str(exc))


def test_health_returns_ok(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.delenv("WEBFA_BROWSER_DRIVER", raising=False)
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["runtime"] == "running"
    assert body["storage"]["db_path"].endswith("webfa.db")
    assert body["browser"]["selected_driver"] == "managed-chromium"
    assert body["browser"]["host_status"] == "not_started"
    assert "executable_found" in body["browser"]
    body_str = str(body).lower()
    for forbidden in ("token", "cookie", "localstorage", "sessionstorage", "websocketdebuggerurl"):
        assert forbidden not in body_str


def test_health_reports_browser_after_open(monkeypatch, tmp_path: Path):
    _require_managed_chromium()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    monkeypatch.delenv("WEBFA_BROWSER_DRIVER", raising=False)
    reset_engine_for_tests()

    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "agent_validation_page.html"
    with TestClient(create_app()) as client:
        opened = client.post("/v1/browser/open", json={"url": fixture.as_uri()})
        assert opened.status_code == 200, opened.text
        response = client.get("/health")

    assert response.status_code == 200
    browser = response.json()["browser"]
    assert browser["selected_driver"] == "managed-chromium"
    assert browser["host_status"] == "running"
    assert browser["executable_found"] is True
    assert browser["profile_id"] == "default"
    body_str = str(browser).lower()
    for forbidden in ("token", "cookie", "localstorage", "sessionstorage", "websocket", "devtools"):
        assert forbidden not in body_str


def test_transactions_endpoint_returns_registry(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        response = client.get("/v1/transactions")

    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["transactions"]}
    assert ids == {"github.patch_and_open_pr", "hf.compare_and_publish", "mock.patch_and_open_pr"}


def test_providers_endpoint_returns_disconnected(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        response = client.get("/v1/providers")

    assert response.status_code == 200
    providers = {item["id"]: item["status"] for item in response.json()["providers"]}
    assert providers["github"] == "disconnected"
    assert providers["huggingface"] == "disconnected"
