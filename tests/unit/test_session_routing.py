from __future__ import annotations

from datetime import datetime, timezone

import pytest

from browser.runtime_errors import BrowserRuntimeError
from browser.session_routing import (
    AgentConnectionRegistry,
    AgentProfileGrantManager,
    AgentSessionLeaseManager,
    GlobalRouteRegistry,
)
from schemas.profile import BrowserProfile
from schemas.web import (
    WebObject,
    WebObjectRelations,
    WebObserveRequest,
    WebOperationRequest,
    WebState,
)


def _profile(*, profile_id: str = "profile-a", bound_agent_ids: list[str] | None = None) -> BrowserProfile:
    now = datetime.now(timezone.utc)
    return BrowserProfile(
        profile_id=profile_id,
        agent_alias=profile_id,
        display_name=profile_id,
        persistence="persistent",
        owner="shared",
        trust_mode="trusted_agent",
        bound_agent_ids=bound_agent_ids or [],
        allowed_origins=[],
        unknown_external_effect_policy="require_step_up",
        storage_ref=f"profiles/{profile_id}",
        bootstrap_source="blank",
        catalog_state="ready",
        version=1,
        created_at=now,
        updated_at=now,
    )


def test_connection_identity_cannot_change() -> None:
    registry = AgentConnectionRegistry()
    registry.get_or_create(connection_id="conn-a", agent_id="agent-a")

    with pytest.raises(BrowserRuntimeError) as excinfo:
        registry.get_or_create(connection_id="conn-a", agent_id="agent-b")

    assert excinfo.value.code == "connection_identity_mismatch"


def test_profile_grant_enforces_bound_agents() -> None:
    grants = AgentProfileGrantManager()
    profile = _profile(bound_agent_ids=["agent-a"])

    grant = grants.authorize(profile=profile, agent_id="agent-a", connection_id="conn-a")
    assert grant.profile_id == profile.profile_id

    with pytest.raises(BrowserRuntimeError) as excinfo:
        grants.authorize(profile=profile, agent_id="agent-b", connection_id="conn-b")
    assert excinfo.value.code == "profile_access_denied"


def test_session_lease_is_connection_exclusive() -> None:
    leases = AgentSessionLeaseManager()
    leases.acquire(
        agent_id="agent-a",
        connection_id="conn-a",
        session_id="session-a",
        profile_id="profile-a",
        runtime_generation="generation-a",
    )

    with pytest.raises(BrowserRuntimeError) as excinfo:
        leases.acquire(
            agent_id="agent-a",
            connection_id="conn-b",
            session_id="session-a",
            profile_id="profile-a",
            runtime_generation="generation-a",
        )
    assert excinfo.value.code == "session_busy"


def test_global_object_routes_project_relations_and_reject_cross_session_use() -> None:
    routes = GlobalRouteRegistry(secret=b"test-secret")
    state = WebState(
        session_id="session-a",
        document_id="document-a",
        document_revision=1,
        objects=[
            WebObject(
                id="local-parent",
                category="container",
                role="form",
                name="Form",
                capabilities=["submit"],
                relations=WebObjectRelations(children=["local-child"]),
            ),
            WebObject(
                id="local-child",
                category="interactive",
                role="textbox",
                name="Name",
                capabilities=["set_value"],
                relations=WebObjectRelations(parent="local-parent", form="local-parent"),
            ),
        ],
        object_count=2,
    )

    projected = routes.project_web_state(
        state,
        profile_id="profile-a",
        runtime_generation="generation-a",
    )
    parent, child = projected.objects
    assert parent.id.startswith("objr_")
    assert child.id.startswith("objr_")
    assert parent.relations.children == [child.id]
    assert child.relations.parent == parent.id
    assert child.relations.form == parent.id

    localized = routes.localize_operation_request(
        WebOperationRequest(target=child.id, operation="set_value", arguments={"value": "Fei"}),
        session_id="session-a",
        runtime_generation="generation-a",
    )
    assert localized.target == "local-child"

    with pytest.raises(BrowserRuntimeError) as excinfo:
        routes.localize_observe_request(
            WebObserveRequest(mode="object", target=child.id),
            session_id="session-b",
            runtime_generation="generation-b",
        )
    assert excinfo.value.code == "object_session_mismatch"
