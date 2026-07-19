from __future__ import annotations

from datetime import datetime, timedelta, timezone

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


def test_active_profile_grant_renews_on_each_successful_use() -> None:
    now = [datetime(2026, 7, 19, tzinfo=timezone.utc)]
    grants = AgentProfileGrantManager(ttl_seconds=60, clock=lambda: now[0])
    profile = _profile()

    issued = grants.authorize(profile=profile, agent_id="agent-a", connection_id="conn-a")
    now[0] += timedelta(seconds=50)
    renewed = grants.require(
        connection_id="conn-a",
        agent_id="agent-a",
        profile=profile,
    )

    assert renewed.grant_id == issued.grant_id
    assert renewed.issued_at == issued.issued_at
    assert renewed.expires_at == now[0] + timedelta(seconds=60)
    now[0] += timedelta(seconds=20)
    assert grants.require(
        connection_id="conn-a",
        agent_id="agent-a",
        profile=profile,
    ).grant_id == issued.grant_id


def test_expired_profile_grant_is_not_resurrected_by_use() -> None:
    now = [datetime(2026, 7, 19, tzinfo=timezone.utc)]
    grants = AgentProfileGrantManager(ttl_seconds=60, clock=lambda: now[0])
    profile = _profile()
    grants.authorize(profile=profile, agent_id="agent-a", connection_id="conn-a")
    now[0] += timedelta(seconds=61)

    with pytest.raises(BrowserRuntimeError) as excinfo:
        grants.require(connection_id="conn-a", agent_id="agent-a", profile=profile)

    assert excinfo.value.code == "profile_grant_required"


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


def test_active_session_lease_renews_on_write_and_read_activity() -> None:
    now = [datetime(2026, 7, 19, tzinfo=timezone.utc)]
    leases = AgentSessionLeaseManager(ttl_seconds=30, clock=lambda: now[0])
    issued = leases.acquire(
        agent_id="agent-a",
        connection_id="conn-a",
        session_id="session-a",
        profile_id="profile-a",
        runtime_generation="generation-a",
    )

    now[0] += timedelta(seconds=20)
    write_renewed = leases.require(
        agent_id="agent-a",
        connection_id="conn-a",
        session_id="session-a",
        profile_id="profile-a",
        runtime_generation="generation-a",
    )
    assert write_renewed.lease_id == issued.lease_id
    assert write_renewed.expires_at == now[0] + timedelta(seconds=30)

    now[0] += timedelta(seconds=20)
    read_renewed = leases.renew_if_owned(
        agent_id="agent-a",
        connection_id="conn-a",
        session_id="session-a",
        profile_id="profile-a",
        runtime_generation="generation-a",
    )
    assert read_renewed is not None
    assert read_renewed.lease_id == issued.lease_id
    assert read_renewed.expires_at == now[0] + timedelta(seconds=30)


def test_expired_session_lease_is_not_resurrected_by_read_activity() -> None:
    now = [datetime(2026, 7, 19, tzinfo=timezone.utc)]
    leases = AgentSessionLeaseManager(ttl_seconds=30, clock=lambda: now[0])
    leases.acquire(
        agent_id="agent-a",
        connection_id="conn-a",
        session_id="session-a",
        profile_id="profile-a",
        runtime_generation="generation-a",
    )
    now[0] += timedelta(seconds=31)

    assert leases.renew_if_owned(
        agent_id="agent-a",
        connection_id="conn-a",
        session_id="session-a",
        profile_id="profile-a",
        runtime_generation="generation-a",
    ) is None


def test_session_lease_uses_the_documented_agent_lease_ttl(monkeypatch) -> None:
    now = datetime(2026, 7, 19, tzinfo=timezone.utc)
    monkeypatch.setenv("WEBFA_AGENT_LEASE_TTL_SECONDS", "75")
    lease = AgentSessionLeaseManager(clock=lambda: now).acquire(
        agent_id="agent-a",
        connection_id="conn-a",
        session_id="session-a",
        profile_id="profile-a",
        runtime_generation="generation-a",
    )

    assert lease.expires_at == now + timedelta(seconds=75)


@pytest.mark.parametrize(
    ("profile_id", "runtime_generation", "expected_code"),
    [
        ("profile-b", "generation-a", "session_profile_mismatch"),
        ("profile-a", "generation-b", "session_generation_mismatch"),
    ],
)
def test_session_lease_rejects_stale_profile_or_generation_binding(
    profile_id: str,
    runtime_generation: str,
    expected_code: str,
) -> None:
    leases = AgentSessionLeaseManager()
    leases.acquire(
        agent_id="agent-a",
        connection_id="conn-a",
        session_id="session-a",
        profile_id="profile-a",
        runtime_generation="generation-a",
    )

    with pytest.raises(BrowserRuntimeError) as excinfo:
        leases.require(
            agent_id="agent-a",
            connection_id="conn-a",
            session_id="session-a",
            profile_id=profile_id,
            runtime_generation=runtime_generation,
        )

    assert excinfo.value.code == expected_code


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
