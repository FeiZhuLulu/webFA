from __future__ import annotations

from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from typing import Any

from browser.web_object_compiler import WebObjectCompilation, WebObjectProvenance
from schemas.web import (
    WebChangeSet,
    WebObject,
    WebObjectSummary,
    WebObjectUpdate,
    WebRegionRef,
    WebState,
)


DEFAULT_HISTORY_LIMIT = 64


class WebObjectNotFoundError(LookupError):
    pass


class WebRevisionUnavailableError(LookupError):
    pass


@dataclass(frozen=True)
class RegisteredWebState:
    state: WebState
    provenance: dict[str, WebObjectProvenance]
    changes: WebChangeSet


@dataclass(frozen=True)
class _RevisionSnapshot:
    state: WebState
    provenance: dict[str, WebObjectProvenance]


class ObjectRegistry:
    """Reconcile compiled WebObjects into stable session-scoped identities."""

    def __init__(self, *, history_limit: int = DEFAULT_HISTORY_LIMIT) -> None:
        if history_limit < 2:
            raise ValueError("history_limit must be at least 2")
        self._history_limit = history_limit
        self._next_object_number = 1
        self._current: _RevisionSnapshot | None = None
        self._history: OrderedDict[int, _RevisionSnapshot] = OrderedDict()

    @property
    def current_revision(self) -> int:
        return self._current.state.document_revision if self._current else 0

    @property
    def current_document_id(self) -> str | None:
        return self._current.state.document_id if self._current else None

    def update(self, compilation: WebObjectCompilation) -> RegisteredWebState:
        incoming = compilation.state.model_copy(deep=True)
        incoming_objects = {
            item.id: item
            for item in incoming.objects
            if isinstance(item, WebObject)
        }
        previous = self._current
        same_document = previous is not None and previous.state.document_id == incoming.document_id
        previous_objects = _full_objects(previous.state) if previous else {}

        transient_to_stable = self._reconcile_ids(
            incoming_objects,
            compilation.provenance,
            previous_objects if same_document else {},
            previous.provenance if same_document and previous else {},
        )
        stable_objects = self._rewrite_objects(incoming_objects, transient_to_stable)
        stable_provenance = {
            transient_to_stable[transient_id]: provenance
            for transient_id, provenance in compilation.provenance.items()
            if transient_id in transient_to_stable
        }

        previous_revision = previous.state.document_revision if previous else 0
        changed_fields: dict[str, list[str]] = {}
        for stable_id, item in stable_objects.items():
            old = previous_objects.get(stable_id) if same_document else None
            if old is None:
                item.version = 1
                continue
            fields = _changed_fields(old, item)
            if fields:
                item.version = old.version + 1
                changed_fields[stable_id] = fields
            else:
                item.version = old.version

        added_ids = [stable_id for stable_id in stable_objects if stable_id not in previous_objects]
        removed_ids = [stable_id for stable_id in previous_objects if stable_id not in stable_objects]
        invalidated_ids: list[str] = []
        if previous is not None and not same_document:
            invalidated_ids = list(previous_objects)
            removed_ids = []

        rewritten_state = self._rewrite_state(incoming, stable_objects, transient_to_stable)
        document_changed_fields = (
            _changed_document_fields(previous.state, rewritten_state)
            if previous is not None
            else []
        )
        meaningful_change = bool(
            previous is None
            or not same_document
            or added_ids
            or removed_ids
            or changed_fields
            or document_changed_fields
        )
        revision = previous_revision + 1 if meaningful_change else previous_revision
        rewritten_state.document_revision = revision

        changes = WebChangeSet(
            from_revision=previous_revision,
            to_revision=revision,
            document_changed_fields=document_changed_fields,
            added=[_summary(stable_objects[stable_id]) for stable_id in added_ids],
            updated=[
                WebObjectUpdate(
                    id=stable_id,
                    from_version=previous_objects[stable_id].version,
                    to_version=stable_objects[stable_id].version,
                    changed_fields=fields,
                )
                for stable_id, fields in changed_fields.items()
            ],
            removed=removed_ids,
            invalidated=invalidated_ids,
        )
        rewritten_state.changes = changes

        snapshot = _RevisionSnapshot(
            state=rewritten_state.model_copy(deep=True),
            provenance=dict(stable_provenance),
        )
        self._current = snapshot
        self._history[revision] = snapshot
        self._history.move_to_end(revision)
        while len(self._history) > self._history_limit:
            self._history.popitem(last=False)

        return RegisteredWebState(
            state=rewritten_state,
            provenance=stable_provenance,
            changes=changes,
        )

    def current_state(self) -> WebState | None:
        return self._current.state.model_copy(deep=True) if self._current else None

    def current_provenance(self) -> dict[str, WebObjectProvenance]:
        return dict(self._current.provenance) if self._current else {}

    def require(self, object_id: str) -> WebObject:
        if self._current is None:
            raise WebObjectNotFoundError(object_id)
        item = _full_objects(self._current.state).get(object_id)
        if item is None:
            raise WebObjectNotFoundError(object_id)
        return item.model_copy(deep=True)

    def provenance_for(self, object_id: str) -> WebObjectProvenance:
        if self._current is None or object_id not in self._current.provenance:
            raise WebObjectNotFoundError(object_id)
        return self._current.provenance[object_id]

    def legacy_target_for(self, object_id: str) -> str | None:
        return self.provenance_for(object_id).legacy_id

    def changes_since(self, revision: int) -> WebChangeSet:
        if self._current is None:
            if revision == 0:
                return WebChangeSet(from_revision=0, to_revision=0)
            raise WebRevisionUnavailableError(revision)
        current_revision = self._current.state.document_revision
        if revision == current_revision:
            return WebChangeSet(from_revision=revision, to_revision=revision)
        baseline = self._history.get(revision)
        if baseline is None:
            raise WebRevisionUnavailableError(revision)
        return _diff_snapshots(baseline, self._current)

    def clear(self) -> None:
        self._next_object_number = 1
        self._current = None
        self._history.clear()

    def _reconcile_ids(
        self,
        incoming: dict[str, WebObject],
        incoming_provenance: dict[str, WebObjectProvenance],
        previous: dict[str, WebObject],
        previous_provenance: dict[str, WebObjectProvenance],
    ) -> dict[str, str]:
        if not previous:
            return {transient_id: self._allocate_id() for transient_id in incoming}

        result: dict[str, str] = {}
        used_previous: set[str] = set()
        strong_indexes = _strong_identity_indexes(previous, previous_provenance)

        for transient_id, item in incoming.items():
            provenance = incoming_provenance.get(transient_id)
            for key in _strong_identity_keys(item, provenance):
                candidate = strong_indexes.get(key)
                if candidate and candidate not in used_previous:
                    result[transient_id] = candidate
                    used_previous.add(candidate)
                    break

        current_semantic_counts: dict[tuple[Any, ...], int] = defaultdict(int)
        for transient_id, item in incoming.items():
            if transient_id not in result:
                current_semantic_counts[_semantic_identity_key(item, incoming)] += 1
        previous_semantic: dict[tuple[Any, ...], list[str]] = defaultdict(list)
        for stable_id, item in previous.items():
            if stable_id not in used_previous:
                previous_semantic[_semantic_identity_key(item, previous)].append(stable_id)

        for transient_id, item in incoming.items():
            if transient_id in result:
                continue
            key = _semantic_identity_key(item, incoming)
            candidates = previous_semantic.get(key, [])
            if current_semantic_counts[key] == 1 and len(candidates) == 1:
                candidate = candidates[0]
                result[transient_id] = candidate
                used_previous.add(candidate)
            else:
                result[transient_id] = self._allocate_id()
        return result

    def _rewrite_objects(
        self,
        incoming: dict[str, WebObject],
        transient_to_stable: dict[str, str],
    ) -> dict[str, WebObject]:
        stable: dict[str, WebObject] = {}
        for transient_id, item in incoming.items():
            clone = item.model_copy(deep=True)
            clone.id = transient_to_stable[transient_id]
            relations = clone.relations
            relations.parent = _mapped(relations.parent, transient_to_stable)
            relations.children = _mapped_list(relations.children, transient_to_stable)
            relations.belongs_to = _mapped(relations.belongs_to, transient_to_stable)
            relations.labelled_by = _mapped_list(relations.labelled_by, transient_to_stable)
            relations.described_by = _mapped_list(relations.described_by, transient_to_stable)
            relations.controls = _mapped_list(relations.controls, transient_to_stable)
            relations.controlled_by = _mapped_list(relations.controlled_by, transient_to_stable)
            relations.owns = _mapped_list(relations.owns, transient_to_stable)
            relations.owned_by = _mapped(relations.owned_by, transient_to_stable)
            relations.form = _mapped(relations.form, transient_to_stable)
            relations.submit_control = _mapped(relations.submit_control, transient_to_stable)
            stable[clone.id] = clone
        return stable

    def _rewrite_state(
        self,
        incoming: WebState,
        stable_objects: dict[str, WebObject],
        transient_to_stable: dict[str, str],
    ) -> WebState:
        state = incoming.model_copy(deep=True)
        state.objects = list(stable_objects.values())
        state.object_count = len(stable_objects)
        state.outline = [
            item.model_copy(update={"object_id": transient_to_stable.get(item.object_id, item.object_id)})
            for item in state.outline
        ]
        state.regions = [
            WebRegionRef(
                object_id=transient_to_stable.get(item.object_id, item.object_id),
                role=item.role,
                name=item.name,
            )
            for item in state.regions
        ]
        if state.takeover.target:
            state.takeover.target = transient_to_stable.get(state.takeover.target, state.takeover.target)
        return state

    def _allocate_id(self) -> str:
        object_id = f"obj_{self._next_object_number}"
        self._next_object_number += 1
        return object_id


