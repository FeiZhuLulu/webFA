from __future__ import annotations

from typing import Any, Protocol

from browser.human_control import HumanInputEvent
from schemas.browser import BrowserTab


class BrowserHost(Protocol):
    """Low-level webpage host used by experimental drivers.

    Host implementations run or connect to a real web engine. They do not know
    about MCP, REST, BrowserState, or agent-facing tool semantics.
    """

    def navigate(self, url: str) -> None: ...

    def evaluate(self, expression: str) -> object: ...

    def set_file_input_files(
        self,
        element_id: str,
        file_paths: list[str],
        *,
        frame_id: str | None = None,
    ) -> None: ...

    def capture_accessibility_tree(self) -> dict[str, Any]: ...

    def capture_dom_snapshot(self) -> dict[str, Any]: ...

    def get_frame_tree(self) -> list[dict[str, Any]]: ...

    def tabs(self) -> list[BrowserTab]: ...

    def dispatch_human_input(self, event: HumanInputEvent) -> None: ...

    def close(self) -> None: ...

