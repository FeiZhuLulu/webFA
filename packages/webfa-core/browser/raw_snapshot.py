from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from browser.driver import RawPageSnapshot
from schemas.browser import BrowserTab, BrowserViewport


SAFE_DOM_ATTRIBUTES = frozenset(
    {
        "id",
        "class",
        "role",
        "aria-label",
        "aria-labelledby",
        "aria-describedby",
        "aria-expanded",
        "aria-selected",
        "aria-checked",
        "aria-disabled",
        "aria-hidden",
        "title",
        "placeholder",
        "name",
        "type",
        "href",
        "src",
        "alt",
        "tabindex",
        "contenteditable",
        "disabled",
        "required",
        "checked",
        "selected",
        "multiple",
    }
)

SENSITIVE_AX_VALUE_ROLES = frozenset({"textbox", "searchbox", "combobox"})
SENSITIVE_AX_PROPERTY_NAMES = frozenset({"value", "valuetext"})
RAW_TEXT_MAX_CHARS = 2000


@dataclass(frozen=True)
class RawEvidenceError:
    source: str
    code: str
    message: str
    recoverable: bool = True


@dataclass(frozen=True)
class RawAccessibilityNode:
    node_id: str
    ignored: bool = False
    role: str = ""
    name: str = ""
    description: str = ""
    value: Any = None
    backend_dom_node_id: int | None = None
    parent_id: str | None = None
    child_ids: tuple[str, ...] = ()
    frame_id: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    ignored_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class RawDOMNode:
    document_index: int
    node_index: int
    backend_node_id: int | None
    parent_index: int | None
    node_type: int | None
    node_name: str
    node_value: str
    attributes: dict[str, str] = field(default_factory=dict)
    bounds: tuple[float, float, float, float] | None = None
    clickable: bool = False
    shadow_root_type: str | None = None
    content_document_index: int | None = None


@dataclass(frozen=True)
class RawDOMDocument:
    document_index: int
    frame_id: str
    url: str
    title: str
    base_url: str
    content_language: str
    encoding_name: str
    nodes: tuple[RawDOMNode, ...] = ()


@dataclass(frozen=True)
class RawFrameEvidence:
    frame_id: str
    parent_id: str | None
    url: str
    name: str = ""
    security_origin: str = ""
    mime_type: str = ""
    unreachable_url: str = ""


@dataclass
class RawWebSnapshot:
    url: str
    title: str
    loading: bool
    focused_element_id: str | None
    viewport: BrowserViewport
    tabs: list[BrowserTab]
    visible_text: str
    content_blocks: list[dict] = field(default_factory=list)
    forms: list[dict] = field(default_factory=list)
    interactive_elements: list[dict] = field(default_factory=list)
    dialogs: list[dict] = field(default_factory=list)
    frames: list[dict] = field(default_factory=list)
    accessibility_nodes: list[RawAccessibilityNode] = field(default_factory=list)
    dom_documents: list[RawDOMDocument] = field(default_factory=list)
    engine_frames: list[RawFrameEvidence] = field(default_factory=list)
    evidence_errors: list[RawEvidenceError] = field(default_factory=list)
    collected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_page_snapshot(self) -> RawPageSnapshot:
        """Project the richer P10 snapshot onto the current BrowserState input."""

        return RawPageSnapshot(
            url=self.url,
            title=self.title,
            loading=self.loading,
            focused_element_id=self.focused_element_id,
            viewport=self.viewport,
            tabs=self.tabs,
            visible_text=self.visible_text,
            content_blocks=self.content_blocks,
            forms=self.forms,
            interactive_elements=self.interactive_elements,
            dialogs=self.dialogs,
            frames=self.frames,
        )


class RawWebSnapshotDriver(Protocol):
    def observe_web_raw(self) -> RawWebSnapshot: ...


