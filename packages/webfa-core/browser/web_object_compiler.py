from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from browser.agent_view import AgentViewBuilder
from browser.raw_snapshot import RawAccessibilityNode, RawDOMNode, RawFrameEvidence, RawWebSnapshot
from schemas.browser import BrowserAgentState, BrowserStateError
from schemas.web import (
    HumanTakeoverState,
    ObjectCapabilityName,
    ObjectCategory,
    ObjectRole,
    WebObject,
    WebObjectObservable,
    WebObjectRelations,
    WebObjectSecurity,
    WebObjectState,
    WebOutlineItem,
    WebRegionRef,
    WebState,
)


@dataclass(frozen=True)
class WebObjectProvenance:
    sources: tuple[str, ...]
    compiler_rules: tuple[str, ...]
    legacy_id: str | None = None
    engine_frame_id: str | None = None
    ax_node_id: str | None = None
    backend_dom_node_id: int | None = None
    dom_document_index: int | None = None
    dom_node_index: int | None = None


@dataclass
class WebObjectCompilation:
    state: WebState
    provenance: dict[str, WebObjectProvenance] = field(default_factory=dict)


@dataclass(frozen=True)
class _RoleSpec:
    category: ObjectCategory
    role: ObjectRole


_AX_ROLE_SPECS: dict[str, _RoleSpec] = {
    "main": _RoleSpec("container", "main"),
    "navigation": _RoleSpec("container", "navigation"),
    "banner": _RoleSpec("container", "header"),
    "contentinfo": _RoleSpec("container", "footer"),
    "region": _RoleSpec("container", "region"),
    "section": _RoleSpec("container", "section"),
    "article": _RoleSpec("container", "article"),
    "complementary": _RoleSpec("container", "complementary"),
    "heading": _RoleSpec("content", "heading"),
    "paragraph": _RoleSpec("content", "paragraph"),
    "list": _RoleSpec("collection", "list"),
    "listitem": _RoleSpec("collection", "list_item"),
    "table": _RoleSpec("collection", "table"),
    "grid": _RoleSpec("collection", "table"),
    "row": _RoleSpec("collection", "row"),
    "cell": _RoleSpec("collection", "cell"),
    "gridcell": _RoleSpec("collection", "cell"),
    "columnheader": _RoleSpec("collection", "cell"),
    "rowheader": _RoleSpec("collection", "cell"),
    "tree": _RoleSpec("collection", "tree"),
    "treeitem": _RoleSpec("collection", "tree_item"),
    "feed": _RoleSpec("collection", "feed"),
    "dialog": _RoleSpec("dialog", "dialog"),
    "alertdialog": _RoleSpec("dialog", "dialog"),
    "alert": _RoleSpec("dialog", "alert"),
    "status": _RoleSpec("dialog", "status"),
    "toolbar": _RoleSpec("container", "toolbar"),
}

_BLOCK_ROLE_SPECS: dict[str, _RoleSpec] = {
    "heading": _RoleSpec("content", "heading"),
    "paragraph": _RoleSpec("content", "paragraph"),
    "list_item": _RoleSpec("collection", "list_item"),
    "nav": _RoleSpec("container", "navigation"),
    "form": _RoleSpec("container", "section"),
    "generic": _RoleSpec("content", "text"),
}

_REGION_ROLES = {"main", "region", "navigation", "header", "footer", "complementary"}
_EDITABLE_ROLES = {"field", "searchbox", "textbox", "textarea"}


