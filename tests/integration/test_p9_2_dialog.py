from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.runtime.main import create_app
from browser.managed_chromium_host import _find_chromium_executable
from storage.db import reset_engine_for_tests

DIALOG_PAGE = Path(__file__).resolve().parents[1] / "fixtures" / "dialog_confirm_page.html"


def _require_default_browser() -> None:
    pytest.importorskip("websockets.sync.client")
    try:
        _find_chromium_executable()
    except RuntimeError as exc:
        pytest.skip(str(exc))


def test_dialog_confirm_flow(monkeypatch, tmp_path: Path):
    _require_default_browser()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "0")
    monkeypatch.delenv("WEBFA_BROWSER_DRIVER", raising=False)
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        opened = client.post("/v1/browser/open", json={"url": DIALOG_PAGE.as_uri()})
        assert opened.status_code == 200, opened.text
        state = opened.json()["state"]
        button = next(el for el in state["interactive_elements"] if el.get("role") == "button")

        blocked = client.post("/v1/browser/act", json={"action": "click", "target": button["id"]})
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["detail"]["code"] == "dialog_required"

        plain_act = client.post("/v1/browser/act", json={"action": "type", "target": button["id"], "text": "x"})
        assert plain_act.status_code == 409
        assert plain_act.json()["detail"]["code"] == "dialog_required"

        dismissed = client.post(
            "/v1/browser/act",
            json={"action": "dismiss_dialog", "target": "dialog_1"},
        )
        assert dismissed.status_code == 200, dismissed.text
        assert dismissed.json()["state"]["dialogs"] == []

        final = client.get("/v1/browser/observe")
        assert final.status_code == 200
        assert "dismissed" in final.json()["visible_text"].lower()