from __future__ import annotations

import pytest

from browser.object_registry import ObjectRegistry
from browser.semantic_operations import (
    SemanticOperationExecutor,
    WebDocumentRevisionConflictError,
    WebObjectVersionConflictError,
    WebOperationArgumentError,
    WebOperationNotSupportedError,
    WebOperationUnavailableError,
)
from browser.web_capabilities import capability_descriptors
from browser.web_object_compiler import WebObjectCompilation, WebObjectProvenance
from schemas.web import (
    WebObject,
    WebObjectRelations,
    WebObjectState,
    WebOperationRequest,
    WebState,
)


class RecordingDriver:
    def __init__(self) -> None:
        self.actions = []

    def act(self, request) -> None:
        self.actions.append(request)


def _object(
    object_id: str,
    role: str,
    name: str,
    *,
    category: str = "interactive",
    capabilities: list[str] | None = None,
    legacy_id: str | None = None,
    checked: bool | None = None,
    expanded: bool | None = None,
    visible: bool = True,
    enabled: bool = True,
    relations: WebObjectRelations | None = None,
) -> tuple[WebObject, WebObjectProvenance]:
    item = WebObject(
        id=object_id,
        category=category,
        role=role,
        name=name,
        capabilities=capabilities or [],
        state=WebObjectState(
            visible=visible,
            enabled=enabled,
            checked=checked,
            expanded=expanded,
        ),
        relations=relations or WebObjectRelations(),
        origin="https://example.com",
        frame_id="frame_1",
    )
    provenance = WebObjectProvenance(
        sources=("fixture",),
        compiler_rules=("fixture",),
        legacy_id=legacy_id,
    )
    return item, provenance


def _registry() -> tuple[ObjectRegistry, dict[str, WebObject]]:
    field, field_provenance = _object(
        "tmp_field",
        "textbox",
        "Name",
        capabilities=["set_value", "clear_value"],
        legacy_id="el_field",
    )
    checkbox, checkbox_provenance = _object(
        "tmp_checkbox",
        "checkbox",
        "Enabled",
        capabilities=["toggle"],
        legacy_id="el_checkbox",
        checked=False,
    )
    submit, submit_provenance = _object(
        "tmp_submit",
        "button",
        "Submit",
        capabilities=["activate"],
        legacy_id="el_submit",
    )
    form, form_provenance = _object(
        "tmp_form",
        "form",
        "Profile",
        category="container",
        capabilities=["submit"],
        legacy_id="form_1",
        relations=WebObjectRelations(
            children=["tmp_field", "tmp_checkbox", "tmp_submit"],
            submit_control="tmp_submit",
        ),
    )
    link, link_provenance = _object(
        "tmp_link",
        "link",
        "Example",
        capabilities=["open"],
        legacy_id="el_link",
    )
    password, password_provenance = _object(
        "tmp_password",
        "textbox",
        "Password",
        capabilities=["request_human_takeover"],
        legacy_id="el_password",
    )
    objects = [field, checkbox, submit, form, link, password]
    registry = ObjectRegistry()
    registry.update(
        WebObjectCompilation(
            state=WebState(
                document_id="doc_1",
                document_revision=1,
                url="https://example.com/form",
                title="Form",
                objects=objects,
                object_count=len(objects),
            ),
            provenance={
                field.id: field_provenance,
                checkbox.id: checkbox_provenance,
                submit.id: submit_provenance,
                form.id: form_provenance,
                link.id: link_provenance,
                password.id: password_provenance,
            },
        )
    )
    current = {
        item.name: item
        for item in registry.current_state().objects
        if isinstance(item, WebObject)
    }
    return registry, current


def test_capability_registry_defines_complete_target_without_primitives():
    descriptors = capability_descriptors()

    assert {
        "open",
        "open_in_new_context",
        "activate",
        "set_value",
        "clear_value",
        "choose",
        "toggle",
        "submit",
        "expand",
        "collapse",
        "dismiss",
        "download",
        "upload",
        "provide_payment_instrument",
        "request_human_takeover",
    } == set(descriptors)
    assert descriptors["submit"].effect == "external_write"
    assert descriptors["submit"].requires_confirmation is True
    assert set(descriptors).isdisjoint({"click", "type", "press", "focus", "double_click"})


def test_set_value_translates_to_internal_clear_and_type_actions():
    registry, objects = _registry()
    executor = SemanticOperationExecutor(registry)
    driver = RecordingDriver()
    field = objects["Name"]

    plan = executor.plan(
        WebOperationRequest(
            target=field.id,
            operation="set_value",
            arguments={"value": "Fei"},
            expected_object_version=field.version,
        )
    )
    executor.execute(driver, plan)

    assert [item.action for item in driver.actions] == ["clear", "type"]
    assert [item.target for item in driver.actions] == ["el_field", "el_field"]
    assert driver.actions[1].text == "Fei"


def test_submit_targets_the_forms_declared_submit_control():
    registry, objects = _registry()
    executor = SemanticOperationExecutor(registry)
    driver = RecordingDriver()

    plan = executor.plan(
        WebOperationRequest(target=objects["Profile"].id, operation="submit")
    )
    executor.execute(driver, plan)

    assert len(driver.actions) == 1
    assert driver.actions[0].action == "click"
    assert driver.actions[0].target == "el_submit"