class WebObjectCompiler:
    """Deterministically compile RawWebSnapshot evidence into agent WebObjects."""

    def __init__(self) -> None:
        self._legacy_builder = AgentViewBuilder()

    def compile(
        self,
        snapshot: RawWebSnapshot,
        *,
        session_id: str = "default",
        agent: BrowserAgentState | None = None,
    ) -> WebObjectCompilation:
        legacy_state = self._legacy_builder.build(snapshot.to_page_snapshot(), session_id=session_id)
        origin = _origin_of(snapshot.url)
        document_id = _document_id(snapshot)
        objects: dict[str, WebObject] = {}
        provenance: dict[str, WebObjectProvenance] = {}
        allocator = _ObjectIdAllocator()
        semantic_keys: dict[tuple[str, str], list[str]] = {}
        ax_to_object: dict[str, str] = {}
        heading_levels: dict[str, int] = {}

        document_object_id = allocator.allocate("document")
        document_object = WebObject(
            id=document_object_id,
            category="document",
            role="document",
            name=snapshot.title,
            text="",
            state=WebObjectState(visible=True, enabled=True),
            relations=WebObjectRelations(),
            origin=origin,
            lifetime="document",
            security=WebObjectSecurity(content_trust="untrusted", cross_origin=False),
        )
        objects[document_object_id] = document_object
        provenance[document_object_id] = WebObjectProvenance(
            sources=("runtime",),
            compiler_rules=("document_root",),
        )

        frame_object_ids, frame_id_map = self._compile_frames(
            snapshot,
            objects,
            provenance,
            allocator,
            document_object_id,
        )
        root_frame_id = _root_frame_id(snapshot)

        self._compile_ax_structure(
            snapshot,
            objects,
            provenance,
            allocator,
            semantic_keys,
            ax_to_object,
            heading_levels,
            document_object_id,
            frame_object_ids,
            frame_id_map,
            root_frame_id,
            origin,
        )

        block_object_ids = self._compile_content_blocks(
            snapshot,
            objects,
            provenance,
            allocator,
            semantic_keys,
            document_object_id,
            frame_object_ids,
            root_frame_id,
            origin,
        )

        legacy_to_object = self._compile_interactive_elements(
            snapshot,
            objects,
            provenance,
            allocator,
            document_object_id,
            frame_object_ids,
            frame_id_map,
            root_frame_id,
            origin,
        )

        self._compile_forms(
            snapshot,
            objects,
            provenance,
            allocator,
            legacy_to_object,
            document_object_id,
            frame_object_ids,
            root_frame_id,
            origin,
        )

        self._bind_content_blocks(
            snapshot,
            objects,
            block_object_ids,
            legacy_to_object,
        )
        self._bind_ax_structure(
            snapshot,
            objects,
            ax_to_object,
            document_object_id,
            frame_object_ids,
            frame_id_map,
        )
        self._compile_javascript_dialogs(
            snapshot,
            objects,
            provenance,
            allocator,
            document_object_id,
            origin,
        )

        self._attach_document_children(objects, document_object_id)
        outline = self._build_outline(objects, heading_levels)
        regions = self._build_regions(objects)
        password_target = next(
            (
                legacy_to_object.get(str(element.get("id", "")))
                for element in snapshot.interactive_elements
                if isinstance(element, dict) and str(element.get("input_type", "")).lower() == "password"
            ),
            None,
        )
        takeover = _takeover_from_auth(legacy_state.auth, origin, password_target)
        errors = _compiler_errors(snapshot)

        state = WebState(
            session_id=session_id,
            document_id=document_id,
            document_revision=1,
            url=snapshot.url,
            title=snapshot.title,
            status="loading" if snapshot.loading else "idle",
            outline=outline,
            regions=regions,
            objects=list(objects.values()),
            object_count=len(objects),
            frames=legacy_state.frames,
            dialogs=legacy_state.dialogs,
            auth=legacy_state.auth,
            takeover=takeover,
            security=legacy_state.security,
            agent=agent or BrowserAgentState(),
            errors=errors,
        )
        return WebObjectCompilation(state=state, provenance=provenance)

    def _compile_frames(
        self,
        snapshot: RawWebSnapshot,
        objects: dict[str, WebObject],
        provenance: dict[str, WebObjectProvenance],
        allocator: "_ObjectIdAllocator",
        document_object_id: str,
    ) -> tuple[dict[str, str], dict[str, str]]:
        frame_object_ids: dict[str, str] = {}
        frame_id_map: dict[str, str] = {}
        engine_by_legacy = _match_engine_frames(snapshot)
        for legacy_id, engine_frame in engine_by_legacy.items():
            frame_id_map[engine_frame.frame_id] = legacy_id

        for frame in snapshot.frames:
            if not isinstance(frame, dict):
                continue
            frame_id = str(frame.get("id", ""))
            if not frame_id:
                continue
            object_id = allocator.allocate(f"frame_{frame_id}")
            parent_frame_id = frame.get("parent_id")
            parent_object_id = frame_object_ids.get(str(parent_frame_id)) if parent_frame_id else document_object_id
            same_origin = bool(frame.get("same_origin", True))
            objects[object_id] = WebObject(
                id=object_id,
                category="frame",
                role="frame",
                name=str(frame.get("title", "")),
                description=str(frame.get("url", "")),
                state=WebObjectState(visible=bool(frame.get("visible", True)), enabled=True),
                relations=WebObjectRelations(parent=parent_object_id),
                origin=_origin_of(str(frame.get("url", ""))),
                frame_id=frame_id,
                lifetime="frame",
                security=WebObjectSecurity(content_trust="untrusted", cross_origin=not same_origin),
            )
            engine_frame = engine_by_legacy.get(frame_id)
            provenance[object_id] = WebObjectProvenance(
                sources=("probe_frame", "engine_frame") if engine_frame else ("probe_frame",),
                compiler_rules=("frame_metadata",),
                legacy_id=frame_id,
                engine_frame_id=engine_frame.frame_id if engine_frame else None,
            )
            frame_object_ids[frame_id] = object_id
        return frame_object_ids, frame_id_map

    def _compile_ax_structure(
        self,
        snapshot: RawWebSnapshot,
        objects: dict[str, WebObject],
        provenance: dict[str, WebObjectProvenance],
        allocator: "_ObjectIdAllocator",
        semantic_keys: dict[tuple[str, str], list[str]],
        ax_to_object: dict[str, str],
        heading_levels: dict[str, int],
        document_object_id: str,
        frame_object_ids: dict[str, str],
        frame_id_map: dict[str, str],
        root_frame_id: str | None,
        origin: str,
    ) -> None:
        for node in snapshot.accessibility_nodes:
            if node.ignored:
                continue
            role_key = _normalize_role(node.role)
            spec = _AX_ROLE_SPECS.get(role_key)
            if spec is None:
                continue
            name = node.name.strip()
            if spec.role in {"heading", "paragraph", "list_item", "cell"} and not name:
                continue
            semantic_key = (spec.role, _norm(name))
            object_id = allocator.allocate(f"ax_{node.node_id}")
            frame_id = frame_id_map.get(node.frame_id or "", node.frame_id) or root_frame_id
            parent = frame_object_ids.get(frame_id or "", document_object_id)
            state = _state_from_ax(node)
            capabilities = _capabilities_for_ax(spec.role, state)
            objects[object_id] = WebObject(
                id=object_id,
                category=spec.category,
                role=spec.role,
                name=name,
                description=node.description,
                value=_safe_web_value(node.value),
                state=state,
                relations=WebObjectRelations(parent=parent),
                capabilities=capabilities,
                origin=origin,
                frame_id=frame_id,
                lifetime="frame" if frame_id and frame_id != "frame_1" else "document",
                security=WebObjectSecurity(content_trust="untrusted", cross_origin=False),
                observable=WebObjectObservable(
                    inspectable=True,
                    range_readable=spec.role in {"list", "table", "tree", "feed"},
                ),
            )
            provenance[object_id] = WebObjectProvenance(
                sources=("accessibility",),
                compiler_rules=(f"ax_role:{role_key}",),
                ax_node_id=node.node_id,
                backend_dom_node_id=node.backend_dom_node_id,
            )
            ax_to_object[node.node_id] = object_id
            if name:
                semantic_keys.setdefault(semantic_key, []).append(object_id)
            if spec.role == "heading":
                heading_levels[object_id] = _heading_level(node)

    def _compile_content_blocks(
        self,
        snapshot: RawWebSnapshot,
        objects: dict[str, WebObject],
        provenance: dict[str, WebObjectProvenance],
        allocator: "_ObjectIdAllocator",
        semantic_keys: dict[tuple[str, str], list[str]],
        document_object_id: str,
        frame_object_ids: dict[str, str],
        root_frame_id: str | None,
        origin: str,
    ) -> dict[str, str]:
        block_object_ids: dict[str, str] = {}
        matched_candidate_counts: dict[tuple[str, str], int] = {}
        for block in snapshot.content_blocks:
            if not isinstance(block, dict):
                continue
            block_id = str(block.get("id", ""))
            block_type = str(block.get("type", "generic"))
            spec = _BLOCK_ROLE_SPECS.get(block_type, _BLOCK_ROLE_SPECS["generic"])
            text = str(block.get("text", "")).strip()
            name = text if spec.role in {"heading", "navigation", "list_item"} else ""
            semantic_key = (spec.role, _norm(name or text))
            candidates = semantic_keys.get(semantic_key, []) if (name or text) else []
            candidate_index = matched_candidate_counts.get(semantic_key, 0)
            existing = candidates[candidate_index] if candidate_index < len(candidates) else None
            if existing:
                matched_candidate_counts[semantic_key] = candidate_index + 1
            if existing:
                block_object_ids[block_id] = existing
                previous = provenance.get(existing)
                if previous is not None and "content_block" not in previous.sources:
                    provenance[existing] = WebObjectProvenance(
                        sources=previous.sources + ("content_block",),
                        compiler_rules=previous.compiler_rules + (f"block_type:{block_type}",),
                        legacy_id=block_id,
                        engine_frame_id=previous.engine_frame_id,
                        ax_node_id=previous.ax_node_id,
                        backend_dom_node_id=previous.backend_dom_node_id,
                        dom_document_index=previous.dom_document_index,
                        dom_node_index=previous.dom_node_index,
                    )
                continue

            frame_id = str(block.get("frame_id", "")) or root_frame_id
            parent = frame_object_ids.get(frame_id or "", document_object_id)
            object_id = allocator.allocate(block_id or f"block_{len(block_object_ids) + 1}")
            objects[object_id] = WebObject(
                id=object_id,
                category=spec.category,
                role=spec.role,
                name=name,
                text=text,
                state=WebObjectState(visible=True, enabled=True),
                relations=WebObjectRelations(parent=parent),
                origin=origin,
                frame_id=frame_id,
                lifetime="frame" if frame_id else "document",
                security=WebObjectSecurity(content_trust="untrusted", cross_origin=False),
            )
            provenance[object_id] = WebObjectProvenance(
                sources=("content_block",),
                compiler_rules=(f"block_type:{block_type}",),
                legacy_id=block_id or None,
            )
            block_object_ids[block_id] = object_id
            if name or text:
                semantic_keys.setdefault(semantic_key, []).append(object_id)
        return block_object_ids

    def _compile_interactive_elements(
        self,
        snapshot: RawWebSnapshot,
        objects: dict[str, WebObject],
        provenance: dict[str, WebObjectProvenance],
        allocator: "_ObjectIdAllocator",
        document_object_id: str,
        frame_object_ids: dict[str, str],
        frame_id_map: dict[str, str],
        root_frame_id: str | None,
        origin: str,
    ) -> dict[str, str]:
        legacy_to_object: dict[str, str] = {}
        matched_ax: set[str] = set()
        available_ax = [node for node in snapshot.accessibility_nodes if not node.ignored]
        dom_nodes = [node for document in snapshot.dom_documents for node in document.nodes]

        for element in snapshot.interactive_elements:
            if not isinstance(element, dict):
                continue
            legacy_id = str(element.get("id", ""))
            if not legacy_id:
                continue
            spec = _interactive_spec(element)
            name = _element_name(element)
            ax_node = _best_ax_match(element, available_ax, matched_ax)
            if ax_node is not None:
                matched_ax.add(ax_node.node_id)
            dom_node = _best_dom_match(element, dom_nodes, ax_node)
            state = _state_from_element(element, snapshot.focused_element_id, ax_node)
            capabilities = _capabilities_for_element(element, spec.role, state)
            frame_id = str(element.get("frame_id", "")) or None
            frame_id = frame_id_map.get(frame_id or "", frame_id) or root_frame_id
            parent = frame_object_ids.get(frame_id or "", document_object_id)
            object_id = allocator.allocate(legacy_id)
            objects[object_id] = WebObject(
                id=object_id,
                category=spec.category,
                role=spec.role,
                name=name,
                description=ax_node.description if ax_node is not None else "",
                text=str(element.get("text", "")),
                value=_safe_web_value(element.get("value")),
                state=state,
                relations=WebObjectRelations(parent=parent),
                capabilities=capabilities,
                origin=_element_origin(element, origin),
                frame_id=frame_id,
                lifetime="frame" if frame_id and frame_id != "frame_1" else "document",
                security=WebObjectSecurity(content_trust="untrusted", cross_origin=False),
            )
            sources = ["legacy_probe"]
            rules = [f"legacy_role:{str(element.get('role', ''))}"]
            if ax_node is not None:
                sources.append("accessibility")
                rules.append("ax_match")
            if dom_node is not None:
                sources.append("dom_snapshot")
                rules.append("dom_match")
            provenance[object_id] = WebObjectProvenance(
                sources=tuple(sources),
                compiler_rules=tuple(rules),
                legacy_id=legacy_id,
                ax_node_id=ax_node.node_id if ax_node else None,
                backend_dom_node_id=(
                    ax_node.backend_dom_node_id
                    if ax_node and ax_node.backend_dom_node_id is not None
                    else dom_node.backend_node_id if dom_node else None
                ),
                dom_document_index=dom_node.document_index if dom_node else None,
                dom_node_index=dom_node.node_index if dom_node else None,
            )
            legacy_to_object[legacy_id] = object_id
        return legacy_to_object

    def _compile_forms(
        self,
        snapshot: RawWebSnapshot,
        objects: dict[str, WebObject],
        provenance: dict[str, WebObjectProvenance],
        allocator: "_ObjectIdAllocator",
        legacy_to_object: dict[str, str],
        document_object_id: str,
        frame_object_ids: dict[str, str],
        root_frame_id: str | None,
        origin: str,
    ) -> None:
        for form in snapshot.forms:
            if not isinstance(form, dict):
                continue
            legacy_id = str(form.get("id", ""))
            if not legacy_id:
                continue
            frame_id = str(form.get("frame_id", "")) or root_frame_id
            parent = frame_object_ids.get(frame_id or "", document_object_id)
            child_ids = [legacy_to_object[field] for field in form.get("fields", []) if field in legacy_to_object]
            submit_id = legacy_to_object.get(str(form.get("submit", "")))
            if submit_id and submit_id not in child_ids:
                child_ids.append(submit_id)
            object_id = allocator.allocate(legacy_id)
            capabilities: list[ObjectCapabilityName] = ["submit"] if submit_id else []
            name = str(form.get("label", "")) or _short_name(str(form.get("text", "")))
            objects[object_id] = WebObject(
                id=object_id,
                category="container",
                role="form",
                name=name,
                text=str(form.get("text", "")),
                state=WebObjectState(visible=True, enabled=True),
                relations=WebObjectRelations(
                    parent=parent,
                    children=child_ids,
                    submit_control=submit_id,
                ),
                capabilities=capabilities,
                origin=origin,
                frame_id=frame_id,
                lifetime="frame" if frame_id else "document",
                security=WebObjectSecurity(content_trust="untrusted", cross_origin=False),
            )
            provenance[object_id] = WebObjectProvenance(
                sources=("form_probe",),
                compiler_rules=("form_structure",),
                legacy_id=legacy_id,
            )
            for child_id in child_ids:
                child = objects.get(child_id)
                if child is None:
                    continue
                child.relations.form = object_id
                if child.relations.belongs_to is None:
                    child.relations.belongs_to = object_id
    def _bind_content_blocks(
        self,
        snapshot: RawWebSnapshot,
        objects: dict[str, WebObject],
        block_object_ids: dict[str, str],
        legacy_to_object: dict[str, str],
    ) -> None:
        for block in snapshot.content_blocks:
            if not isinstance(block, dict):
                continue
            block_object_id = block_object_ids.get(str(block.get("id", "")))
            block_object = objects.get(block_object_id or "")
            if block_object is None:
                continue
            for legacy_id in block.get("element_ids", []):
                child_id = legacy_to_object.get(str(legacy_id))
                child = objects.get(child_id or "")
                if child is None:
                    continue
                if child_id not in block_object.relations.children:
                    block_object.relations.children.append(child_id)
                if child.relations.belongs_to is None:
                    child.relations.belongs_to = block_object_id

    def _bind_ax_structure(
        self,
        snapshot: RawWebSnapshot,
        objects: dict[str, WebObject],
        ax_to_object: dict[str, str],
        document_object_id: str,
        frame_object_ids: dict[str, str],
        frame_id_map: dict[str, str],
    ) -> None:
        ax_by_id = {node.node_id: node for node in snapshot.accessibility_nodes}
        for node_id, object_id in ax_to_object.items():
            node = ax_by_id.get(node_id)
            current = objects.get(object_id)
            if node is None or current is None or current.id == document_object_id:
                continue
            parent_id = node.parent_id
            parent_object_id: str | None = None
            while parent_id:
                parent_object_id = ax_to_object.get(parent_id)
                if parent_object_id and parent_object_id != object_id:
                    break
                parent_node = ax_by_id.get(parent_id)
                parent_id = parent_node.parent_id if parent_node else None
            if parent_object_id is None:
                frame_id = frame_id_map.get(node.frame_id or "", node.frame_id)
                parent_object_id = frame_object_ids.get(frame_id or "", document_object_id)
            current.relations.parent = parent_object_id
            parent = objects.get(parent_object_id)
            if parent and object_id not in parent.relations.children:
                parent.relations.children.append(object_id)

    def _compile_javascript_dialogs(
        self,
        snapshot: RawWebSnapshot,
        objects: dict[str, WebObject],
        provenance: dict[str, WebObjectProvenance],
        allocator: "_ObjectIdAllocator",
        document_object_id: str,
        origin: str,
    ) -> None:
        for dialog in snapshot.dialogs:
            if not isinstance(dialog, dict):
                continue
            legacy_id = str(dialog.get("id", "")) or "dialog"
            object_id = allocator.allocate(legacy_id)
            objects[object_id] = WebObject(
                id=object_id,
                category="dialog",
                role="dialog",
                name=str(dialog.get("message", "")),
                state=WebObjectState(visible=True, enabled=True),
                relations=WebObjectRelations(parent=document_object_id),
                capabilities=["dismiss"],
                origin=origin,
                lifetime="transient",
                security=WebObjectSecurity(content_trust="untrusted", cross_origin=False),
            )
            provenance[object_id] = WebObjectProvenance(
                sources=("javascript_dialog",),
                compiler_rules=("pending_dialog",),
                legacy_id=legacy_id,
            )

    def _attach_document_children(self, objects: dict[str, WebObject], document_object_id: str) -> None:
        root = objects[document_object_id]
        for object_id, item in objects.items():
            if object_id == document_object_id:
                continue
            parent_id = item.relations.parent or document_object_id
            item.relations.parent = parent_id
            parent = objects.get(parent_id)
            if parent is not None and object_id not in parent.relations.children:
                parent.relations.children.append(object_id)
            elif parent_id == document_object_id and object_id not in root.relations.children:
                root.relations.children.append(object_id)

    def _build_outline(
        self,
        objects: dict[str, WebObject],
        heading_levels: dict[str, int],
    ) -> list[WebOutlineItem]:
        items: list[WebOutlineItem] = []
        for object_id, item in objects.items():
            if item.role != "heading":
                continue
            level = heading_levels.get(object_id, 2)
            items.append(WebOutlineItem(object_id=object_id, level=level, name=item.name or _short_name(item.text)))
        return items

    def _build_regions(self, objects: dict[str, WebObject]) -> list[WebRegionRef]:
        return [
            WebRegionRef(object_id=item.id, role=item.role, name=item.name)
            for item in objects.values()
            if item.role in _REGION_ROLES
        ]