def parse_accessibility_tree(payload: dict[str, Any]) -> list[RawAccessibilityNode]:
    nodes = payload.get("nodes", [])
    if not isinstance(nodes, list):
        raise ValueError("Accessibility.getFullAXTree returned invalid nodes")

    parsed: list[RawAccessibilityNode] = []
    for item in nodes:
        if not isinstance(item, dict):
            continue
        node_id = str(item.get("nodeId", ""))
        if not node_id:
            continue
        role = str(_cdp_value(item.get("role")) or "")
        value = None if role.lower() in SENSITIVE_AX_VALUE_ROLES else _cdp_value(item.get("value"))
        properties: dict[str, Any] = {}
        for prop in item.get("properties", []):
            if not isinstance(prop, dict):
                continue
            name = str(prop.get("name", ""))
            if name and name.lower() not in SENSITIVE_AX_PROPERTY_NAMES:
                properties[name] = _cdp_value(prop.get("value"))
        ignored_reasons = tuple(
            str(reason.get("name", ""))
            for reason in item.get("ignoredReasons", [])
            if isinstance(reason, dict) and reason.get("name")
        )
        backend_id = item.get("backendDOMNodeId")
        parsed.append(
            RawAccessibilityNode(
                node_id=node_id,
                ignored=bool(item.get("ignored", False)),
                role=role,
                name=str(_cdp_value(item.get("name")) or ""),
                description=str(_cdp_value(item.get("description")) or ""),
                value=value,
                backend_dom_node_id=int(backend_id) if isinstance(backend_id, int) else None,
                parent_id=str(item.get("parentId")) if item.get("parentId") else None,
                child_ids=tuple(str(value) for value in item.get("childIds", []) if value),
                frame_id=str(item.get("frameId")) if item.get("frameId") else None,
                properties=properties,
                ignored_reasons=ignored_reasons,
            )
        )
    return parsed


def parse_dom_snapshot(payload: dict[str, Any]) -> list[RawDOMDocument]:
    strings = payload.get("strings", [])
    documents = payload.get("documents", [])
    if not isinstance(strings, list) or not isinstance(documents, list):
        raise ValueError("DOMSnapshot.captureSnapshot returned invalid payload")

    normalized_strings = [str(value) for value in strings]
    parsed_documents: list[RawDOMDocument] = []
    for document_index, document in enumerate(documents):
        if not isinstance(document, dict):
            continue
        node_tree = document.get("nodes", {})
        layout = document.get("layout", {})
        if not isinstance(node_tree, dict) or not isinstance(layout, dict):
            continue

        node_names = node_tree.get("nodeName", [])
        if not isinstance(node_names, list):
            continue
        node_count = len(node_names)
        layout_bounds = _layout_bounds_by_node(layout)
        clickable_nodes = _rare_boolean_indices(node_tree.get("isClickable"))
        shadow_roots = _rare_string_values(node_tree.get("shadowRootType"), normalized_strings)
        content_documents = _rare_integer_values(node_tree.get("contentDocumentIndex"))

        nodes: list[RawDOMNode] = []
        for node_index in range(node_count):
            backend_node_id = _array_int(node_tree.get("backendNodeId"), node_index)
            parent_index = _array_int(node_tree.get("parentIndex"), node_index)
            node_type = _array_int(node_tree.get("nodeType"), node_index)
            node_name = _string_at(normalized_strings, _array_int(node_names, node_index))
            node_value = _string_at(normalized_strings, _array_int(node_tree.get("nodeValue"), node_index))
            attributes = _safe_attributes(node_tree.get("attributes"), node_index, normalized_strings)
            nodes.append(
                RawDOMNode(
                    document_index=document_index,
                    node_index=node_index,
                    backend_node_id=backend_node_id,
                    parent_index=parent_index,
                    node_type=node_type,
                    node_name=node_name,
                    node_value=node_value[:RAW_TEXT_MAX_CHARS],
                    attributes=attributes,
                    bounds=layout_bounds.get(node_index),
                    clickable=node_index in clickable_nodes,
                    shadow_root_type=shadow_roots.get(node_index),
                    content_document_index=content_documents.get(node_index),
                )
            )

        parsed_documents.append(
            RawDOMDocument(
                document_index=document_index,
                frame_id=str(document.get("frameId", "")),
                url=_string_at(normalized_strings, _optional_index(document.get("documentURL"))),
                title=_string_at(normalized_strings, _optional_index(document.get("title"))),
                base_url=_string_at(normalized_strings, _optional_index(document.get("baseURL"))),
                content_language=_string_at(normalized_strings, _optional_index(document.get("contentLanguage"))),
                encoding_name=_string_at(normalized_strings, _optional_index(document.get("encodingName"))),
                nodes=tuple(nodes),
            )
        )
    return parsed_documents


