from __future__ import annotations

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


def _find_object(state: dict, *, role: str, name: str | None = None) -> dict:
    for item in state["objects"]:
        if item.get("role") != role:
            continue
        if name is not None and item.get("name") != name:
            continue
        return item
    raise AssertionError(f"WebObject not found: role={role}, name={name}")


def test_public_web_object_rest_loop(monkeypatch, tmp_path: Path):
    _require_managed_chromium()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    monkeypatch.delenv("WEBFA_BROWSER_DRIVER", raising=False)
    reset_engine_for_tests()

    headers = {"X-WebFA-Agent-Id": "web-api-test"}
    with TestClient(create_app()) as client:
        opened = client.post(
            "/v1/browser/web/open",
            headers=headers,
            json={"url": FIXTURE_PAGE.as_uri()},
        )
        assert opened.status_code == 200, opened.text
        state = opened.json()["state"]
        assert state["document_id"]
        assert state["document_revision"] >= 1
        assert state["url"].endswith("agent_validation_page.html")

        field = _find_object(state, role="textbox", name="Your name")
        form = _find_object(state, role="form")
        assert "set_value" in field["capabilities"]
        assert "submit" in form["capabilities"]

        typed = client.post(
            "/v1/browser/web/act",
            headers=headers,
            json={
                "target": field["id"],
                "operation": "set_value",
                "arguments": {"value": "Fei"},
                "expected_object_version": field["version"],
            },
        )
        assert typed.status_code == 200, typed.text
        assert typed.json()["operation"] == "set_value"

        submitted = client.post(
            "/v1/browser/web/act",
            headers=headers,
            json={"target": form["id"], "operation": "submit", "arguments": {}},
        )
        assert submitted.status_code == 200, submitted.text

        queried = client.post(
            "/v1/browser/web/observe",
            headers=headers,
            json={
                "mode": "query",
                "query": {"text_contains": "Hello Fei"},
                "detail": "full",
                "limit": 10,
            },
        )
        assert queried.status_code == 200, queried.text
        query_state = queried.json()
        assert any("Hello Fei" in (item.get("text") or item.get("name") or "") for item in query_state["objects"])


def test_public_web_object_api_rejects_browser_primitives_and_selectors(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        primitive = client.post(
            "/v1/browser/web/act",
            json={"target": "obj_1", "operation": "click", "arguments": {}},
        )
        selector = client.post(
            "/v1/browser/web/observe",
            json={"mode": "query", "query": {"selector": "button"}},
        )

    assert primitive.status_code == 422
    assert selector.status_code == 422
    combined = f"{primitive.text} {selector.text}".lower()
    assert "playwright" not in combined
    assert "cdp" not in combined