def _strong_identity_indexes(
    previous: dict[str, WebObject],
    provenance: dict[str, WebObjectProvenance],
) -> dict[tuple[Any, ...], str]:
    indexes: dict[tuple[Any, ...], str] = {}
    duplicates: set[tuple[Any, ...]] = set()
    for stable_id, item in previous.items():
        for key in _strong_identity_keys(item, provenance.get(stable_id)):
            if key in indexes:
                duplicates.add(key)
            else:
                indexes[key] = stable_id
    for key in duplicates:
        indexes.pop(key, None)
    return indexes


def _strong_identity_keys(
    item: WebObject,
    provenance: WebObjectProvenance | None,
) -> list[tuple[Any, ...]]:
    keys: list[tuple[Any, ...]] = []
    frame = item.frame_id or ""
    if item.role == "document":
        keys.append(("document", item.origin))
    if provenance is None:
        return keys
    if provenance.engine_frame_id:
        keys.append(("engine_frame", provenance.engine_frame_id))
    if provenance.backend_dom_node_id is not None:
        keys.append(("backend", frame, provenance.backend_dom_node_id))
    if provenance.ax_node_id:
        keys.append(("ax", frame, provenance.ax_node_id))
    if provenance.legacy_id and _legacy_id_is_stable(provenance.legacy_id):
        keys.append(("legacy", frame, provenance.legacy_id))
    return keys


