from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from schemas.browser import BrowserActionRequest, BrowserTab, BrowserViewport


VISIBLE_TEXT_MAX_CHARS = 8000
CONTENT_BLOCK_MAX_CHARS = 1000
CONTENT_BLOCK_MAX_COUNT = 80
ACTION_TIMEOUT_MS = 5000


@dataclass
class RawPageSnapshot:
    url: str
    title: str
    loading: bool
    focused_element_id: str | None
    viewport: BrowserViewport
    tabs: list[BrowserTab]
    visible_text: str
    content_blocks: list[dict] = field(default_factory=list)
    forms: list[dict] = field(default_factory=list)
    interactive_elements: list[dict] = field(default_factory=list)


class BrowserDriver(Protocol):
    def open(self, url: str) -> None: ...

    def observe_raw(self) -> RawPageSnapshot: ...

    def act(self, request: BrowserActionRequest) -> None: ...

    def tabs(self) -> list[BrowserTab]: ...

    def switch_tab(self, tab_id: str) -> None: ...

    def close(self) -> None: ...
