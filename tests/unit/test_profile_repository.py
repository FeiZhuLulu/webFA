from __future__ import annotations

from pathlib import Path

import pytest

from browser.profile_policy import ProfilePolicyStore
from browser.profile_repository import (
    BrowserSessionRepository,
    ProfileConflictError,
    ProfileRepository,
    ProfileStateError,
    ProfileVersionConflictError,
)
from schemas.profile import BrowserProfileCreate, BrowserProfileUpdate
from schemas.safety import ProfileOwnershipMetadata
from storage.db import init_db, reset_engine_for_tests


def _repository(monkeypatch, tmp_path: Path) -> ProfileRepository:
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()
    init_db()
    return ProfileRepository()


def test_profile_catalog_persists_and_separates_agent_projection(monkeypatch, tmp_path: Path):
    repository = _repository(monkeypatch, tmp_path)
    default = repository.ensure_default_profile()
    profile = repository.create_profile(
        BrowserProfileCreate(
            agent_alias="work",
            display_name="Fei Work Account",
            agent_description="Work sites and accounts",
            owner="user_owned",
            trust_mode="guarded",
            bound_agent_ids=["agent-a", "agent-a"],
            allowed_origins=["https://example.com"],
        )
    )

    assert default.profile_id == "default"
    assert profile.agent_alias == "work"
    assert profile.bound_agent_ids == ["agent-a"]
    assert profile.storage_ref == f"profiles/{profile.profile_id}"

    agent_view = profile.agent_view().model_dump()
    assert agent_view["agent_alias"] == "work"
    assert "display_name" not in agent_view
    assert "storage_ref" not in agent_view

    reloaded = ProfileRepository().get_profile("work")
    assert reloaded.profile_id == profile.profile_id
    assert reloaded.display_name == "Fei Work Account"


def test_profile_alias_and_version_conflicts_are_deterministic(monkeypatch, tmp_path: Path):
    repository = _repository(monkeypatch, tmp_path)
    repository.ensure_default_profile()
    profile = repository.create_profile(
        BrowserProfileCreate(agent_alias="personal", display_name="Personal")
    )

    with pytest.raises(ProfileConflictError):
        repository.create_profile(
            BrowserProfileCreate(agent_alias="personal", display_name="Duplicate")
        )

    updated = repository.update_profile(
        profile.profile_id,
        BrowserProfileUpdate(
            expected_version=profile.version,
            display_name="Personal Updated",
            bound_agent_ids=["agent-b"],
        ),
    )
    assert updated.version == 2
    assert updated.bound_agent_ids == ["agent-b"]

    with pytest.raises(ProfileVersionConflictError):
        repository.update_profile(
            profile.profile_id,
            BrowserProfileUpdate(expected_version=1, display_name="Stale"),
        )


def test_profile_policy_store_uses_persistent_profile_catalog(monkeypatch, tmp_path: Path):
    repository = _repository(monkeypatch, tmp_path)
    repository.ensure_default_profile()
    store = ProfilePolicyStore(repository=repository)

    stored = store.upsert(
        ProfileOwnershipMetadata(
            profile_id="default",
            owner="agent_owned",
            trust_mode="trusted_agent",
            bound_agent_ids=["agent-a"],
            allowed_origins=["https://example.com"],
        )
    )

    assert stored.owner == "agent_owned"
    assert stored.unknown_external_effect_policy == "allow_with_audit"
    reloaded = ProfilePolicyStore(repository=ProfileRepository()).get("default")
    assert reloaded.bound_agent_ids == ["agent-a"]
    assert reloaded.allowed_origins == ["https://example.com"]


def test_session_metadata_lifecycle_and_interruption(monkeypatch, tmp_path: Path):
    repository = _repository(monkeypatch, tmp_path)
    profile = repository.ensure_default_profile()
    sessions = BrowserSessionRepository()
    created = sessions.create_session(
        session_id="session_test",
        profile_id=profile.profile_id,
        runtime_generation="generation_test",
    )
    assert created.lifecycle == "created"

    running = sessions.transition("session_test", lifecycle="running")
    assert running.lifecycle == "running"
    assert running.started_at is not None

    assert sessions.interrupt_nonterminal_sessions(profile_id=profile.profile_id) == 1
    interrupted = sessions.get_session("session_test")
    assert interrupted.lifecycle == "interrupted"
    assert interrupted.health == "failed"
    assert interrupted.stopped_at is not None

    with pytest.raises(ProfileConflictError):
        sessions.create_session(
            session_id="session_invalid_profile",
            profile_id="missing-profile",
            runtime_generation="generation_invalid",
        )


def test_profile_archive_rejects_default_and_active_session(monkeypatch, tmp_path: Path):
    repository = _repository(monkeypatch, tmp_path)
    default = repository.ensure_default_profile()
    with pytest.raises(ProfileStateError, match="default profile"):
        repository.archive_profile(default.profile_id, expected_version=default.version)

    profile = repository.create_profile(
        BrowserProfileCreate(agent_alias="active", display_name="Active")
    )
    sessions = BrowserSessionRepository()
    sessions.create_session(
        session_id="session_active_profile",
        profile_id=profile.profile_id,
        runtime_generation="generation_active",
    )
    sessions.transition("session_active_profile", lifecycle="running")

    with pytest.raises(ProfileStateError, match="active session"):
        repository.archive_profile(profile.profile_id, expected_version=profile.version)

    unchanged = repository.get_profile(profile.profile_id)
    assert unchanged.catalog_state == "ready"
    assert unchanged.version == profile.version


def test_profile_policy_update_remains_available_for_active_session_revocation(monkeypatch, tmp_path: Path):
    repository = _repository(monkeypatch, tmp_path)
    profile = repository.create_profile(
        BrowserProfileCreate(agent_alias="immutable", display_name="Immutable")
    )
    sessions = BrowserSessionRepository()
    sessions.create_session(
        session_id="session_immutable_profile",
        profile_id=profile.profile_id,
        runtime_generation="generation_immutable",
    )
    sessions.transition("session_immutable_profile", lifecycle="running")

    updated = repository.update_profile(
        profile.profile_id,
        BrowserProfileUpdate(
            expected_version=profile.version,
            owner="agent_owned",
            bound_agent_ids=["different-agent"],
        ),
    )

    assert updated.owner == "agent_owned"
    assert updated.bound_agent_ids == ["different-agent"]
    assert updated.version == profile.version + 1
