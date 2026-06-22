from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from apps.runtime.main import create_app
from browser.driver import RawPageSnapshot
from browser.runtime import BrowserRuntime
from schemas.browser import BrowserActionRequest, BrowserTab, BrowserViewport
from storage.db import reset_engine_for_tests


class FakeDriver:
    def __init__(self) -> None:
        self.url = ""
        self.title = "Blank"

    def open(self, url: str) -> None:
        self.url = url
        self.title = "Opened"

    def observe_raw(self) -> RawPageSnapshot:
        return RawPageSnapshot(
            url=self.url,
            title=self.title,
            loading=False,
            focused_element_id=None,
            viewport=BrowserViewport(width=1280, height=720),
            tabs=[BrowserTab(id="tab_1", url=self.url, title=self.title, active=True)],
            visible_text=self.title,
            interactive_elements=[],
        )

    def act(self, request: BrowserActionRequest) -> None:
        self.title = f"acted:{request.action}"

    def tabs(self) -> list[BrowserTab]:
        return [BrowserTab(id="tab_1", url=self.url, title=self.title, active=True)]

    def switch_tab(self, tab_id: str) -> None:
        self.title = f"tab:{tab_id}"

    def close(self) -> None:
        pass


def _client(monkeypatch, tmp_path: Path, ttl: int = 600) -> TestClient:
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_AGENT_LEASE_TTL_SECONDS", str(ttl))
    reset_engine_for_tests()
    app = create_app()
    app.state.browser_runtime = BrowserRuntime(headless=True, driver_factory=FakeDriver)
    return TestClient(app)


def test_agent_lease_blocks_second_agent_mutation_but_allows_observe(monkeypatch, tmp_path: Path):
    with _client(monkeypatch, tmp_path) as client:
        first = client.post(
            "/v1/browser/open",
            json={"url": "https://example.com"},
            headers={"X-WebFA-Agent-Id": "opencode"},
        )
        assert first.status_code == 200, first.text
        assert first.json()["state"]["agent"]["active_agent_id"] == "opencode"

        blocked = client.post(
            "/v1/browser/open",
            json={"url": "https://example.org"},
            headers={"X-WebFA-Agent-Id": "kimi-code"},
        )
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["code"] == "agent_busy"
        assert blocked.json()["detail"]["active_agent_id"] == "opencode"

        observed = client.get("/v1/browser/observe", headers={"X-WebFA-Agent-Id": "kimi-code"})
        assert observed.status_code == 200
        assert observed.json()["agent"]["active_agent_id"] == "opencode"

        tabs = client.get("/v1/browser/tabs", headers={"X-WebFA-Agent-Id": "kimi-code"})
        assert tabs.status_code == 200
        assert tabs.json()["agent"]["active_agent_id"] == "opencode"


def test_agent_lease_expires_and_allows_new_agent(monkeypatch, tmp_path: Path):
    import time

    with _client(monkeypatch, tmp_path, ttl=1) as client:
        first = client.post(
            "/v1/browser/open",
            json={"url": "https://example.com"},
            headers={"X-WebFA-Agent-Id": "opencode"},
        )
        assert first.status_code == 200

        time.sleep(1.2)

        second = client.post(
            "/v1/browser/open",
            json={"url": "https://example.org"},
            headers={"X-WebFA-Agent-Id": "kimi-code"},
        )
        assert second.status_code == 200, second.text
        assert second.json()["state"]["agent"]["active_agent_id"] == "kimi-code"


def test_health_reports_agent_lease_and_shared_profile(monkeypatch, tmp_path: Path):
    with _client(monkeypatch, tmp_path) as client:
        client.post(
            "/v1/browser/open",
            json={"url": "https://example.com"},
            headers={"X-WebFA-Agent-Id": "opencode"},
        )

        health = client.get("/health").json()["browser"]

    assert health["active_agent_id"] == "opencode"
    assert health["agent_lease_expires_at"]
    assert health["profile_shared"] is True
    assert health["profile_id"] == "default"
