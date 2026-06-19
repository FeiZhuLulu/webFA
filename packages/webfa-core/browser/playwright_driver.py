from __future__ import annotations

from pathlib import Path
from typing import Any

from browser.driver import (
    ACTION_TIMEOUT_MS,
    CONTENT_BLOCK_MAX_CHARS,
    CONTENT_BLOCK_MAX_COUNT,
    VISIBLE_TEXT_MAX_CHARS,
    RawPageSnapshot,
)
from browser.observe_probe import OBSERVE_PROBE
from schemas.browser import BrowserActionRequest, BrowserTab, BrowserViewport
from storage.file_store import ensure_webfa_data_dir


class PlaywrightBrowserDriver:
    def __init__(self, headless: bool) -> None:
        self._headless = headless
        self._playwright: Any = None
        self._context: Any = None
        self._page: Any = None

    def open(self, url: str) -> None:
        self._ensure_page().goto(url, wait_until="domcontentloaded")

    def observe_raw(self) -> RawPageSnapshot:
        page = self._ensure_page()
        raw = page.evaluate(
            OBSERVE_PROBE,
            {"maxChars": VISIBLE_TEXT_MAX_CHARS, "blockChars": CONTENT_BLOCK_MAX_CHARS, "blockCount": CONTENT_BLOCK_MAX_COUNT},
        )
        viewport = page.viewport_size or {"width": 1280, "height": 720}
        return RawPageSnapshot(
            url=page.url,
            title=page.title(),
            loading=bool(raw.get("loading")),
            focused_element_id=raw.get("focused_element_id"),
            viewport=BrowserViewport(width=viewport["width"], height=viewport["height"]),
            tabs=self.tabs(),
            visible_text=raw.get("visible_text", ""),
            content_blocks=raw.get("content_blocks", []),
            forms=raw.get("forms", []),
            interactive_elements=raw.get("interactive_elements", []),
        )

    def act(self, request: BrowserActionRequest) -> None:
        page = self._ensure_page()
        action = request.action

        if action == "wait":
            page.wait_for_timeout(request.ms)
        elif action == "wait_for_text":
            page.get_by_text(request.text, exact=False).first.wait_for(timeout=request.timeout_ms or 5000)
        elif action == "wait_for_element":
            self._wait_for_element(request)
        elif action == "press":
            if request.target:
                self._locator(request.target).focus(timeout=ACTION_TIMEOUT_MS)
            page.keyboard.press(request.key)
        elif action == "scroll":
            if request.target:
                self._locator(request.target).evaluate("(el, y) => el.scrollBy(0, y)", request.delta_y or 600)
            else:
                page.evaluate("(y) => window.scrollBy(0, y)", request.delta_y or 600)
        else:
            locator = self._locator(request.target)
            if action == "click":
                locator.click(timeout=ACTION_TIMEOUT_MS)
            elif action == "type":
                try:
                    locator.fill(request.text, timeout=ACTION_TIMEOUT_MS)
                except Exception:
                    locator.click(timeout=ACTION_TIMEOUT_MS)
                    page.keyboard.insert_text(request.text or "")
            elif action == "clear":
                locator.fill("", timeout=ACTION_TIMEOUT_MS)
            elif action == "focus":
                locator.focus(timeout=ACTION_TIMEOUT_MS)
            elif action == "select":
                locator.select_option(value=request.value or request.text, timeout=ACTION_TIMEOUT_MS)
            elif action == "check":
                locator.check(timeout=ACTION_TIMEOUT_MS)
            elif action == "uncheck":
                locator.uncheck(timeout=ACTION_TIMEOUT_MS)

    def tabs(self) -> list[BrowserTab]:
        if self._context is None:
            return []
        return [
            BrowserTab(id=f"tab_{index + 1}", url=page.url, title=page.title(), active=page == self._page)
            for index, page in enumerate(self._context.pages)
        ]

    def switch_tab(self, tab_id: str) -> None:
        self._ensure_page()
        index = _tab_index(tab_id)
        pages = self._context.pages
        if index < 0 or index >= len(pages):
            raise ValueError("tab not found")
        self._page = pages[index]
        self._page.bring_to_front()

    def close(self) -> None:
        if self._context is not None:
            self._context.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._context = None
        self._playwright = None
        self._page = None

    def _ensure_page(self) -> Any:
        if self._context is None:
            from playwright.sync_api import sync_playwright

            paths = ensure_webfa_data_dir()
            data_dir = Path(paths["data_dir"])
            profile_dir = data_dir / "browser" / "profile-default"
            downloads_dir = data_dir / "downloads"
            profile_dir.mkdir(parents=True, exist_ok=True)
            downloads_dir.mkdir(parents=True, exist_ok=True)

            self._playwright = sync_playwright().start()
            self._context = self._playwright.chromium.launch_persistent_context(
                str(profile_dir),
                headless=self._headless,
                accept_downloads=True,
                downloads_path=str(downloads_dir),
                viewport={"width": 1280, "height": 720},
            )
        if self._page is None:
            self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        return self._page

    def _locator(self, element_id: str | None) -> Any:
        if not element_id:
            raise ValueError("target is required")
        locator = self._page.locator(f'[data-webfa-id="{element_id}"]')
        if locator.count() == 0:
            raise ValueError("element id is stale; call observe again")
        return locator.first

    def _wait_for_element(self, request: BrowserActionRequest) -> None:
        locator = self._locator(request.target)
        if request.state == "enabled":
            locator.wait_for(state="visible", timeout=request.timeout_ms or 5000)
            self._page.wait_for_function(
                "(id) => { const el = document.querySelector(`[data-webfa-id=\"${id}\"]`); return !!el && !el.disabled; }",
                request.target,
                timeout=request.timeout_ms or 5000,
            )
        else:
            locator.wait_for(state=request.state, timeout=request.timeout_ms or 5000)


def _tab_index(tab_id: str) -> int:
    if not tab_id.startswith("tab_"):
        return -1
    try:
        return int(tab_id.removeprefix("tab_")) - 1
    except ValueError:
        return -1
