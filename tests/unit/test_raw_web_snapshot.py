from __future__ import annotations

from browser.raw_snapshot import parse_accessibility_tree, parse_dom_snapshot
from browser.raw_snapshot_collector import RawSnapshotCollector
from schemas.browser import BrowserTab


def _ax_payload():
    return {
        "nodes": [
            {
                "nodeId": "ax_1",
                "role": {"value": "textbox"},
                "name": {"value": "Password"},
                "value": {"value": "should-not-survive"},
                "backendDOMNodeId": 12,
                "childIds": [],
                "properties": [{"name": "editable", "value": {"value": "plaintext"}}],
            },
            {
                "nodeId": "ax_2",
                "role": {"value": "checkbox"},
                "name": {"value": "Remember me"},
                "value": {"value": True},
                "backendDOMNodeId": 13,
                "parentId": "ax_1",
                "properties": [{"name": "checked", "value": {"value": "true"}}],
            },
        ]
    }


def _dom_payload():
    strings = [
        "#document",
        "HTML",
        "INPUT",
        "",
        "id",
        "password-field",
        "type",
        "password",
        "value",
        "secret",
        "aria-label",
        "Password",
        "data-token",
        "token-secret",
        "https://example.com/login",
        "Login",
        "en",
        "UTF-8",
    ]
    return {
        "strings": strings,
        "documents": [
            {
                "frameId": "frame-main",
                "documentURL": 14,
                "title": 15,
                "baseURL": 14,
                "contentLanguage": 16,
                "encodingName": 17,
                "nodes": {
                    "parentIndex": [-1, 0, 1],
                    "nodeType": [9, 1, 1],
                    "nodeName": [0, 1, 2],
                    "nodeValue": [3, 3, 3],
                    "backendNodeId": [10, 11, 12],
                    "attributes": [[], [], [4, 5, 6, 7, 8, 9, 10, 11, 12, 13]],
                    "isClickable": {"index": [2]},
                },
                "layout": {
                    "nodeIndex": [2],
                    "bounds": [[10, 20, 100, 30]],
                },
            }
        ],
    }


def test_accessibility_tree_sanitizes_editable_values():
    nodes = parse_accessibility_tree(_ax_payload())

    assert len(nodes) == 2
    assert nodes[0].role == "textbox"
    assert nodes[0].value is None
    assert nodes[0].backend_dom_node_id == 12
    assert nodes[1].value is True
    assert nodes[1].parent_id == "ax_1"
    assert nodes[1].properties["checked"] == "true"


def test_dom_snapshot_normalizes_structure_and_allowlists_attributes():
    documents = parse_dom_snapshot(_dom_payload())

    assert len(documents) == 1
    document = documents[0]
    assert document.frame_id == "frame-main"
    assert document.url == "https://example.com/login"
    assert document.title == "Login"
    assert len(document.nodes) == 3

    password = document.nodes[2]
    assert password.backend_node_id == 12
    assert password.node_name == "INPUT"
    assert password.bounds == (10.0, 20.0, 100.0, 30.0)
    assert password.clickable is True
    assert password.attributes == {
        "id": "password-field",
        "type": "password",
        "aria-label": "Password",
    }
    assert "value" not in password.attributes
    assert "data-token" not in password.attributes


class RichFakeHost:
    def evaluate(self, expression: str):
        if expression == "window.location.href":
            return "https://example.com/login"
        if expression == "document.title":
            return "Login"
        if expression == "({ width: window.innerWidth, height: window.innerHeight })":
            return {"width": 1440, "height": 900}
        return {
            "loading": False,
            "focused_element_id": "el_1",
            "visible_text": "Login",
            "interactive_elements": [
                {
                    "id": "el_1",
                    "role": "textbox",
                    "tag": "input",
                    "name": "Password",
                    "value": "secret",
                    "input_type": "password",
                    "visible": True,
                    "enabled": True,
                    "actions": ["type"],
                }
            ],
            "content_blocks": [],
            "forms": [
                {
                    "id": "form_1",
                    "field_details": [
                        {"id": "el_1", "key": "password", "type": "password", "value": "secret"}
                    ],
                }
            ],
            "frames": [],
        }

    def capture_accessibility_tree(self):
        return _ax_payload()

    def capture_dom_snapshot(self):
        return _dom_payload()

    def get_frame_tree(self):
        return [
            {
                "cdp_frame_id": "frame-main",
                "parent_cdp_frame_id": None,
                "url": "https://example.com/login",
                "loader_id": "loader-main",
                "security_origin": "https://example.com",
                "mime_type": "text/html",
            }
        ]


class MinimalFakeHost:
    def evaluate(self, expression: str):
        if expression == "window.location.href":
            return "https://example.com"
        if expression == "document.title":
            return "Example"
        if expression == "({ width: window.innerWidth, height: window.innerHeight })":
            return {"width": 800, "height": 600}
        return {
            "loading": False,
            "visible_text": "Example",
            "interactive_elements": [],
            "content_blocks": [],
            "forms": [],
            "frames": [],
        }


def test_collector_builds_rich_snapshot_and_legacy_projection():
    collector = RawSnapshotCollector(RichFakeHost())
    tabs = [BrowserTab(id="tab_1", url="https://example.com/login", title="Login", active=True)]

    snapshot = collector.collect(tabs=tabs, dialogs=[])

    assert snapshot.url == "https://example.com/login"
    assert snapshot.viewport.width == 1440
    assert len(snapshot.accessibility_nodes) == 2
    assert len(snapshot.dom_documents) == 1
    assert snapshot.engine_frames[0].loader_id == "loader-main"
    assert snapshot.engine_frames[0].security_origin == "https://example.com"
    assert snapshot.evidence_errors == []
    assert snapshot.interactive_elements[0]["value"] == ""
    assert snapshot.forms[0]["field_details"][0]["value"] == ""

    legacy = snapshot.to_page_snapshot()
    assert legacy.url == snapshot.url
    assert legacy.interactive_elements[0]["value"] == ""
    assert legacy.frames[0]["id"] == "frame_1"


def test_collector_degrades_when_engine_evidence_is_unavailable():
    collector = RawSnapshotCollector(MinimalFakeHost())

    snapshot = collector.collect(tabs=[], dialogs=[])

    assert snapshot.visible_text == "Example"
    assert snapshot.accessibility_nodes == []
    assert snapshot.dom_documents == []
    assert snapshot.engine_frames == []
    assert [error.source for error in snapshot.evidence_errors] == [
        "accessibility",
        "dom_snapshot",
        "frame_tree",
    ]
    assert all(error.code == "evidence_unavailable" for error in snapshot.evidence_errors)
