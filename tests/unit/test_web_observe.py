from __future__ import annotations

import pytest

from browser.object_registry import ObjectRegistry, WebObjectNotFoundError
from browser.runtime import BrowserRuntime
from browser.web_object_compiler import WebObjectCompilation, WebObjectProvenance
from browser.web_observe import (
    STANDARD_RELATION_MAX_COUNT,
    STANDARD_TEXT_MAX_CHARS,
    WebObserveDebugForbiddenError,
    WebObserveRangeError,
    WebObserveService,
    WebObserveUnavailableError,
)
from schemas.web import (
    WebObject,
    WebObjectObservable,
    WebObjectRelations,
    WebObjectState,
    WebObjectSummary,
    WebObserveQuery,
    WebObserveRequest,
    WebOutlineItem,
    WebRegionRef,
    WebState,
)


def _web_object(
    object_id: str,
    category: str,
    role: str,
    name: str,
    *,
    parent: str | None = None,
    children: list[str] | None = None,
    text: str = "",
    value=None,
    capabilities: list[str] | None = None,
    range_readable: bool = False,
    origin: str = "https://example.com",
) -> WebObject:
    return WebObject(
        id=object_id,
        category=category,
        role=role,
        name=name,
        text=text,
        value=value,
        state=WebObjectState(visible=True, enabled=True),
        relations=WebObjectRelations(parent=parent, children=children or []),
        observable=WebObjectObservable(
            inspectable=True,
            range_readable=range_readable,
            item_count=len(children or []) if range_readable else None,
        ),
        capabilities=capabilities or [],
        origin=origin,
        frame_id="frame_1",
    )


def _compilation(*, field_value: str = "") -> WebObjectCompilation:
    item_ids = [f"tmp_item_{index}" for index in range(30)]
    document = _web_object("tmp_doc", "document", "document", "Search page", children=["tmp_main"])
    main = _web_object(
        "tmp_main",
        "container",
        "main",
        "Main",
        parent="tmp_doc",
        children=["tmp_heading", "tmp_nav", "tmp_form", "tmp_collection"],
    )
    heading = _web_object(
        "tmp_heading",
        "content",
        "heading",
        "Results",
        parent="tmp_main",
        text="Results" + (" details" * 200),
    )
    navigation = _web_object(
        "tmp_nav",
        "container",
        "navigation",
        "Primary navigation",
        parent="tmp_main",
        children=["tmp_link"],
    )
    link = _web_object(
        "tmp_link",
        "interactive",
        "link",
        "WebFA repository",
        parent="tmp_main",
        capabilities=["open", "open_in_new_context"],
        origin="https://github.com",
    )
    link.relations.belongs_to = "tmp_nav"
    field = _web_object(
        "tmp_field",
        "interactive",
        "searchbox",
        "Search repositories",
        parent="tmp_form",
        value=field_value,
        capabilities=["set_value", "clear_value"],
    )
    submit = _web_object(
        "tmp_submit",
        "interactive",
        "button",
        "Search",
        parent="tmp_form",
        capabilities=["activate"],
    )
    form = _web_object(
        "tmp_form",
        "container",
        "form",
        "Repository search",
        parent="tmp_main",
        children=["tmp_field", "tmp_submit"],
        capabilities=["submit"],
    )
    form.relations.submit_control = "tmp_submit"
    collection = _web_object(
        "tmp_collection",
        "collection",
        "collection",
        "Repository results",
        parent="tmp_main",
        children=item_ids,
        range_readable=True,
    )
    items = [
        _web_object(
            item_id,
            "collection",
            "list_item",
            f"Repository {index}",
            parent="tmp_collection",
            text=f"Repository {index} description",
        )
        for index, item_id in enumerate(item_ids)
    ]
    objects = [document, main, heading, navigation, link, form, field, submit, collection, *items]
    provenance = {
        item.id: WebObjectProvenance(
            sources=("fixture",),
            compiler_rules=("fixture",),
            legacy_id="el_field" if item.id == "tmp_field" else None,
            backend_dom_node_id=101 if item.id == "tmp_field" else None,
        )
        for item in objects
    }
    return WebObjectCompilation(
        state=WebState(
            session_id="default",
            document_id="doc_search",
            url="https://example.com/search",
            title="Search page",
            outline=[WebOutlineItem(object_id="tmp_heading", level=1, name="Results")],
            regions=[WebRegionRef(object_id="tmp_main", role="main", name="Main")],
            objects=objects,
            object_count=len(objects),
        ),
        provenance=provenance,
    )


def _seed_registry(*, field_value: str = "") -> ObjectRegistry:
    registry = ObjectRegistry()
    registry.update(_compilation(field_value=field_value))
    return registry


def _full_objects(result) -> list[WebObject]:
    return [item for item in result.state.objects if isinstance(item, WebObject)]


def test_observe_requires_compiled_state():
    with pytest.raises(WebObserveUnavailableError):
        WebObserveService(ObjectRegistry()).observe()