class _ObjectIdAllocator:
    def __init__(self) -> None:
        self._used: set[str] = set()

    def allocate(self, raw: str) -> str:
        base = re.sub(r"[^a-zA-Z0-9_]+", "_", raw).strip("_").lower() or "object"
        candidate = f"obj_{base}"
        suffix = 2
        while candidate in self._used:
            candidate = f"obj_{base}_{suffix}"
            suffix += 1
        self._used.add(candidate)
        return candidate


def _interactive_spec(element: dict) -> _RoleSpec:
    role = _normalize_role(str(element.get("role", "")))
    tag = str(element.get("tag", "")).lower()
    input_type = str(element.get("input_type", "")).lower()
    if role == "link" or tag == "a":
        return _RoleSpec("interactive", "link")
    if role == "button" or tag == "button":
        return _RoleSpec("interactive", "button")
    if role == "searchbox" or input_type == "search":
        return _RoleSpec("interactive", "searchbox")
    if role == "combobox" or tag == "select":
        return _RoleSpec("interactive", "combobox")
    if role == "checkbox" or input_type == "checkbox":
        return _RoleSpec("interactive", "checkbox")
    if role == "radio" or input_type == "radio":
        return _RoleSpec("interactive", "radio")
    if role == "switch":
        return _RoleSpec("interactive", "switch")
    if tag == "textarea":
        return _RoleSpec("interactive", "textarea")
    if role in {"textbox", "field"} or tag == "input":
        return _RoleSpec("interactive", "textbox")
    if role == "option":
        return _RoleSpec("interactive", "option")
    if role == "tab":
        return _RoleSpec("interactive", "tab")
    if role == "menuitem":
        return _RoleSpec("interactive", "menuitem")
    if role == "row" or tag == "tr":
        return _RoleSpec("collection", "row")
    if role in {"listitem", "list_item"}:
        return _RoleSpec("collection", "list_item")
    if role == "slider":
        return _RoleSpec("interactive", "slider")
    return _RoleSpec("interactive", "button")


