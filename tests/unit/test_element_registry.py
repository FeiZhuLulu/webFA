import pytest

from browser.driver import RawPageSnapshot
from browser.element_registry import ElementRegistry
from browser.runtime_errors import BrowserRuntimeError
from schemas.browser import BrowserViewport


def test_element_registry_keeps_current_page_ids_and_clears_on_navigation():
    registry = ElementRegistry()
    registry.update(_raw("https://example.com/a", ["el_1", "el_2"]))

    registry.require("el_1")

    registry.update(_raw("https://example.com/b", ["el_3"]))

    with pytest.raises(BrowserRuntimeError) as excinfo:
        registry.require("el_1")
    assert excinfo.value.code == "stale_element"
    assert "observe" in excinfo.value.message.lower()
    registry.require("el_3")


def _raw(url: str, ids: list[str]) -> RawPageSnapshot:
    return RawPageSnapshot(
        url=url,
        title="",
        loading=False,
        focused_element_id=None,
        viewport=BrowserViewport(width=1280, height=720),
        tabs=[],
        visible_text="",
        forms=[],
        interactive_elements=[{"id": item} for item in ids],
    )
