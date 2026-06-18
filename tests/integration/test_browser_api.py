from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.runtime.main import create_app
from storage.db import reset_engine_for_tests

FIXTURE_PAGE = Path(__file__).resolve().parents[1] / "fixtures" / "agent_validation_page.html"


def test_browser_open_observe_act_loop(monkeypatch, tmp_path: Path):
    pytest.importorskip("playwright.sync_api")
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        opened = client.post("/v1/browser/open", json={"url": FIXTURE_PAGE.as_uri()})
        assert opened.status_code == 200, opened.text
        state = opened.json()["state"]
        assert state["session_id"] == "default"
        assert state["title"] == "WebFA Agent Validation"
        assert state["url_parts"]["scheme"] == "file"
        assert state["url_parts"]["path"].endswith("agent_validation_page.html")
        assert state["url_parts"]["query"] == {}
        assert "WebFA Agent Validation" in state["visible_text"]
        assert "cookies" not in str(state).lower()
        assert "localstorage" not in str(state).lower()
        assert "full_html" not in state
        assert "full_dom" not in state

        name_el = next(el for el in state["interactive_elements"] if el["placeholder"] == "Your name")
        button_el = next(el for el in state["interactive_elements"] if el["role"] == "button")
        assert "press" in name_el["actions"]

        typed = client.post("/v1/browser/act", json={"action": "type", "target": name_el["id"], "text": "hello"})
        assert typed.status_code == 200, typed.text
        updated = typed.json()["state"]
        typed_el = next(el for el in updated["interactive_elements"] if el["placeholder"] == "Your name")
        assert typed_el["value"] == "hello"

        clicked = client.post("/v1/browser/act", json={"action": "click", "target": button_el["id"]})
        assert clicked.status_code == 200, clicked.text
        assert "Hello hello" in clicked.json()["state"]["visible_text"]

        wait = client.post("/v1/browser/act", json={"action": "wait_for_text", "text": "Hello hello", "timeout_ms": 1000})
        assert wait.status_code == 200, wait.text


def test_browser_rejects_raw_selector(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        response = client.post("/v1/browser/act", json={"action": "click", "selector": "button"})

    assert response.status_code == 422


def test_browser_stale_element_after_navigation(monkeypatch, tmp_path: Path):
    pytest.importorskip("playwright.sync_api")
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        state = client.post("/v1/browser/open", json={"url": FIXTURE_PAGE.as_uri()}).json()["state"]
        link = next(el for el in state["interactive_elements"] if el["tag"] == "a")
        assert client.post("/v1/browser/act", json={"action": "click", "target": link["id"]}).status_code == 200
        stale = client.post("/v1/browser/act", json={"action": "click", "target": link["id"]})

    assert stale.status_code == 400
    assert "call observe again" in stale.json()["detail"]


def test_browser_keeps_element_ids_stable_after_dom_insert(monkeypatch, tmp_path: Path):
    pytest.importorskip("playwright.sync_api")
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    reset_engine_for_tests()

    page = tmp_path / "dynamic.html"
    page.write_text(
        """
        <!doctype html>
        <title>Dynamic Form</title>
        <input id="q" placeholder="Search" oninput="
          if (!document.getElementById('tips')) {
            const a = document.createElement('a');
            a.id = 'tips';
            a.href = '#tips';
            a.textContent = 'Search syntax tips';
            document.getElementById('submit').before(a);
          }
        ">
        <button id="submit" onclick="result.textContent = q.value">Search</button>
        <div id="result"></div>
        """,
        encoding="utf-8",
    )

    with TestClient(create_app()) as client:
        state = client.post("/v1/browser/open", json={"url": page.as_uri()}).json()["state"]
        textbox = next(el for el in state["interactive_elements"] if el["placeholder"] == "Search")
        submit = next(el for el in state["interactive_elements"] if el["text"] == "Search")
        submit_id = submit["id"]

        typed = client.post("/v1/browser/act", json={"action": "type", "target": textbox["id"], "text": "webfa"})
        assert typed.status_code == 200, typed.text
        updated_submit = next(el for el in typed.json()["state"]["interactive_elements"] if el["text"] == "Search")
        assert updated_submit["id"] == submit_id

        clicked = client.post("/v1/browser/act", json={"action": "click", "target": submit_id})
        assert clicked.status_code == 200, clicked.text
        assert "webfa" in clicked.json()["state"]["visible_text"]