def _element_name(element: dict) -> str:
    for key in ("name", "placeholder", "text"):
        value = str(element.get(key, "")).strip()
        if value:
            return value
    href = str(element.get("href", "")).strip()
    return href


def _capabilities_for_element(
    element: dict,
    role: ObjectRole,
    state: WebObjectState,
) -> list[ObjectCapabilityName]:
    capabilities: list[ObjectCapabilityName] = []
    input_type = str(element.get("input_type", "")).lower()
    href = str(element.get("href", ""))
    legacy_actions = {str(action) for action in element.get("actions", [])}

    if role == "link" and href:
        capabilities.extend(["open", "open_in_new_context"])
    elif role == "button":
        capabilities.append("activate")
    elif role in _EDITABLE_ROLES:
        if input_type == "password":
            capabilities.append("request_human_takeover")
        elif input_type == "file":
            capabilities.append("upload")
        elif state.readonly is not True:
            capabilities.extend(["set_value", "clear_value"])
    elif role in {"combobox", "option"}:
        capabilities.append("choose")
    elif role in {"checkbox", "radio", "switch"}:
        capabilities.append("toggle")
    elif role in {"tab", "menuitem", "slider"}:
        capabilities.append("activate")
    elif role in {"row", "list_item"} and legacy_actions.intersection({"click", "double_click", "activate_control"}):
        capabilities.append("activate")

    if state.expanded is False:
        capabilities.append("expand")
    elif state.expanded is True:
        capabilities.append("collapse")
    return list(dict.fromkeys(capabilities))


