from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from browser.object_registry import ObjectRegistry, WebObjectNotFoundError
from browser.web_object_compiler import WebObjectProvenance
from schemas.web import (
    ObserveDetail,
    WebChangeSet,
    WebObject,
    WebObjectProjection,
    WebObjectSummary,
    WebObserveQuery,
    WebObserveRequest,
    WebState,
    WebVisibleRange,
)


STANDARD_TEXT_MAX_CHARS = 600
STANDARD_DESCRIPTION_MAX_CHARS = 300
STANDARD_RELATION_MAX_COUNT = 20


class WebObserveUnavailableError(RuntimeError):
    pass


class WebObserveDebugForbiddenError(PermissionError):
    pass


class WebObserveRangeError(ValueError):
    pass


@dataclass(frozen=True)
class WebObserveResult:
    state: WebState
    debug_provenance: dict[str, WebObjectProvenance] | None = None


class WebObserveService:
    """Project stable WebObjects into bounded page/object/query/changes views."""

    def __init__(self, registry: ObjectRegistry) -> None:
        self._registry = registry

    def observe(
        self,
        request: WebObserveRequest | None = None,
        *,
        allow_debug: bool = False,
    ) -> WebObserveResult:
        request = request or WebObserveRequest()
        current = self._registry.current_state()
        if current is None:
            raise WebObserveUnavailableError("no compiled WebState is available")
        if request.detail == "debug" and not allow_debug:
            raise WebObserveDebugForbiddenError("debug observe is local-only")

        all_objects = _full_object_map(current)
        selected: list[WebObject]
        changes: WebChangeSet | None = None

        if request.mode == "page":
            selected = _select_page_objects(current, all_objects, request.limit)
        elif request.mode == "object":
            selected = self._select_object(request, all_objects)
        elif request.mode == "query":
            selected = _select_query_objects(request.query, all_objects, request.limit)
        elif request.mode == "changes":
            changes = self._registry.changes_since(request.since_revision or 0)
            affected_ids = [item.id for item in changes.added] + [item.id for item in changes.updated]
            selected = [all_objects[object_id] for object_id in affected_ids if object_id in all_objects]
        else:  # pragma: no cover - guarded by schema
            raise ValueError(f"unsupported observe mode: {request.mode}")

        projected = [_project_object(item, request.detail) for item in selected]
        state = current.model_copy(deep=True)
        state.objects = projected
        state.object_count = current.object_count
        state.changes = changes

        debug_provenance = None
        if request.detail == "debug":
            all_provenance = self._registry.current_provenance()
            debug_provenance = {
                item.id: all_provenance[item.id]
                for item in selected
                if item.id in all_provenance
            }
        return WebObserveResult(state=state, debug_provenance=debug_provenance)

    def _select_object(
        self,
        request: WebObserveRequest,
        all_objects: dict[str, WebObject],
    ) -> list[WebObject]:
        target_id = request.target or ""
        target = all_objects.get(target_id)
        if target is None:
            raise WebObjectNotFoundError(target_id)
        if request.range is None:
            return [target]
        if not target.observable.range_readable:
            raise WebObserveRangeError(f"object is not range-readable: {target_id}")

        range_ids = _range_object_ids(target)
        total = len(range_ids)
        start = request.range.start
        end_exclusive = min(total, start + request.range.limit)
        child_ids = range_ids[start:end_exclusive]
        target_projection = target.model_copy(deep=True)
        target_projection.relations.children = list(child_ids)
        if target.relations.rows:
            target_projection.relations.rows = list(child_ids)
            target_projection.relations.items = list(child_ids)
        elif target.relations.items:
            target_projection.relations.items = list(child_ids)
        elif target.relations.cells:
            target_projection.relations.cells = list(child_ids)
            target_projection.relations.items = list(child_ids)
        target_projection.observable.item_count = total
        target_projection.observable.visible_range = (
            WebVisibleRange(start=start, end=end_exclusive - 1)
            if child_ids
            else None
        )
        children = [all_objects[child_id] for child_id in child_ids if child_id in all_objects]
        return [target_projection, *children]


def _select_page_objects(
    state: WebState,
    all_objects: dict[str, WebObject],
    limit: int,
) -> list[WebObject]:
    ordered_ids = [item.id for item in state.objects if isinstance(item, WebObject)]
    original_positions = {object_id: index for index, object_id in enumerate(ordered_ids)}
    region_ids = {item.object_id for item in state.regions}
    outline_ids = {item.object_id for item in state.outline}

    def priority(item: WebObject) -> tuple[int, int]:
        if item.role == "document":
            rank = 0
        elif item.id in region_ids:
            rank = 1
        elif item.role in {"dialog", "alert", "status"}:
            rank = 2
        elif item.role == "form":
            rank = 3
        elif item.category == "interactive":
            rank = 4
        elif item.category == "collection":
            rank = 5
        elif item.id in outline_ids or item.role == "heading":
            rank = 6
        elif item.role == "frame":
            rank = 7
        else:
            rank = 8
        return rank, original_positions.get(item.id, len(ordered_ids))

    return sorted(all_objects.values(), key=priority)[:limit]


