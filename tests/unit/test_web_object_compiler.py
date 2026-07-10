from __future__ import annotations

from browser.raw_snapshot import (
    RawAccessibilityNode,
    RawDOMDocument,
    RawDOMNode,
    RawEvidenceError,
    RawFrameEvidence,
    RawWebSnapshot,
)
from browser.web_object_compiler import WebObjectCompiler
from schemas.browser import BrowserTab, BrowserViewport


def _snapshot(*, login: bool = False, degraded: bool = False) -> RawWebSnapshot:
    url = "https://example.com/login" if login else "https://example.com/search?q=webfa"
    password = {
        "id": "el_password",
        "role": "textbox",
        "tag": "input",
        "name": "Password",
        "text": "",
        "value": "",
        "placeholder": "Password",
        "input_type": "password",
        "visible": True,
        "enabled": True,
        "checked": None,
        "selected": None,
        "href": None,
        "actions": ["click", "type", "clear", "focus", "press"],
    }
    elements = [
        {
            "id": "el_link",
            "role": "link",
            "tag": "a",
            "name": "FeiZhuLulu/webFA",
            "text": "FeiZhuLulu/webFA",
            "value": "",
            "placeholder": "",
            "input_type": None,
            "visible": True,
            "enabled": True,
            "checked": None,
            "selected": None,
            "href": "https://github.com/FeiZhuLulu/webFA",
            "actions": ["click", "focus", "follow_link"],
        },
        {
            "id": "el_search",
            "role": "textbox",
            "tag": "input",
            "name": "Search repositories",
            "text": "",
            "value": "webfa",
            "placeholder": "Search repositories",
            "input_type": "search",
            "visible": True,
            "enabled": True,
            "checked": None,
            "selected": None,
            "href": None,
            "actions": ["click", "type", "clear", "focus", "press"],
        },
        {
            "id": "el_check",
            "role": "checkbox",
            "tag": "input",
            "name": "Include archived",
            "text": "",
            "value": "",
            "placeholder": "",
            "input_type": "checkbox",
            "visible": True,
            "enabled": True,
            "checked": False,
            "selected": None,
            "href": None,
            "actions": ["click", "check", "uncheck", "focus"],
        },
        {
            "id": "el_button",
            "role": "button",
            "tag": "button",
            "name": "Search",
            "text": "Search",
            "value": "",
            "placeholder": "",
            "input_type": None,
            "visible": True,
            "enabled": True,
            "checked": None,
            "selected": None,
            "href": None,
            "actions": ["click", "focus", "activate_control"],
        },
    ]
    if login:
        elements.append(password)

    ax_nodes = [
        RawAccessibilityNode(
            node_id="ax_main",
            role="main",
            name="Main content",
            child_ids=("ax_heading", "ax_search", "ax_link"),
        ),
        RawAccessibilityNode(
            node_id="ax_heading",
            role="heading",
            name="Repository results",
            parent_id="ax_main",
            properties={"level": 1},
            backend_dom_node_id=100,
        ),
        RawAccessibilityNode(
            node_id="ax_search",
            role="textbox",
            name="Search repositories",
            parent_id="ax_main",
            properties={"required": True},
            backend_dom_node_id=101,
        ),
        RawAccessibilityNode(
            node_id="ax_link",
            role="link",
            name="FeiZhuLulu/webFA",
            parent_id="ax_main",
            backend_dom_node_id=102,
        ),
    ]

    dom_nodes = (
        RawDOMNode(
            document_index=0,
            node_index=0,
            backend_node_id=100,
            parent_index=None,
            node_type=1,
            node_name="H1",
            node_value="",
            attributes={},
        ),
        RawDOMNode(
            document_index=0,
            node_index=1,
            backend_node_id=101,
            parent_index=0,
            node_type=1,
            node_name="INPUT",
            node_value="",
            attributes={"type": "search", "placeholder": "Search repositories"},
            bounds=(10.0, 10.0, 300.0, 32.0),
        ),
        RawDOMNode(
            document_index=0,
            node_index=2,
            backend_node_id=102,
            parent_index=0,
            node_type=1,
            node_name="A",
            node_value="",
            attributes={"href": "https://github.com/FeiZhuLulu/webFA"},
            bounds=(10.0, 60.0, 200.0, 24.0),
            clickable=True,
        ),
    )

    return RawWebSnapshot(
        url=url,
        title="Repository search",
        loading=False,
        focused_element_id="el_search",
        viewport=BrowserViewport(width=1280, height=720),
        tabs=[BrowserTab(id="tab_1", url=url, title="Repository search", active=True)],
        visible_text="Login Password" if login else "Repository results FeiZhuLulu/webFA",
        content_blocks=[
            {
                "id": "block_heading",
                "type": "heading",
                "text": "Repository results",
                "element_ids": [],
            },
            {
                "id": "block_nav",
                "type": "nav",
                "text": "Main navigation",
                "element_ids": ["el_link"],
            },
        ],
        forms=[
            {
                "id": "form_search",
                "label": "Repository search",
                "text": "Repository search",
                "fields": ["el_search", "el_check"],
                "field_details": [],
                "submit": "el_button",
            }
        ],
        interactive_elements=elements,
        dialogs=[],
        frames=[
            {
                "id": "frame_1",
                "parent_id": None,
                "url": url,
                "title": "Repository search",
                "same_origin": True,
                "visible": True,
            }
        ],
        accessibility_nodes=ax_nodes,
        dom_documents=[
            RawDOMDocument(
                document_index=0,
                frame_id="cdp-main",
                url=url,
                title="Repository search",
                base_url="https://example.com/",
                content_language="en",
                encoding_name="UTF-8",
                nodes=dom_nodes,
            )
        ],
        engine_frames=[
            RawFrameEvidence(
                frame_id="cdp-main",
                parent_id=None,
                url=url,
                security_origin="https://example.com",
                mime_type="text/html",
            )
        ],
        evidence_errors=(
            [RawEvidenceError(source="dom_snapshot", code="evidence_collection_failed", message="failed")]
            if degraded
            else []
        ),
    )


