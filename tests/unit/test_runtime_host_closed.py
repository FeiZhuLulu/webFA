from __future__ import annotations

import pytest

from browser.driver import RawPageSnapshot
from browser.exceptions import BrowserHostClosedError
from browser.runtime import BrowserRuntime
from schemas.browser import BrowserActionRequest, BrowserTab, BrowserViewport


class FakeHostDriver:
    def __init__(self) -> None:
        self.url = ""
        self.host_status = "running"
        self.opens: list[str] = []
        self.closed = False

    def open(self, url: str) -> None:
        self.url = url
        self.opens.append(url)

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
        return {"host_status": self.host_status}


def _runtime_with_drivers() -> tuple[BrowserRuntime, list[FakeHostDriver]]:
    drivers: list[FakeHostDriver] = []
    runtime = BrowserRuntime(headless=False, driver_factory=lambda: (drivers.append(FakeHostDriver()) or drivers[-1]))
    return runtime, drivers


def test_browser_host_closed_error_message():
    exc = BrowserHostClosedError()

    assert str(exc) == "Browser host has exited; use open_url to restart"


def test_observe_raises_browser_host_closed_after_host_exits():
    runtime, drivers = _runtime_with_drivers()
    runtime.open("https://example.com")
    drivers[-1].host_status = "exited"

    with pytest.raises(BrowserHostClosedError):
        runtime.observe()


def test_tabs_raises_browser_host_closed_after_host_exits():
    runtime, drivers = _runtime_with_drivers()
    runtime.open("https://example.com")
    drivers[-1].host_status = "exited"

    with pytest.raises(BrowserHostClosedError):
        runtime.tabs()


def test_act_raises_browser_host_closed_after_host_exits():
    runtime, drivers = _runtime_with_drivers()
    runtime.open("https://example.com")
    drivers[-1].host_status = "exited"

    with pytest.raises(BrowserHostClosedError):
        runtime.act(BrowserActionRequest(action="click", target="el_1"))


def test_open_url_restarts_host_after_browser_host_closed():
    runtime, drivers = _runtime_with_drivers()
    runtime.open("https://example.com")
    assert len(drivers) == 1
    drivers[-1].host_status = "exited"

    result = runtime.open("https://example.org")

    assert result.state.url == "https://example.org"
    assert len(drivers) == 2
    assert drivers[0].closed is True
    assert drivers[1].url == "https://example.org"