def _capabilities_for_ax(role: ObjectRole, state: WebObjectState) -> list[ObjectCapabilityName]:
    capabilities: list[ObjectCapabilityName] = []
    if state.expanded is False:
        capabilities.append("expand")
    elif state.expanded is True:
        capabilities.append("collapse")
    return capabilities


def _state_from_element(
    element: dict,
    focused_element_id: str | None,
    ax_node: RawAccessibilityNode | None,
) -> WebObjectState:
    properties = ax_node.properties if ax_node is not None else {}
    return WebObjectState(
        visible=bool(element.get("visible", True)),
        enabled=bool(element.get("enabled", True)),
        focused=str(element.get("id", "")) == focused_element_id,
        selected=_optional_bool(element.get("selected")),
        checked=_optional_bool(element.get("checked")),
        expanded=_optional_bool(properties.get("expanded")),
        required=_optional_bool(properties.get("required")),
        readonly=_optional_bool(properties.get("readonly")),
        busy=_optional_bool(properties.get("busy")) or False,
        invalid=_optional_bool(properties.get("invalid")),
        pressed=_optional_bool(properties.get("pressed")),
    )


def _state_from_ax(node: RawAccessibilityNode) -> WebObjectState:
    properties = node.properties
    return WebObjectState(
        visible=True,
        enabled=not (_optional_bool(properties.get("disabled")) or False),
        focused=_optional_bool(properties.get("focused")) or False,
        selected=_optional_bool(properties.get("selected")),
        checked=_optional_bool(properties.get("checked")),
        expanded=_optional_bool(properties.get("expanded")),
        required=_optional_bool(properties.get("required")),
        readonly=_optional_bool(properties.get("readonly")),
        busy=_optional_bool(properties.get("busy")) or False,
        invalid=_optional_bool(properties.get("invalid")),
        pressed=_optional_bool(properties.get("pressed")),
    )


