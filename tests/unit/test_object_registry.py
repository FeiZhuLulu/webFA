from __future__ import annotations

import pytest

from browser.object_registry import (
    ObjectRegistry,
    WebObjectNotFoundError,
    WebRevisionUnavailableError,
)
from browser.web_object_compiler import WebObjectCompilation, WebObjectProvenance
from schemas.web import (
    WebObject,
    WebObjectRelations,
    WebObjectState,
    WebOutlineItem,
    WebRegionRef,
    WebState,
)


def _object(
    object_id: str,
    role: str,
    name: str,
    *,
    parent: str | None = None,
    value=None,
    busy: bool = False,
    text: str = "",
) -> WebObject:
    category = {
        "document": "document",
        "main": "container",
        "heading": "content",
        "textbox": "interactive",
        "button": "interactive",
        "status": "dialog",
    }.get(role, "interactive")
    return WebObject(
        id=object_id,
        category=category,
        role=role,
        name=name,
        text=text,
        value=value,
        state=WebObjectState(visible=True, enabled=True, busy=busy),
        relations=WebObjectRelations(parent=parent),
        capabilities=["set_value", "clear_value"] if role == "textbox" else ["activate"] if role == "button" else [],
        origin="https://example.com",
        frame_id="frame_1",
    )


def _compilation(
    *,
    document_id: str = "doc_a",
    field_id: str = "tmp_field",
    field_value: str = "",
    field_backend_id: int | None = 101,
    field_ax_id: str | None = "ax_field",
    field_legacy_id: str | None = "el_1",
    field_busy: bool = False,
    include_button: bool = True,
    title: str = "Page A",
) -> WebObjectCompilation:
    document = _object("tmp_doc", "document", title)
    main = _object("tmp_main", "main", "Main", parent="tmp_doc")
    field = _object(
        field_id,
        "textbox",
        "Search",
        parent="tmp_main",
        value=field_value,
        busy=field_busy,
    )
    objects = [document, main, field]
    provenance = {
        "tmp_doc": WebObjectProvenance(sources=("runtime",), compiler_rules=("document_root",)),
        "tmp_main": WebObjectProvenance(
            sources=("accessibility",),
            compiler_rules=("ax_role:main",),
            ax_node_id="ax_main",
            backend_dom_node_id=100,
        ),
        field_id: WebObjectProvenance(
            sources=("legacy_probe", "accessibility", "dom_snapshot"),
            compiler_rules=("legacy_role:textbox", "ax_match", "dom_match"),
            legacy_id=field_legacy_id,
            ax_node_id=field_ax_id,
            backend_dom_node_id=field_backend_id,
        ),
    }
    if include_button:
        button = _object("tmp_button", "button", "Submit", parent="tmp_main")
        objects.append(button)
        provenance["tmp_button"] = WebObjectProvenance(
            sources=("legacy_probe",),
            compiler_rules=("legacy_role:button",),
            legacy_id="el_2",
        )
    document.relations.children = ["tmp_main"]
    main.relations.children = [field_id] + (["tmp_button"] if include_button else [])

    state = WebState(
        session_id="default",
        document_id=document_id,
        document_revision=1,
        url="https://example.com/a" if document_id == "doc_a" else "https://example.com/b",
        title=title,
        objects=objects,
        object_count=len(objects),
        outline=[WebOutlineItem(object_id="tmp_main", level=1, name="Main")],
        regions=[WebRegionRef(object_id="tmp_main", role="main", name="Main")],
    )
    return WebObjectCompilation(state=state, provenance=provenance)


def _by_role(state: WebState, role: str) -> list[WebObject]:
    return [item for item in state.objects if isinstance(item, WebObject) and item.role == role]


def test_first_update_assigns_stable_ids_and_initial_revision():
    registry = ObjectRegistry()

    registered = registry.update(_compilation())

    assert registered.state.document_revision == 1
    assert registered.changes.from_revision == 0
    assert registered.changes.to_revision == 1
    assert len(registered.changes.added) == registered.state.object_count
    assert all(item.id.startswith("obj_") for item in registered.state.objects)
    assert registered.state.outline[0].object_id == _by_role(registered.state, "main")[0].id
    assert registered.state.regions[0].object_id == _by_role(registered.state, "main")[0].id