def _legacy_id_is_stable(value: str) -> bool:
    return value.startswith("el_") or value.startswith("frame_") or value.startswith("dialog_")


def _semantic_identity_key(item: WebObject, object_map: dict[str, WebObject]) -> tuple[Any, ...]:
    parent = object_map.get(item.relations.parent or "")
    parent_key = (
        parent.category if parent else "",
        parent.role if parent else "",
        _norm(parent.name) if parent else "",
    )
    return (
        item.category,
        item.role,
        _norm(item.name),
        item.origin,
        item.frame_id or "",
        parent_key,
        item.lifetime,
    )


def _meaningful_object_dump(item: WebObject) -> dict[str, Any]:
    data = item.model_dump(exclude={"id", "version"})
    state = dict(data.get("state", {}))
    state.pop("busy", None)
    data["state"] = state
    data["name"] = _norm(str(data.get("name", "")))
    data["description"] = _norm(str(data.get("description", "")))
    data["text"] = _norm(str(data.get("text", "")))
    return data


def _changed_fields(previous: WebObject, current: WebObject) -> list[str]:
    old = _meaningful_object_dump(previous)
    new = _meaningful_object_dump(current)
    changed: list[str] = []
    for key in sorted(set(old) | set(new)):
        old_value = old.get(key)
        new_value = new.get(key)
        if isinstance(old_value, dict) and isinstance(new_value, dict):
            for nested_key in sorted(set(old_value) | set(new_value)):
                if old_value.get(nested_key) != new_value.get(nested_key):
                    changed.append(f"{key}.{nested_key}")
        elif old_value != new_value:
            changed.append(key)
    return changed


