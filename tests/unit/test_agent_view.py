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


def test_agent_view_builder_maps_raw_content_blocks_into_typed_schema():
    state = AgentViewBuilder().build(
        RawPageSnapshot(
            url="https://github.com/search?q=webfa&type=repositories",
            title="Search",
            loading=False,
            focused_element_id=None,
            viewport=BrowserViewport(width=1280, height=720),
            tabs=[],
            visible_text="alpha/webfa-one First repository description",
            content_blocks=[
                {"id": "block_1", "type": "heading", "text": "alpha/webfa-one", "element_ids": ["el_7"]},
                {"id": "block_2", "type": "paragraph", "text": "First repository description", "element_ids": []},
            ],
            forms=[],
            interactive_elements=[],
        )
    )

    blocks = state.content_blocks
    assert [b.id for b in blocks] == ["block_1", "block_2"]
    assert blocks[0].type == "heading"
    assert blocks[0].text == "alpha/webfa-one"
    assert blocks[0].element_ids == ["el_7"]
    assert blocks[1].element_ids == []


def test_agent_view_builder_content_blocks_default_empty_when_raw_missing():
    state = AgentViewBuilder().build(
        RawPageSnapshot(
            url="https://example.com",
            title="Example",
            loading=False,
            focused_element_id=None,
            viewport=BrowserViewport(width=1280, height=720),
            tabs=[],
            visible_text="",
        )
    )

    assert state.content_blocks == []


def test_content_block_serializes_to_stable_json_shape():
    state = AgentViewBuilder().build(
        RawPageSnapshot(
            url="https://example.com",
            title="Example",
            loading=False,
            focused_element_id=None,
            viewport=BrowserViewport(width=1280, height=720),
            tabs=[],
            visible_text="",
            content_blocks=[
                {"id": "block_1", "type": "list_item", "text": "a result", "element_ids": ["el_3", "el_4"]},
            ],
        )
    )
    dumped = state.model_dump()["content_blocks"]
    assert dumped == [{"id": "block_1", "type": "list_item", "text": "a result", "element_ids": ["el_3", "el_4"]}]


def test_content_block_rejects_html_or_dom_fields():
    """A raw block carrying html/outerHTML must not survive into the typed schema."""
    from pydantic import ValidationError

    from schemas.browser import BrowserContentBlock

    for forbidden in ("html", "outerHTML", "innerHTML", "dom_path"):
        try:
            BrowserContentBlock(id="block_1", type="paragraph", text="x", element_ids=[], **{forbidden: "<x>"})
        except ValidationError:
            continue
        raise AssertionError(f"{forbidden} must be rejected by BrowserContentBlock")