def test_page_summary_is_bounded_and_prioritizes_agent_relevant_objects():
    registry = _seed_registry()
    service = WebObserveService(registry)

    result = service.observe(WebObserveRequest(mode="page", detail="summary", limit=6))

    assert len(result.state.objects) == 6
    assert all(isinstance(item, WebObjectSummary) for item in result.state.objects)
    roles = [item.role for item in result.state.objects]
    assert roles[0] == "document"
    assert "main" in roles
    assert "form" in roles
    assert "searchbox" in roles
    assert result.state.object_count > len(result.state.objects)
    assert result.state.changes is None


def test_standard_projection_truncates_large_text_and_relations():
    registry = _seed_registry()
    service = WebObserveService(registry)
    collection = next(item for item in registry.current_state().objects if item.role == "collection")

    result = service.observe(
        WebObserveRequest(mode="object", target=collection.id, detail="standard")
    )
    projected = _full_objects(result)[0]

    assert len(projected.relations.children) == STANDARD_RELATION_MAX_COUNT
    heading = next(item for item in registry.current_state().objects if item.role == "heading")
    heading_result = service.observe(
        WebObserveRequest(mode="object", target=heading.id, detail="standard")
    )
    assert len(_full_objects(heading_result)[0].text) == STANDARD_TEXT_MAX_CHARS


def test_object_full_projection_and_collection_range():
    registry = _seed_registry()
    service = WebObserveService(registry)
    collection = next(item for item in registry.current_state().objects if item.role == "collection")

    result = service.observe(
        WebObserveRequest(
            mode="object",
            target=collection.id,
            range={"start": 10, "limit": 5},
            detail="full",
        )
    )
    objects = _full_objects(result)
    projected_collection = objects[0]

    assert len(objects) == 6
    assert projected_collection.observable.item_count == 30
    assert projected_collection.observable.visible_range.start == 10
    assert projected_collection.observable.visible_range.end == 14
    assert [item.name for item in objects[1:]] == [f"Repository {index}" for index in range(10, 15)]


def test_object_range_rejects_non_collection_object():
    registry = _seed_registry()
    service = WebObserveService(registry)
    field = next(item for item in registry.current_state().objects if item.role == "searchbox")

    with pytest.raises(WebObserveRangeError):
        service.observe(
            WebObserveRequest(mode="object", target=field.id, range={"start": 0, "limit": 5})
        )
    with pytest.raises(WebObjectNotFoundError):
        service.observe(WebObserveRequest(mode="object", target="obj_missing"))


def test_semantic_query_filters_within_capability_and_limit():
    registry = _seed_registry()
    service = WebObserveService(registry)
    form = next(item for item in registry.current_state().objects if item.role == "form")

    result = service.observe(
        WebObserveRequest(
            mode="query",
            query=WebObserveQuery(
                category="interactive",
                within=form.id,
                capability="set_value",
                name_contains="repositories",
            ),
            detail="summary",
            limit=1,
        )
    )

    assert len(result.state.objects) == 1
    assert result.state.objects[0].role == "searchbox"
    assert result.state.objects[0].name == "Search repositories"


def test_query_within_uses_semantic_belongs_to_relations():
    registry = _seed_registry()
    service = WebObserveService(registry)
    navigation = next(item for item in registry.current_state().objects if item.role == "navigation")

    result = service.observe(
        WebObserveRequest(
            mode="query",
            query=WebObserveQuery(role="link", within=navigation.id),
            detail="summary",
        )
    )

    assert len(result.state.objects) == 1
    assert result.state.objects[0].name == "WebFA repository"


def test_changes_mode_returns_compact_changes_and_current_affected_objects():
    registry = _seed_registry(field_value="")
    first_revision = registry.current_revision
    registry.update(_compilation(field_value="webfa"))
    service = WebObserveService(registry)

    result = service.observe(
        WebObserveRequest(mode="changes", since_revision=first_revision, detail="summary")
    )

    assert result.state.changes.from_revision == first_revision
    assert result.state.changes.to_revision == first_revision + 1
    assert len(result.state.changes.updated) == 1
    assert len(result.state.objects) == 1
    assert result.state.objects[0].role == "searchbox"


def test_runtime_auth_surface_is_retired():
    from browser.runtime_errors import BrowserRuntimeError

    runtime = BrowserRuntime(driver_factory=lambda: (_ for _ in ()).throw(RuntimeError("unused")))
    try:
        with pytest.raises(BrowserRuntimeError) as error:
            runtime.open_auth_surface("https://example.com/login")
        assert error.value.code == "legacy_auth_surface_disabled"
        assert error.value.http_status == 410
    finally:
        runtime.close()


def test_debug_detail_is_local_only_and_returns_separate_provenance():
    registry = _seed_registry()
    service = WebObserveService(registry)
    field = next(item for item in registry.current_state().objects if item.role == "searchbox")
    request = WebObserveRequest(mode="object", target=field.id, detail="debug")

    with pytest.raises(WebObserveDebugForbiddenError):
        service.observe(request)

    result = service.observe(request, allow_debug=True)

    assert result.debug_provenance is not None
    assert result.debug_provenance[field.id].backend_dom_node_id == 101
    serialized = result.state.model_dump_json()
    assert "backend_dom_node_id" not in serialized
    assert "provenance" not in serialized