def _best_ax_match(
    element: dict,
    nodes: list[RawAccessibilityNode],
    matched: set[str],
) -> RawAccessibilityNode | None:
    role = _normalize_role(str(element.get("role", "")))
    name = _norm(_element_name(element))
    best: RawAccessibilityNode | None = None
    best_score = 0
    for node in nodes:
        if node.node_id in matched:
            continue
        score = 0
        node_role = _normalize_role(node.role)
        node_name = _norm(node.name)
        if role and role == node_role:
            score += 4
        elif role == "textbox" and node_role in {"textbox", "searchbox"}:
            score += 3
        if name and node_name == name:
            score += 5
        elif name and node_name and (name in node_name or node_name in name):
            score += 2
        if score > best_score:
            best = node
            best_score = score
    return best if best_score >= 4 else None


def _best_dom_match(
    element: dict,
    nodes: list[RawDOMNode],
    ax_node: RawAccessibilityNode | None,
) -> RawDOMNode | None:
    if ax_node is not None and ax_node.backend_dom_node_id is not None:
        for node in nodes:
            if node.backend_node_id == ax_node.backend_dom_node_id:
                return node

    tag = str(element.get("tag", "")).upper()
    name = _norm(_element_name(element))
    href = str(element.get("href", ""))
    best: RawDOMNode | None = None
    best_score = 0
    for node in nodes:
        score = 0
        if tag and node.node_name.upper() == tag:
            score += 3
        attributes = node.attributes
        candidate_names = [
            attributes.get("aria-label", ""),
            attributes.get("placeholder", ""),
            attributes.get("name", ""),
            attributes.get("title", ""),
        ]
        if name and any(_norm(value) == name for value in candidate_names if value):
            score += 4
        if href and attributes.get("href") == href:
            score += 4
        if score > best_score:
            best = node
            best_score = score
    return best if best_score >= 3 else None