def test_toggle_supports_desired_state_and_no_op():
    registry, objects = _registry()
    executor = SemanticOperationExecutor(registry)
    checkbox = objects["Enabled"]

    no_op = executor.plan(
        WebOperationRequest(
            target=checkbox.id,
            operation="toggle",
            arguments={"checked": False},
        )
    )
    toggle = executor.plan(
        WebOperationRequest(
            target=checkbox.id,
            operation="toggle",
            arguments={"checked": True},
        )
    )

    assert no_op.no_op is True
    assert toggle.actions[0].action == "click"
    assert toggle.actions[0].target == "el_checkbox"


def test_document_revision_conflict_is_explicit():
    registry, objects = _registry()
    executor = SemanticOperationExecutor(registry)
    field = objects["Name"]

    with pytest.raises(WebDocumentRevisionConflictError) as raised:
        executor.plan(
            WebOperationRequest(
                target=field.id,
                operation="clear_value",
                expected_document_revision=999,
            )
        )

    assert raised.value.code == "document_revision_conflict"
    assert "Observe" in raised.value.recover_hint


def test_object_version_conflict_is_explicit():
    registry, objects = _registry()
    executor = SemanticOperationExecutor(registry)
    field = objects["Name"]

    with pytest.raises(WebObjectVersionConflictError) as raised:
        executor.plan(
            WebOperationRequest(
                target=field.id,
                operation="clear_value",
                expected_object_version=field.version + 1,
            )
        )

    assert raised.value.code == "object_version_conflict"
    assert "Observe" in raised.value.recover_hint


def test_operation_must_be_declared_by_the_object():
    registry, objects = _registry()
    executor = SemanticOperationExecutor(registry)

    with pytest.raises(WebOperationNotSupportedError) as raised:
        executor.plan(
            WebOperationRequest(target=objects["Example"].id, operation="activate")
        )

    assert raised.value.code == "operation_not_supported"


def test_operation_arguments_are_strictly_validated():
    registry, objects = _registry()
    executor = SemanticOperationExecutor(registry)

    with pytest.raises(WebOperationArgumentError):
        executor.plan(
            WebOperationRequest(
                target=objects["Name"].id,
                operation="set_value",
                arguments={"value": 42},
            )
        )
    with pytest.raises(WebOperationArgumentError):
        executor.plan(
            WebOperationRequest(
                target=objects["Name"].id,
                operation="clear_value",
                arguments={"value": "unexpected"},
            )
        )


def test_request_human_takeover_is_semantic_and_has_no_driver_actions():
    registry, objects = _registry()
    executor = SemanticOperationExecutor(registry)

    plan = executor.plan(
        WebOperationRequest(
            target=objects["Password"].id,
            operation="request_human_takeover",
        )
    )

    assert plan.actions == ()
    assert plan.takeover_reason == "authentication"


def test_upload_requires_only_an_opaque_resource_reference():
    item, provenance = _object(
        "tmp_upload",
        "upload_target",
        "Attachment",
        capabilities=["upload"],
        legacy_id="el_upload",
    )
    registry = ObjectRegistry()
    registry.update(
        WebObjectCompilation(
            state=WebState(document_id="doc_1", objects=[item], object_count=1),
            provenance={item.id: provenance},
        )
    )
    target = next(item for item in registry.current_state().objects if isinstance(item, WebObject))
    executor = SemanticOperationExecutor(registry)

    plan = executor.plan(
        WebOperationRequest(
            target=target.id,
            operation="upload",
            arguments={"resource_ref": "resource_123", "purpose": "application"},
        )
    )

    assert plan.upload_resource_ref == "resource_123"
    assert plan.upload_purpose == "application"
    assert plan.upload_legacy_target == "el_upload"
    assert plan.actions == ()

    for arguments in (
        {"path": "C:/Users/user/secret.txt"},
        {"file_path": "/home/user/secret.txt"},
        {"resource_id": "legacy-resource"},
    ):
        with pytest.raises(WebOperationArgumentError):
            executor.plan(
                WebOperationRequest(
                    target=target.id,
                    operation="upload",
                    arguments=arguments,
                )
            )


def test_complete_but_unimplemented_resource_operation_reports_unavailable():
    item, provenance = _object(
        "tmp_download",
        "download",
        "Export",
        category="resource",
        capabilities=["download"],
        legacy_id="el_download",
    )
    registry = ObjectRegistry()
    registry.update(
        WebObjectCompilation(
            state=WebState(document_id="doc_1", objects=[item], object_count=1),
            provenance={item.id: provenance},
        )
    )
    target = next(item for item in registry.current_state().objects if isinstance(item, WebObject))

    with pytest.raises(WebOperationUnavailableError) as raised:
        SemanticOperationExecutor(registry).plan(
            WebOperationRequest(target=target.id, operation="download")
        )

    assert raised.value.code == "operation_temporarily_unavailable"
