from __future__ import annotations

from typing import Protocol

from schemas.browser import BrowserTab


class BrowserHost(Protocol):
    """Low-level webpage host used by experimental drivers.

    Host implementations run or connect to a real web engine. They do not know
    about MCP, REST, BrowserState, or agent-facing tool semantics.
    """

    def navigate(self, url: str) -> None: ...

    def evaluate(self, expression: str) -> object: ...

    def tabs(self) -> list[BrowserTab]: ...

    def close(self) -> None: ...

