from __future__ import annotations

from browser.driver import RawPageSnapshot


class ElementRegistry:
    def __init__(self) -> None:
        self._url: str | None = None
        self._ids: set[str] = set()

    def update(self, raw: RawPageSnapshot) -> None:
        if raw.url != self._url:
            self.clear()
            self._url = raw.url
        self._ids = {
            element["id"]
            for element in raw.interactive_elements
            if isinstance(element.get("id"), str)
        }

    def require(self, element_id: str | None) -> None:
        if not element_id or element_id not in self._ids:
            raise ValueError("element id is stale; call observe again")

    def clear(self) -> None:
        self._url = None
        self._ids.clear()
