from __future__ import annotations

import os
import queue
import threading
from typing import Any, Callable

from browser.agent_view import AgentViewBuilder
from browser.driver import BrowserDriver, RawPageSnapshot
from browser.playwright_driver import PlaywrightBrowserDriver
from schemas.browser import (
    BrowserActionRequest,
    BrowserActionResult,
    BrowserState,
    BrowserTab,
)


DriverFactory = Callable[[], BrowserDriver]


class BrowserRuntime:
    """Single-session agent browser runtime backed by one driver thread."""

    def __init__(self, headless: bool | None = None, driver_factory: DriverFactory | None = None) -> None:
        self._headless = headless if headless is not None else os.getenv("WEBFA_BROWSER_HEADLESS") == "1"
        self._driver_factory = driver_factory or (lambda: PlaywrightBrowserDriver(headless=self._headless))
        self._jobs: queue.Queue[tuple[str, tuple, queue.Queue] | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._closed = False

    def open(self, url: str) -> BrowserActionResult:
        return self._call("open", url)

    def observe(self) -> BrowserState:
        return self._call("observe")

    def act(self, request: BrowserActionRequest) -> BrowserActionResult:
        return self._call("act", request)

    def tabs(self) -> list[BrowserTab]:
        return self._call("tabs")

    def switch_tab(self, tab_id: str) -> BrowserState:
        return self._call("switch_tab", tab_id)

    def close(self) -> None:
        if self._thread is None or self._closed:
            return
        result: queue.Queue = queue.Queue(maxsize=1)
        self._jobs.put(("close", (), result))
        ok, value = result.get(timeout=30)
        self._closed = True
        self._thread.join(timeout=30)
        if not ok:
            raise value

    def _call(self, name: str, *args: Any) -> Any:
        if self._closed:
            raise RuntimeError("browser runtime is closed")
        self._ensure_thread()
        result: queue.Queue = queue.Queue(maxsize=1)
        self._jobs.put((name, args, result))
        ok, value = result.get(timeout=60)
        if ok:
            return value
        raise value

    def _ensure_thread(self) -> None:
        if self._thread is not None:
            return
        worker = _BrowserWorker(self._driver_factory)
        self._thread = threading.Thread(target=worker.run, args=(self._jobs,), name="webfa-browser", daemon=True)
        self._thread.start()


class _BrowserWorker:
    def __init__(self, driver_factory: DriverFactory) -> None:
        self._driver_factory = driver_factory
        self._driver: BrowserDriver | None = None
        self._view_builder = AgentViewBuilder()

    def run(self, jobs: queue.Queue) -> None:
        handlers: dict[str, Callable[..., Any]] = {
            "open": self.open,
            "observe": self.observe,
            "act": self.act,
            "tabs": self.tabs,
            "switch_tab": self.switch_tab,
            "close": self.close,
        }
        while True:
            job = jobs.get()
            if job is None:
                return
            name, args, result = job
            try:
                value = handlers[name](*args)
                result.put((True, value))
                if name == "close":
                    return
            except Exception as exc:
                result.put((False, exc))

    def open(self, url: str) -> BrowserActionResult:
        driver = self._ensure_driver()
        driver.open(url)
        return BrowserActionResult(ok=True, action="open_url", state=self._state_from_raw(driver.observe_raw()))

    def observe(self) -> BrowserState:
        if self._driver is None:
            return BrowserState()
        return self._state_from_raw(self._driver.observe_raw())

    def act(self, request: BrowserActionRequest) -> BrowserActionResult:
        driver = self._ensure_driver()
        driver.act(request)
        return BrowserActionResult(ok=True, action=request.action, state=self._state_from_raw(driver.observe_raw()))

    def tabs(self) -> list[BrowserTab]:
        return [] if self._driver is None else self._driver.tabs()

    def switch_tab(self, tab_id: str) -> BrowserState:
        driver = self._ensure_driver()
        driver.switch_tab(tab_id)
        return self._state_from_raw(driver.observe_raw())

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
        self._driver = None

    def _ensure_driver(self) -> BrowserDriver:
        if self._driver is None:
            self._driver = self._driver_factory()
        return self._driver

    def _state_from_raw(self, raw: RawPageSnapshot) -> BrowserState:
        return self._view_builder.build(raw, session_id="default")
