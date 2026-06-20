from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.runtime.main import create_app
from browser.managed_chromium_host import ManagedChromiumHost, _find_chromium_executable
from storage.db import reset_engine_for_tests


FIXTURE_PAGE = Path(__file__).resolve().parents[1] / "fixtures" / "agent_validation_page.html"


def _require_managed_chromium() -> None:
    pytest.importorskip("websockets.sync.client")
    try:
        _find_chromium_executable()
    except RuntimeError as exc:
        pytest.skip(str(exc))


def test_managed_chromium_open_observe_act_loop(monkeypatch, tmp_path: Path):
    _require_managed_chromium()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_DRIVER", "managed-chromium")
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        opened = client.post("/v1/browser/open", json={"url": FIXTURE_PAGE.as_uri()})
        assert opened.status_code == 200, opened.text
        state = opened.json()["state"]
        assert state["title"] == "WebFA Agent Validation"
        assert state["url_parts"]["scheme"] == "file"
        assert "WebFA Agent Validation" in state["visible_text"]
        assert state["content_blocks"]

        tabs = client.get("/v1/browser/tabs")
        assert tabs.status_code == 200, tabs.text
        assert tabs.json()["tabs"]

        name_el = next(el for el in state["interactive_elements"] if el["placeholder"] == "Your name")
        button_el = next(el for el in state["interactive_elements"] if el["role"] == "button")

        typed = client.post("/v1/browser/act", json={"action": "type", "target": name_el["id"], "text": "Fei"})
        assert typed.status_code == 200, typed.text
        typed_el = next(el for el in typed.json()["state"]["interactive_elements"] if el["placeholder"] == "Your name")
        assert typed_el["value"] == "Fei"

        clicked = client.post("/v1/browser/act", json={"action": "click", "target": button_el["id"]})
        assert clicked.status_code == 200, clicked.text
        assert "Hello Fei" in clicked.json()["state"]["visible_text"]


def test_managed_chromium_rejects_unsupported_actions(monkeypatch, tmp_path: Path):
    _require_managed_chromium()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_DRIVER", "managed-chromium")
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        state = client.post("/v1/browser/open", json={"url": FIXTURE_PAGE.as_uri()}).json()["state"]
        name_el = next(el for el in state["interactive_elements"] if el["placeholder"] == "Your name")
        unsupported = client.post("/v1/browser/act", json={"action": "select", "target": name_el["id"], "value": "x"})

    assert unsupported.status_code == 400
    assert "element is not a select" in unsupported.json()["detail"]


def test_managed_chromium_object_form_actions(monkeypatch, tmp_path: Path):
    _require_managed_chromium()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_DRIVER", "managed-chromium")
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        state = client.post("/v1/browser/open", json={"url": FIXTURE_PAGE.as_uri()}).json()["state"]
        assert state["forms"][0]["field_details"][0]["key"] == "name"

        filled = client.post("/v1/browser/act", json={"action": "fill_form", "target": "form_1", "fields": {"name": "Fei"}})
        assert filled.status_code == 200, filled.text
        field = filled.json()["state"]["forms"][0]["field_details"][0]
        assert field["value"] == "Fei"

        submitted = client.post("/v1/browser/act", json={"action": "submit_form", "target": "form_1"})
        assert submitted.status_code == 200, submitted.text
        assert "Hello Fei" in submitted.json()["state"]["visible_text"]


def test_managed_chromium_restarts_after_process_exit(monkeypatch, tmp_path: Path):
    _require_managed_chromium()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))

    host = ManagedChromiumHost(headless=True)
    try:
        host.navigate(FIXTURE_PAGE.as_uri())
        first = host.status()
        assert first["host_status"] == "running"

        assert host._process is not None
        host._process.kill()
        host._process.wait(timeout=5)
        assert host.status()["host_status"] == "exited"

        host.navigate(FIXTURE_PAGE.as_uri())
        restarted = host.status()
        assert restarted["host_status"] == "running"
        assert restarted["last_error"] is None
    finally:
        host.close()