def test_identical_update_keeps_ids_versions_and_revision():
    registry = ObjectRegistry()
    first = registry.update(_compilation())
    second = registry.update(_compilation())

    assert second.state.document_revision == first.state.document_revision
    assert second.changes.added == []
    assert second.changes.updated == []
    assert second.changes.removed == []
    assert second.changes.document_changed_fields == []
    assert {
        (item.role, item.name): (item.id, item.version)
        for item in second.state.objects
    } == {
        (item.role, item.name): (item.id, item.version)
        for item in first.state.objects
    }


def test_backend_identity_survives_transient_compiler_id_change():
    registry = ObjectRegistry()
    first = registry.update(_compilation(field_id="tmp_field_a"))
    second = registry.update(_compilation(field_id="completely_new_temp_id", field_legacy_id=None))

    first_field = _by_role(first.state, "textbox")[0]
    second_field = _by_role(second.state, "textbox")[0]
    assert second_field.id == first_field.id
    assert second_field.version == 1
    assert second.state.document_revision == 1


def test_meaningful_value_change_increments_object_version_and_revision():
    registry = ObjectRegistry()
    first = registry.update(_compilation(field_value=""))
    second = registry.update(_compilation(field_value="webfa"))

    first_field = _by_role(first.state, "textbox")[0]
    second_field = _by_role(second.state, "textbox")[0]
    assert second_field.id == first_field.id
    assert second_field.version == first_field.version + 1
    assert second.state.document_revision == first.state.document_revision + 1
    update = next(item for item in second.changes.updated if item.id == second_field.id)
    assert "value" in update.changed_fields


def test_busy_only_change_is_ambient_and_does_not_increment_revision():
    registry = ObjectRegistry()
    first = registry.update(_compilation(field_busy=False))
    second = registry.update(_compilation(field_busy=True))

    assert second.state.document_revision == first.state.document_revision
    assert second.changes.updated == []
    assert _by_role(second.state, "textbox")[0].state.busy is True


def test_added_and_removed_objects_produce_compact_changes():
    registry = ObjectRegistry()
    first = registry.update(_compilation(include_button=True))
    button_id = _by_role(first.state, "button")[0].id
    second = registry.update(_compilation(include_button=False))

    assert second.changes.removed == [button_id]
    assert second.changes.invalidated == []
    assert second.state.document_revision == 2


def test_navigation_invalidates_previous_document_objects():
    registry = ObjectRegistry()
    first = registry.update(_compilation(document_id="doc_a"))
    second = registry.update(_compilation(document_id="doc_b", title="Page B"))

    previous_ids = {item.id for item in first.state.objects}
    current_ids = {item.id for item in second.state.objects}
    assert previous_ids.isdisjoint(current_ids)
    assert {"document_id", "url", "title"}.issubset(set(second.changes.document_changed_fields))
    assert set(second.changes.invalidated) == previous_ids
    assert second.changes.removed == []
    assert len(second.changes.added) == second.state.object_count
    assert second.state.document_revision == 2


def test_changes_since_aggregates_from_retained_revision():
    registry = ObjectRegistry()
    first = registry.update(_compilation(field_value=""))
    second = registry.update(_compilation(field_value="one"))
    third = registry.update(_compilation(field_value="two", include_button=False))

    changes = registry.changes_since(first.state.document_revision)
    field = _by_role(third.state, "textbox")[0]
    removed_button = _by_role(second.state, "button")[0]

    assert changes.from_revision == 1
    assert changes.to_revision == 3
    assert changes.document_changed_fields == []
    assert next(item for item in changes.updated if item.id == field.id).to_version == 3
    assert removed_button.id in changes.removed


def test_registry_exposes_internal_legacy_binding_for_future_executor():
    registry = ObjectRegistry()
    registered = registry.update(_compilation())
    field = _by_role(registered.state, "textbox")[0]

    assert registry.require(field.id).name == "Search"
    assert registry.legacy_target_for(field.id) == "el_1"
    with pytest.raises(WebObjectNotFoundError):
        registry.require("obj_missing")


