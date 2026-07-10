from __future__ import annotations

import pytest
from pydantic import ValidationError

from schemas.web import (
    CapabilityDescriptor,
    HumanTakeoverState,
    WebChangeSet,
    WebObject,
    WebObjectSummary,
    WebObjectUpdate,
    WebObserveQuery,
    WebObserveRequest,
    WebOperationRequest,
    WebState,
)


def test_web_object_expresses_state_relations_capabilities_and_version() -> None:
    obj = WebObject(
        id="field_search",
        category="interactive",
        role="searchbox",
        name="Search repositories",
        capabilities=["set_value", "clear_value", "submit"],
        version=3,
        origin="https://github.com",
        relations={"form": "form_search", "parent": "region_header"},
        state={"visible": True, "enabled": True, "required": False},
    )

    assert obj.projection == "full"
    assert obj.state.enabled is True
    assert obj.relations.form == "form_search"
    assert obj.capabilities == ["set_value", "clear_value", "submit"]
    assert obj.version == 3


def test_opaque_surface_requires_explicit_reason() -> None:
    with pytest.raises(ValidationError, match="opaque surfaces require opaque_reason"):
        WebObject(
            id="opaque_editor",
            category="opaque_surface",
            role="opaque_surface",
            name="Diagram editor",
            capabilities=["request_human_takeover"],
        )

    obj = WebObject(
        id="opaque_editor",
        category="opaque_surface",
        role="opaque_surface",
        name="Diagram editor",
        opaque_reason="semantic_structure_unavailable",
        capabilities=["request_human_takeover"],
    )
    assert obj.opaque_reason == "semantic_structure_unavailable"


def test_observe_request_modes_have_distinct_shapes() -> None:
    assert WebObserveRequest().mode == "page"
    assert WebObserveRequest(mode="object", target="collection_results").target == "collection_results"
    assert WebObserveRequest(
        mode="query",
        query=WebObserveQuery(role="link", name_contains="webFA"),
        limit=20,
    ).query is not None
    assert WebObserveRequest(mode="changes", since_revision=12).since_revision == 12

    with pytest.raises(ValidationError, match="object mode requires target"):
        WebObserveRequest(mode="object")
    with pytest.raises(ValidationError, match="query mode requires query"):
        WebObserveRequest(mode="query")
    with pytest.raises(ValidationError, match="changes mode requires since_revision"):
        WebObserveRequest(mode="changes")
    with pytest.raises(ValidationError, match="page mode does not accept"):
        WebObserveRequest(mode="page", target="obj_1")


def test_query_requires_a_semantic_filter_and_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="query requires at least one filter"):
        WebObserveQuery()
    with pytest.raises(ValidationError):
        WebObserveQuery.model_validate({"selector": "#submit"})


def test_changeset_tracks_object_versions() -> None:
    changes = WebChangeSet(
        from_revision=4,
        to_revision=5,
        added=[
            WebObjectSummary(
                id="dialog_1",
                category="dialog",
                role="dialog",
                name="Confirm",
                capabilities=["dismiss"],
                version=1,
            )
        ],
        updated=[
            WebObjectUpdate(
                id="field_search",
                from_version=2,
                to_version=3,
                changed_fields=["value"],
            )
        ],
    )

    assert changes.added[0].projection == "summary"
    assert changes.updated[0].changed_fields == ["value"]

    with pytest.raises(ValidationError, match="to_version must be greater"):
        WebObjectUpdate(id="obj_1", from_version=2, to_version=2)


def test_web_state_supports_summary_and_full_object_projections() -> None:
    summary = WebObjectSummary(
        id="link_1",
        category="interactive",
        role="link",
        name="WebFA",
        capabilities=["open"],
    )
    full = WebObject(
        id="form_1",
        category="interactive",
        role="form",
        name="Search",
        capabilities=["submit"],
    )
    state = WebState(
        document_id="doc_1",
        document_revision=7,
        objects=[summary, full],
        object_count=20,
    )

    assert state.objects[0].projection == "summary"
    assert state.objects[1].projection == "full"
    assert state.object_count == 20

    with pytest.raises(ValidationError, match="object_count cannot be smaller"):
        WebState(objects=[summary], object_count=0)


def test_semantic_operation_schema_rejects_browser_primitives() -> None:
    request = WebOperationRequest(
        target="button_submit",
        operation="activate",
        expected_object_version=2,
    )
    assert request.operation == "activate"

    for primitive in ("click", "type", "press", "double_click"):
        with pytest.raises(ValidationError):
            WebOperationRequest.model_validate(
                {"target": "obj_1", "operation": primitive, "arguments": {}}
            )


def test_capability_effect_metadata_is_part_of_the_protocol() -> None:
    descriptor = CapabilityDescriptor(
        name="submit",
        effect="external_write",
        requires_confirmation=True,
    )
    assert descriptor.effect == "external_write"
    assert descriptor.requires_confirmation is True


def test_takeover_requires_an_explicit_reason() -> None:
    with pytest.raises(ValidationError, match="required takeover needs a reason"):
        HumanTakeoverState(required=True)

    takeover = HumanTakeoverState(
        required=True,
        reason="opaque_surface",
        target="opaque_1",
        origin="https://example.com",
    )
    assert takeover.resume_operation == "observe"