def _heading_level(node: RawAccessibilityNode) -> int:
    value = node.properties.get("level")
    try:
        level = int(value)
    except (TypeError, ValueError):
        level = 2
    return min(6, max(1, level))


def _takeover_from_auth(auth, origin: str, target: str | None) -> HumanTakeoverState:
    if not auth.user_action_required:
        return HumanTakeoverState()
    return HumanTakeoverState(
        required=True,
        reason="authentication",
        target=target,
        origin=origin,
    )


def _compiler_errors(snapshot: RawWebSnapshot) -> list[BrowserStateError]:
    if not snapshot.evidence_errors:
        return []
    return [
        BrowserStateError(
            code="compiler_evidence_degraded",
            message="WebFA compiled the page with partial browser evidence.",
            recover_hint="Continue with available WebObjects or observe again.",
        )
    ]


def _match_engine_frames(snapshot: RawWebSnapshot) -> dict[str, RawFrameEvidence]:
    matches: dict[str, RawFrameEvidence] = {}
    used_engine_ids: set[str] = set()
    engine_parent_by_legacy: dict[str, str] = {}
    for frame in snapshot.frames:
        if not isinstance(frame, dict):
            continue
        legacy_id = str(frame.get("id", ""))
        if not legacy_id:
            continue
        parent_legacy_id = str(frame.get("parent_id", "")) or None
        expected_parent_engine = engine_parent_by_legacy.get(parent_legacy_id or "")
        url = str(frame.get("url", ""))
        candidates = [
            item
            for item in snapshot.engine_frames
            if item.frame_id not in used_engine_ids
            and item.url == url
            and (
                (parent_legacy_id is None and item.parent_id is None)
                or (parent_legacy_id is not None and item.parent_id == expected_parent_engine)
            )
        ]
        if not candidates:
            candidates = [
                item
                for item in snapshot.engine_frames
                if item.frame_id not in used_engine_ids and item.url == url
            ]
        if not candidates:
            continue
        selected = candidates[0]
        matches[legacy_id] = selected
        used_engine_ids.add(selected.frame_id)
        engine_parent_by_legacy[legacy_id] = selected.frame_id
    return matches


