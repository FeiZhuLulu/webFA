from __future__ import annotations

from fastapi.testclient import TestClient

from apps.runtime.main import create_app
from browser.driver import RawPageSnapshot
from browser.runtime import BrowserRuntime
from schemas.browser import BrowserActionRequest, BrowserTab, BrowserViewport
from storage.db import reset_engine_for_tests


class FakeHostDriver:
    def __init__(self) -> None:
        self.url = ""
        self.host_status = "running"
        self.closed = False

    def open(self, url: str) -> None:
        self.url = url

    def observe_raw(self) -> RawPageSnapshot:
        return RawPageSnapshot(
            url=self.url,
            title="Page",
            loading=False,
            focused_element_id=None,
            viewport=BrowserViewport(width=1280, height=720),
            tabs=[BrowserTab(id="tab_1", url=self.url, title="Page", active=True)],
            visible_text="Hello",
            interactive_elements=[],
        )

    def act(self, request: BrowserActionRequest) -> None:
        pass

    def tabs(self) -> list[BrowserTab]:
        return []

    def switch_tab(self, tab_id: str) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    def status(self) -> dict:
        return {
            "host_status": self.host_status,
            "headless": False,
            "visible_window": self.host_status == "running",
        }


def _client_with_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()
    app = create_app()
    drivers: list[FakeHostDriver] = []
    runtime = BrowserRuntime(headless=False, driver_factory=lambda: (drivers.append(FakeHostDriver()) or drivers[-1]))
    runtime.open("https://example.com")
    app.state.browser_runtime = runtime
    drivers[-1].host_status = "exited"
    return app, drivers


def test_observe_returns_503_when_host_exited(monkeypatch, tmp_path):
    app, _drivers = _client_with_runtime(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.get("/v1/browser/observe")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "browser_host_closed"


def test_tabs_returns_503_when_host_exited(monkeypatch, tmp_path):
    app, _drivers = _client_with_runtime(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.get("/v1/browser/tabs")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "browser_host_closed"


def test_open_url_restarts_host_after_exited(monkeypatch, tmp_path):
    app, drivers = _client_with_runtime(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.post("/v1/browser/open", json={"url": "https://example.org"})

    assert response.status_code == 200
    assert len(drivers) == 2
    assert drivers[0].closed is True
    assert drivers[1].url == "https://example.org"


def test_health_reports_host_exited(monkeypatch, tmp_path):
    app, _drivers = _client_with_runtime(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    browser = response.json()["browser"]
    assert browser["host_status"] == "exited"
    assert browser["headless"] is False