def _select_query_objects(
    query: WebObserveQuery | None,
    all_objects: dict[str, WebObject],
    limit: int,
) -> list[WebObject]:
    if query is None:  # pragma: no cover - guarded by schema
        return []
    return [
        item
        for item in all_objects.values()
        if _matches_query(item, query, all_objects)
    ][:limit]


def _matches_query(
    item: WebObject,
    query: WebObserveQuery,
    all_objects: dict[str, WebObject],
) -> bool:
    if query.id is not None and item.id != query.id:
        return False
    if query.category is not None and item.category != query.category:
        return False
    if query.role is not None and item.role != query.role:
        return False
    if query.name is not None and _norm(item.name) != _norm(query.name):
        return False
    if query.name_contains is not None and _norm(query.name_contains) not in _norm(item.name):
        return False
    if query.text_contains is not None and _norm(query.text_contains) not in _norm(item.text):
        return False
    if query.capability is not None and query.capability not in item.capabilities:
        return False
    if query.visible is not None and item.state.visible != query.visible:
        return False
    if query.enabled is not None and item.state.enabled != query.enabled:
        return False
    if query.frame_id is not None and item.frame_id != query.frame_id:
        return False
    if query.origin is not None and item.origin != query.origin:
        return False
    if query.within is not None and not _is_descendant(item.id, query.within, all_objects):
        return False
    return True


def _is_descendant(
    object_id: str,
    ancestor_id: str,
    all_objects: dict[str, WebObject],
) -> bool:
    if object_id == ancestor_id:
        return False
    pending = [object_id]
    seen: set[str] = set()
    while pending:
        current_id = pending.pop()
        if current_id in seen:
            continue
        seen.add(current_id)
        current = all_objects.get(current_id)
        if current is None:
            continue
        relations = current.relations
        containers = [
            relations.parent,
            relations.belongs_to,
            relations.form,
            relations.owned_by,
        ]
        for container_id in containers:
            if not container_id:
                continue
            if container_id == ancestor_id:
                return True
            if container_id not in seen:
                pending.append(container_id)
    return False


def _project_object(item: WebObject, detail: ObserveDetail) -> WebObjectProjection:
    if detail == "summary":
        return _summary(item)
    if detail == "standard":
        return _standard(item)
    return item.model_copy(deep=True)


def _standard(item: WebObject) -> WebObject:
    projected = item.model_copy(deep=True)
    projected.description = projected.description[:STANDARD_DESCRIPTION_MAX_CHARS]
    projected.text = projected.text[:STANDARD_TEXT_MAX_CHARS]
    relations = projected.relations
    relations.children = relations.children[:STANDARD_RELATION_MAX_COUNT]
    relations.labelled_by = relations.labelled_by[:STANDARD_RELATION_MAX_COUNT]
    relations.described_by = relations.described_by[:STANDARD_RELATION_MAX_COUNT]
    relations.controls = relations.controls[:STANDARD_RELATION_MAX_COUNT]
    relations.controlled_by = relations.controlled_by[:STANDARD_RELATION_MAX_COUNT]
    relations.owns = relations.owns[:STANDARD_RELATION_MAX_COUNT]
    relations.fields = relations.fields[:STANDARD_RELATION_MAX_COUNT]
    relations.items = relations.items[:STANDARD_RELATION_MAX_COUNT]
    relations.rows = relations.rows[:STANDARD_RELATION_MAX_COUNT]
    relations.cells = relations.cells[:STANDARD_RELATION_MAX_COUNT]
    relations.headers = relations.headers[:STANDARD_RELATION_MAX_COUNT]
    range_ids = _range_object_ids(projected)
    if projected.observable.range_readable and projected.observable.item_count is not None and range_ids:
        projected.observable.visible_range = WebVisibleRange(start=0, end=len(range_ids) - 1)
    return projected


def _summary(item: WebObject) -> WebObjectSummary:
    states: list[str] = []
    if item.state.visible:
        states.append("visible")
    if item.state.enabled:
        states.append("enabled")
    if item.state.focused:
        states.append("focused")
    if item.state.selected is True:
        states.append("selected")
    if item.state.checked is True:
        states.append("checked")
    if item.state.expanded is True:
        states.append("expanded")
    if item.state.expanded is False:
        states.append("collapsed")
    return WebObjectSummary(
        id=item.id,
        category=item.category,
        role=item.role,
        name=item.name,
        capabilities=item.capabilities,
        version=item.version,
        state_summary=states,
    )


def _range_object_ids(item: WebObject) -> list[str]:
    if item.relations.rows:
        return item.relations.rows
    if item.relations.items:
        return item.relations.items
    if item.relations.cells:
        return item.relations.cells
    return item.relations.children


def _full_object_map(state: WebState) -> dict[str, WebObject]:
    return {
        item.id: item
        for item in state.objects
        if isinstance(item, WebObject)
    }


def _norm(value: str) -> str:
    return " ".join(value.strip().lower().split())