def _object_by_role(compilation, role: str):
    return [item for item in compilation.state.objects if item.role == role]


def test_compiler_builds_web_objects_outline_regions_and_capabilities():
    compilation = WebObjectCompiler().compile(_snapshot())
    state = compilation.state

    assert state.document_id.startswith("doc_")
    assert state.document_revision == 1
    assert state.object_count == len(state.objects)
    assert _object_by_role(compilation, "document")
    assert _object_by_role(compilation, "frame")
    assert _object_by_role(compilation, "main")
    assert len(_object_by_role(compilation, "heading")) == 1
    assert _object_by_role(compilation, "form")

    assert state.outline[0].level == 1
    assert state.outline[0].name == "Repository results"
    assert any(region.role == "main" for region in state.regions)
    assert any(region.role == "navigation" for region in state.regions)

    link = _object_by_role(compilation, "link")[0]
    assert link.capabilities == ["open", "open_in_new_context"]
    assert link.origin == "https://github.com"

    search = _object_by_role(compilation, "searchbox")[0]
    assert search.capabilities == ["set_value", "clear_value"]
    assert search.state.focused is True
    assert search.state.required is True

    checkbox = _object_by_role(compilation, "checkbox")[0]
    assert checkbox.capabilities == ["toggle"]
    assert checkbox.state.checked is False

    button = _object_by_role(compilation, "button")[0]
    assert button.capabilities == ["activate"]

    forbidden = {"click", "double_click", "type", "press", "focus"}
    assert all(set(item.capabilities).isdisjoint(forbidden) for item in state.objects)


