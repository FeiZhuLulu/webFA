from browser.agent_view import AgentViewBuilder
from browser.driver import VISIBLE_TEXT_MAX_CHARS, RawPageSnapshot
from schemas.browser import BrowserTab, BrowserViewport


def test_agent_view_builder_creates_browser_state_with_url_parts():
    state = AgentViewBuilder().build(
        RawPageSnapshot(
            url="https://github.com/search?q=text&type=repositories",
            title="Repository search results",
            loading=False,
            focused_element_id="el_1",
            viewport=BrowserViewport(width=1280, height=720),
            tabs=[BrowserTab(id="tab_1", url="https://github.com", title="GitHub", active=True)],
            visible_text="Search results",
            forms=[{"id": "form_1", "fields": ["el_1"], "submit": None}],
            interactive_elements=[{
                "id": "el_1",
                "role": "textbox",
                "tag": "input",
                "name": "Search",
                "visible": True,
                "enabled": True,
                "actions": ["type", "press"],
            }],
        )
    )

    assert state.url_parts.query == {"q": "text", "type": "repositories"}
    assert state.forms[0].id == "form_1"
    assert state.interactive_elements[0].id == "el_1"


def test_agent_view_builder_limits_visible_text_with_runtime_constant():
    state = AgentViewBuilder().build(
        RawPageSnapshot(
            url="https://example.com",
            title="Example",
            loading=False,
            focused_element_id=None,
            viewport=BrowserViewport(width=1280, height=720),
            tabs=[],
            visible_text="x" * (VISIBLE_TEXT_MAX_CHARS + 1),
            forms=[],
            interactive_elements=[],
        )
    )

    assert len(state.visible_text) == VISIBLE_TEXT_MAX_CHARS
    assert "full_dom" not in state.model_dump()
    assert "full_html" not in state.model_dump()
