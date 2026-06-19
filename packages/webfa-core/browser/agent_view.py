from __future__ import annotations

from browser.driver import VISIBLE_TEXT_MAX_CHARS, RawPageSnapshot
from schemas.browser import (
    BrowserContentBlock,
    BrowserElement,
    BrowserForm,
    BrowserState,
    parse_browser_url_parts,
)


class AgentViewBuilder:
    def build(self, raw: RawPageSnapshot, session_id: str = "default") -> BrowserState:
        return BrowserState(
            session_id=session_id,
            url=raw.url,
            url_parts=parse_browser_url_parts(raw.url),
            title=raw.title,
            page_status="loading" if raw.loading else "idle",
            focused_element_id=raw.focused_element_id,
            viewport=raw.viewport,
            tabs=raw.tabs,
            visible_text=(raw.visible_text or "")[:VISIBLE_TEXT_MAX_CHARS],
            content_blocks=[BrowserContentBlock(**item) for item in raw.content_blocks],
            forms=[BrowserForm(**item) for item in raw.forms],
            interactive_elements=[BrowserElement(**item) for item in raw.interactive_elements],
            error=None,
        )
