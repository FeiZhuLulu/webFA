from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.runtime.main import create_app
from browser.managed_chromium_host import _find_chromium_executable
from storage.db import reset_engine_for_tests

SAME_ORIGIN_PAGE = Path(__file__).resolve().parents[1] / "fixtures" / "iframe_same_origin_page.html"
CROSS_ORIGIN_PAGE = Path(__file__).resolve().parents[1] / "fixtures" / "iframe_cross_origin_page.html"
AUTH_IFRAME_PAGE = Path(__file__).resolve().parents[1] / "fixtures" / "auth_iframe_page.html"


def _require_default_browser() -> None:
    pytest.importorskip("websockets.sync.client")
    try:
        _find_chromium_executable()
    except RuntimeError as exc:
        pytest.skip(str(exc))


def test_same_origin_iframe_elements_are_observable(monkeypatch, tmp_path: Path):
    _require_default_browser()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    monkeypatch.delenv("WEBFA_BROWSER_DRIVER", raising=False)
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        opened = client.post("/v1/browser/open", json={"url": SAME_ORIGIN_PAGE.as_uri()})
        assert opened.status_code == 200, opened.text
        state = opened.json()["state"]
        frame_ids = {frame["id"] for frame in state["frames"]}
        assert "frame_1" in frame_ids
        assert any(frame["same_origin"] and frame["id"] != "frame_1" for frame in state["frames"])

        iframe_elements = [el for el in state["interactive_elements"] if el.get("frame_id") and el["frame_id"] != "frame_1"]
        assert iframe_elements
        child_input = next(el for el in iframe_elements if el.get("placeholder") == "Child name")

        typed = client.post(
            "/v1/browser/act",
            json={"action": "type", "target": child_input["id"], "text": "Fei"},
        )
        assert typed.status_code == 200, typed.text
        updated = typed.json()["state"]["interactive_elements"]
        refreshed = next(el for el in updated if el["id"] == child_input["id"])
        assert refreshed["value"] == "Fei"


def test_cross_origin_iframe_exposes_metadata_only(monkeypatch, tmp_path: Path):
    _require_default_browser()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    monkeypatch.delenv("WEBFA_BROWSER_DRIVER", raising=False)
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        opened = client.post("/v1/browser/open", json={"url": CROSS_ORIGIN_PAGE.as_uri()})
        assert opened.status_code == 200, opened.text
        state = opened.json()["state"]
        external_frames = [frame for frame in state["frames"] if not frame["same_origin"] and frame["id"] != "frame_1"]
        assert external_frames
        iframe_elements = [el for el in state["interactive_elements"] if el.get("frame_id") in {f["id"] for f in external_frames}]
        assert iframe_elements == []
        body_str = str(state).lower()
        assert "example domain" not in body_str or "iframe" in body_str


def test_auth_iframe_triggers_auth_surface(monkeypatch, tmp_path: Path):
    _require_default_browser()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    monkeypatch.setenv("WEBFA_AUTH_SURFACE_MODE", "electron")
    monkeypatch.delenv("WEBFA_BROWSER_DRIVER", raising=False)
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        opened = client.post("/v1/browser/open", json={"url": AUTH_IFRAME_PAGE.as_uri()})
        assert opened.status_code == 200, opened.text
        state = opened.json()["state"]
        assert state["auth"]["surface_detected"] is True
        assert state["auth"]["user_action_required"] is True
        assert any(frame["same_origin"] for frame in state["frames"] if frame["id"] != "frame_1")