def _root_frame_id(snapshot: RawWebSnapshot) -> str | None:
    for frame in snapshot.frames:
        if isinstance(frame, dict) and frame.get("id") and not frame.get("parent_id"):
            return str(frame["id"])
    return None


def _document_id(snapshot: RawWebSnapshot) -> str:
    root_engine_frame = next((item for item in snapshot.engine_frames if item.parent_id is None), None)
    if root_engine_frame and root_engine_frame.loader_id:
        identity = f"{root_engine_frame.frame_id}:{root_engine_frame.loader_id}"
    else:
        identity = snapshot.url
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return f"doc_{digest}"


def _origin_of(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    if parsed.scheme == "file":
        return "file://"
    return ""


def _element_origin(element: dict, fallback: str) -> str:
    href = str(element.get("href", ""))
    return _origin_of(href) or fallback


def _normalize_role(value: str) -> str:
    return value.strip().lower().replace("_", "").replace("-", "").replace(" ", "")


def _norm(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _short_name(text: str) -> str:
    return " ".join(text.split())[:120]


def _optional_bool(value) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "on", "mixed"}:
        return True
    if normalized in {"false", "0", "no", "off", "undefined"}:
        return False
    return None


def _safe_web_value(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [item for item in value if isinstance(item, (str, int, float, bool))]
    return None