def test_compiler_builds_form_relations_and_content_ownership():
    compilation = WebObjectCompiler().compile(_snapshot())
    form = _object_by_role(compilation, "form")[0]
    search = _object_by_role(compilation, "searchbox")[0]
    checkbox = _object_by_role(compilation, "checkbox")[0]
    button = _object_by_role(compilation, "button")[0]
    link = _object_by_role(compilation, "link")[0]
    navigation = _object_by_role(compilation, "navigation")[0]
    root_frame = _object_by_role(compilation, "frame")[0]

    assert form.capabilities == ["submit"]
    assert form.relations.submit_control == button.id
    assert {search.id, checkbox.id, button.id}.issubset(set(form.relations.children))
    assert search.relations.form == form.id
    assert checkbox.relations.form == form.id
    assert link.id in navigation.relations.children
    assert link.relations.belongs_to == navigation.id
    assert form.relations.parent == root_frame.id
    assert search.relations.parent == root_frame.id


def test_compiler_records_internal_provenance_without_exposing_it_in_web_state():
    compilation = WebObjectCompiler().compile(_snapshot())
    search = _object_by_role(compilation, "searchbox")[0]
    evidence = compilation.provenance[search.id]

    assert evidence.ax_node_id == "ax_search"
    assert evidence.backend_dom_node_id == 101
    assert evidence.dom_node_index == 1
    assert "provenance" not in compilation.state.model_dump()
    assert "backend_dom_node_id" not in compilation.state.model_dump_json()


def test_compiler_converts_auth_state_to_human_takeover():
    compilation = WebObjectCompiler().compile(_snapshot(login=True))

    assert compilation.state.auth.surface_detected is True
    assert compilation.state.takeover.required is True
    assert compilation.state.takeover.reason == "authentication"
    password = next(item for item in compilation.state.objects if item.name == "Password")
    assert password.value == ""
    assert password.capabilities == ["request_human_takeover"]
    assert compilation.state.takeover.target == password.id


def test_compiler_marks_cross_origin_child_frames():
    snapshot = _snapshot()
    snapshot.frames.append(
        {
            "id": "frame_2",
            "parent_id": "frame_1",
            "url": "https://other.example/embed",
            "title": "External frame",
            "same_origin": False,
            "visible": True,
        }
    )

    compilation = WebObjectCompiler().compile(snapshot)
    frames = _object_by_role(compilation, "frame")
    external = next(item for item in frames if item.name == "External frame")
    root_frame = next(item for item in frames if item.name == "Repository search")

    assert external.security.cross_origin is True
    assert external.origin == "https://other.example"
    assert external.relations.parent == root_frame.id


def test_compiler_exposes_pending_javascript_dialog_as_transient_object():
    snapshot = _snapshot()
    snapshot.dialogs = [
        {
            "id": "dialog_1",
            "type": "confirm",
            "message": "Delete item?",
            "default_value": "",
            "user_action_required": False,
        }
    ]

    compilation = WebObjectCompiler().compile(snapshot)
    dialog = next(item for item in _object_by_role(compilation, "dialog") if item.name == "Delete item?")

    assert dialog.capabilities == ["dismiss"]
    assert dialog.lifetime == "transient"


def test_compiler_preserves_duplicate_same_name_headings():
    snapshot = _snapshot()
    snapshot.accessibility_nodes.append(
        RawAccessibilityNode(
            node_id="ax_heading_2",
            role="heading",
            name="Repository results",
            parent_id="ax_main",
            properties={"level": 2},
            backend_dom_node_id=103,
        )
    )

    compilation = WebObjectCompiler().compile(snapshot)
    headings = _object_by_role(compilation, "heading")

    assert len(headings) == 2
    assert [item.level for item in compilation.state.outline] == [1, 2]


def test_compiler_reports_partial_evidence_without_exposing_raw_failure_details():
    compilation = WebObjectCompiler().compile(_snapshot(degraded=True))

    assert len(compilation.state.errors) == 1
    assert compilation.state.errors[0].code == "compiler_evidence_degraded"
    serialized = compilation.state.model_dump_json()
    assert "dom_snapshot" not in serialized
    assert "evidence_collection_failed" not in serialized
