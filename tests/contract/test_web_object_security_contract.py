from __future__ import annotations

from typing import get_args

from schemas.web import (
    ObjectCapabilityName,
    SemanticOperationName,
    WebObserveQuery,
    WebOperationRequest,
    WebState,
)


FORBIDDEN_AGENT_FIELDS = {
    "cookie",
    "cookies",
    "local_storage",
    "localstorage",
    "session_storage",
    "sessionstorage",
    "token",
    "authorization",
    "password",
    "raw_dom",
    "html",
    "selector",
    "xpath",
    "cdp",
    "evaluate",
    "coordinates",
    "screenshot",
}

FORBIDDEN_PRIMITIVES = {
    "click",
    "double_click",
    "type",
    "press",
    "focus",
}


def _collect_property_names(schema: dict) -> set[str]:
    names: set[str] = set()
    if isinstance(schema, dict):
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            names.update(str(name).lower() for name in properties)
        for value in schema.values():
            if isinstance(value, dict):
                names.update(_collect_property_names(value))
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        names.update(_collect_property_names(item))
    return names


def test_web_state_schema_does_not_expose_sensitive_or_escape_hatch_fields() -> None:
    property_names = _collect_property_names(WebState.model_json_schema())
    assert property_names.isdisjoint(FORBIDDEN_AGENT_FIELDS)


def test_observe_query_has_no_selector_xpath_or_script_escape_hatch() -> None:
    fields = set(WebObserveQuery.model_fields)
    assert fields.isdisjoint({"selector", "xpath", "locator", "script", "expression", "evaluate"})


def test_semantic_capabilities_exclude_human_browser_primitives() -> None:
    capabilities = set(get_args(ObjectCapabilityName))
    operations = set(get_args(SemanticOperationName))

    assert capabilities == operations
    assert capabilities.isdisjoint(FORBIDDEN_PRIMITIVES)
    assert {
        "open",
        "activate",
        "set_value",
        "choose",
        "toggle",
        "submit",
        "dismiss",
        "request_human_takeover",
    }.issubset(capabilities)


def test_operation_request_has_no_primitive_action_field() -> None:
    fields = set(WebOperationRequest.model_fields)
    assert "operation" in fields
    assert "action" not in fields
