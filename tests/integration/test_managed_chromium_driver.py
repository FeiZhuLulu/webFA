from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.runtime.main import create_app
from browser.managed_chromium_host import _find_chromium_executable
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
    assert "not supported by managed chromium driver" in unsupported.json()["detail"]