def test_unique_semantic_fallback_keeps_identity_without_engine_ids():
    registry = ObjectRegistry()
    first = registry.update(
        _compilation(
            field_id="temporary_a",
            field_backend_id=None,
            field_ax_id=None,
            field_legacy_id=None,
        )
    )
    second = registry.update(
        _compilation(
            field_id="temporary_b",
            field_backend_id=None,
            field_ax_id=None,
            field_legacy_id=None,
        )
    )

    assert _by_role(second.state, "textbox")[0].id == _by_role(first.state, "textbox")[0].id


def test_engine_frame_identity_survives_legacy_frame_enumeration_change():
    registry = ObjectRegistry()

    def frame_compilation(temp_id: str, legacy_id: str) -> WebObjectCompilation:
        document = _object("tmp_doc", "document", "Page")
        frame = WebObject(
            id=temp_id,
            category="frame",
            role="frame",
            name="Main frame",
            state=WebObjectState(visible=True, enabled=True),
            relations=WebObjectRelations(parent="tmp_doc"),
            origin="https://example.com",
            frame_id=legacy_id,
            lifetime="frame",
        )
        document.relations.children = [temp_id]
        return WebObjectCompilation(
            state=WebState(
                document_id="doc_a",
                url="https://example.com",
                title="Page",
                objects=[document, frame],
                object_count=2,
            ),
            provenance={
                "tmp_doc": WebObjectProvenance(
                    sources=("runtime",), compiler_rules=("document_root",)
                ),
                temp_id: WebObjectProvenance(
                    sources=("probe_frame", "engine_frame"),
                    compiler_rules=("frame_metadata",),
                    legacy_id=legacy_id,
                    engine_frame_id="cdp-frame-main",
                ),
            },
        )

    first = registry.update(frame_compilation("temp_frame_a", "frame_1"))
    second = registry.update(frame_compilation("temp_frame_b", "frame_9"))

    assert _by_role(second.state, "frame")[0].id == _by_role(first.state, "frame")[0].id


def test_unavailable_old_revision_is_explicit():
    registry = ObjectRegistry(history_limit=2)
    registry.update(_compilation(field_value=""))
    registry.update(_compilation(field_value="one"))
    registry.update(_compilation(field_value="two"))

    with pytest.raises(WebRevisionUnavailableError):
        registry.changes_since(1)


def test_ambiguous_duplicate_semantic_objects_are_not_wrongly_merged():
    registry = ObjectRegistry()
    first_compilation = _compilation(include_button=False)
    first_compilation.state.objects.extend(
        [
            _object("tmp_status_a", "status", "Updated", parent="tmp_main"),
            _object("tmp_status_b", "status", "Updated", parent="tmp_main"),
        ]
    )
    first_compilation.state.object_count += 2
    first_compilation.provenance["tmp_status_a"] = WebObjectProvenance(
        sources=("accessibility",), compiler_rules=("ax_role:status",)
    )
    first_compilation.provenance["tmp_status_b"] = WebObjectProvenance(
        sources=("accessibility",), compiler_rules=("ax_role:status",)
    )
    first = registry.update(first_compilation)

    second_compilation = _compilation(include_button=False)
    second_compilation.state.objects.extend(
        [
            _object("new_status_a", "status", "Updated", parent="tmp_main"),
            _object("new_status_b", "status", "Updated", parent="tmp_main"),
        ]
    )
    second_compilation.state.object_count += 2
    second_compilation.provenance["new_status_a"] = WebObjectProvenance(
        sources=("accessibility",), compiler_rules=("ax_role:status",)
    )
    second_compilation.provenance["new_status_b"] = WebObjectProvenance(
        sources=("accessibility",), compiler_rules=("ax_role:status",)
    )
    second = registry.update(second_compilation)

    first_status_ids = {item.id for item in _by_role(first.state, "status")}
    second_status_ids = {item.id for item in _by_role(second.state, "status")}
    assert first_status_ids.isdisjoint(second_status_ids)
    assert len(second_status_ids) == 2