def parse_frame_tree(items: list[dict[str, Any]]) -> list[RawFrameEvidence]:
    parsed: list[RawFrameEvidence] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        frame_id = str(item.get("cdp_frame_id") or item.get("frame_id") or "")
        if not frame_id:
            continue
        parent = item.get("parent_cdp_frame_id") or item.get("parent_id")
        parsed.append(
            RawFrameEvidence(
                frame_id=frame_id,
                parent_id=str(parent) if parent else None,
                url=str(item.get("url", "")),
                name=str(item.get("name", "")),
                security_origin=str(item.get("security_origin", "")),
                mime_type=str(item.get("mime_type", "")),
                unreachable_url=str(item.get("unreachable_url", "")),
            )
        )
    return parsed


def _cdp_value(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return None


def _optional_index(value: Any) -> int | None:
    return int(value) if isinstance(value, int) and value >= 0 else None


def _array_int(values: Any, index: int) -> int | None:
    if not isinstance(values, list) or index >= len(values):
        return None
    value = values[index]
    return int(value) if isinstance(value, int) else None


def _string_at(strings: list[str], index: int | None) -> str:
    if index is None or index < 0 or index >= len(strings):
        return ""
    return strings[index]


def _safe_attributes(values: Any, index: int, strings: list[str]) -> dict[str, str]:
    if not isinstance(values, list) or index >= len(values):
        return {}
    raw = values[index]
    if not isinstance(raw, list):
        return {}
    attributes: dict[str, str] = {}
    for offset in range(0, len(raw) - 1, 2):
        name = _string_at(strings, _optional_index(raw[offset])).lower()
        if name not in SAFE_DOM_ATTRIBUTES:
            continue
        attributes[name] = _string_at(strings, _optional_index(raw[offset + 1]))[:RAW_TEXT_MAX_CHARS]
    return attributes


def _layout_bounds_by_node(layout: dict[str, Any]) -> dict[int, tuple[float, float, float, float]]:
    node_indices = layout.get("nodeIndex", [])
    bounds = layout.get("bounds", [])
    if not isinstance(node_indices, list) or not isinstance(bounds, list):
        return {}
    result: dict[int, tuple[float, float, float, float]] = {}
    for position, node_index in enumerate(node_indices):
        if not isinstance(node_index, int) or position >= len(bounds):
            continue
        raw_bounds = bounds[position]
        if not isinstance(raw_bounds, list) or len(raw_bounds) < 4:
            continue
        try:
            result[node_index] = tuple(float(value) for value in raw_bounds[:4])  # type: ignore[assignment]
        except (TypeError, ValueError):
            continue
    return result


def _rare_boolean_indices(value: Any) -> set[int]:
    if not isinstance(value, dict):
        return set()
    indices = value.get("index", [])
    return {int(index) for index in indices if isinstance(index, int)} if isinstance(indices, list) else set()


def _rare_integer_values(value: Any) -> dict[int, int]:
    if not isinstance(value, dict):
        return {}
    indices = value.get("index", [])
    values = value.get("value", [])
    if not isinstance(indices, list) or not isinstance(values, list):
        return {}
    result: dict[int, int] = {}
    for offset, index in enumerate(indices):
        if not isinstance(index, int) or offset >= len(values) or not isinstance(values[offset], int):
            continue
        result[index] = int(values[offset])
    return result


def _rare_string_values(value: Any, strings: list[str]) -> dict[int, str]:
    integer_values = _rare_integer_values(value)
    return {index: _string_at(strings, string_index) for index, string_index in integer_values.items()}
