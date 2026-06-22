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


def test_agent_view_detects_auth_surface_and_hides_password_value():
    state = AgentViewBuilder().build(
        RawPageSnapshot(
            url="https://example.com/login",
            title="Sign in",
            loading=False,
            focused_element_id=None,
            viewport=BrowserViewport(width=1280, height=720),
            tabs=[],
            visible_text="Sign in with password or verification code",
            forms=[
                {
                    "id": "form_1",
                    "fields": ["el_1", "el_2"],
                    "field_details": [
                        {"id": "el_1", "key": "email", "type": "email", "value": "user@example.com"},
                        {"id": "el_2", "key": "password", "type": "password", "value": "secret"},
                    ],
                    "submit": "el_3",
                }
            ],
            interactive_elements=[
                {
                    "id": "el_1",
                    "role": "textbox",
                    "tag": "input",
                    "name": "Email",
                    "value": "user@example.com",
                    "input_type": "email",
                    "visible": True,
                    "enabled": True,
                    "actions": ["type"],
                },
                {
                    "id": "el_2",
                    "role": "textbox",
                    "tag": "input",
                    "name": "Password",
                    "value": "secret",
                    "input_type": "password",
                    "visible": True,
                    "enabled": True,
                    "actions": ["type"],
                },
            ],
        )
    )

    assert state.auth.surface_detected is True
    assert "password_input" in state.auth.reason
    assert state.auth.user_action_required is True
    assert state.interactive_elements[1].value == ""
    assert state.forms[0].field_details[1].value == ""


def test_agent_view_detects_qr_auth_text_but_not_plain_contact_form():
    qr_state = AgentViewBuilder().build(
        RawPageSnapshot(
            url="https://example.com/account",
            title="Account",
            loading=False,
            focused_element_id=None,
            viewport=BrowserViewport(width=1280, height=720),
            tabs=[],
            visible_text="请使用手机扫码登录，或输入验证码完成登录",
        )
    )
    plain_state = AgentViewBuilder().build(
        RawPageSnapshot(
            url="https://example.com/contact",
            title="Contact",
            loading=False,
            focused_element_id=None,
            viewport=BrowserViewport(width=1280, height=720),
            tabs=[],
            visible_text="Contact us Name Email Message Submit",
            interactive_elements=[
                {
                    "id": "el_1",
                    "role": "textbox",
                    "tag": "input",
                    "name": "Email",
                    "input_type": "email",
                    "visible": True,
                    "enabled": True,
                    "actions": ["type"],
                }
            ],
        )
    )

    assert qr_state.auth.surface_detected is True
    assert "human_auth_text" in qr_state.auth.reason
    assert plain_state.auth.surface_detected is False


def test_agent_view_does_not_flag_logged_in_inbox_text_as_auth():
    state = AgentViewBuilder().build(
        RawPageSnapshot(
            url="https://wx.mail.qq.com/list/readtemplate",
            title="QQ Mail Inbox",
            loading=False,
            focused_element_id=None,
            viewport=BrowserViewport(width=1280, height=720),
            tabs=[],
            visible_text="收件箱 322 封未读 GitHub verification code 邮件提醒 密码安全通知",
            content_blocks=[
                {
                    "id": "block_1",
                    "type": "list_item",
                    "text": "GitHub verification code 邮件提醒 密码安全通知",
                    "element_ids": ["el_1"],
                }
            ],
            interactive_elements=[
                {
                    "id": "el_1",
                    "role": "div",
                    "tag": "div",
                    "name": "GitHub verification code 邮件提醒",
                    "visible": True,
                    "enabled": True,
                    "actions": ["click", "focus"],
                }
            ],
        )
    )

    assert state.auth.surface_detected is False