def _changed_document_fields(previous: WebState, current: WebState) -> list[str]:
    fields = {
        "document_id": (previous.document_id, current.document_id),
        "url": (previous.url, current.url),
        "title": (previous.title, current.title),
        "status": (previous.status, current.status),
        "dialogs": (
            tuple(item.model_dump_json() for item in previous.dialogs),
            tuple(item.model_dump_json() for item in current.dialogs),
        ),
        "auth": (previous.auth.model_dump_json(), current.auth.model_dump_json()),
        "takeover": (previous.takeover.model_dump_json(), current.takeover.model_dump_json()),
        "security": (previous.security.model_dump_json(), current.security.model_dump_json()),
        "errors": (
            tuple(error.model_dump_json() for error in previous.errors),
            tuple(error.model_dump_json() for error in current.errors),
        ),
    }
    return [name for name, (old, new) in fields.items() if old != new]


def _summary(item: WebObject) -> WebObjectSummary:
    state_summary: list[str] = []
    if item.state.visible:
        state_summary.append("visible")
    if item.state.enabled:
        state_summary.append("enabled")
    if item.state.focused:
        state_summary.append("focused")
    if item.state.selected is True:
        state_summary.append("selected")
    if item.state.checked is True:
        state_summary.append("checked")
    if item.state.expanded is True:
        state_summary.append("expanded")
    if item.state.expanded is False:
        state_summary.append("collapsed")
    return WebObjectSummary(
        id=item.id,
        category=item.category,
        role=item.role,
        name=item.name,
        capabilities=item.capabilities,
        version=item.version,
        state_summary=state_summary,
    )


def _full_objects(state: WebState) -> dict[str, WebObject]:
    return {
        item.id: item
        for item in state.objects
        if isinstance(item, WebObject)
    }


def _diff_snapshots(baseline: _RevisionSnapshot, current: _RevisionSnapshot) -> WebChangeSet:
    previous_objects = _full_objects(baseline.state)
    current_objects = _full_objects(current.state)
    same_document = baseline.state.document_id == current.state.document_id
    added = [
        _summary(item)
        for object_id, item in current_objects.items()
        if object_id not in previous_objects
    ]
    updated: list[WebObjectUpdate] = []
    for object_id, current_item in current_objects.items():
        previous_item = previous_objects.get(object_id)
        if previous_item is None or current_item.version == previous_item.version:
            continue
        updated.append(
            WebObjectUpdate(
                id=object_id,
                from_version=previous_item.version,
                to_version=current_item.version,
                changed_fields=_changed_fields(previous_item, current_item),
            )
        )
    if same_document:
        removed = [object_id for object_id in previous_objects if object_id not in current_objects]
        invalidated: list[str] = []
    else:
        removed = []
        invalidated = list(previous_objects)
    return WebChangeSet(
        from_revision=baseline.state.document_revision,
        to_revision=current.state.document_revision,
        document_changed_fields=_changed_document_fields(baseline.state, current.state),
        added=added,
        updated=updated,
        removed=removed,
        invalidated=invalidated,
    )


def _mapped(value: str | None, mapping: dict[str, str]) -> str | None:
    if value is None:
        return None
    return mapping.get(value, value)


def _mapped_list(values: list[str], mapping: dict[str, str]) -> list[str]:
    return [mapping.get(value, value) for value in values]


def _norm(value: str) -> str:
    return " ".join(value.strip().lower().split())
