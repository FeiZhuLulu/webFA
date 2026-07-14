from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from browser.profile_bootstrap import (
    CookieImportBindingError,
    CookieImportBusyError,
    CookieImportParseError,
    ProfileBootstrapService,
    ProfileCloneBindingError,
    ProfileCloneBusyError,
    ProfileCloneSourceChangedError,
    parse_cookie_import,
)
from browser.profile_repository import ProfileConflictError, ProfileRepository
from browser.profile_storage import ProfileLockBusyError, ProfileStorageManager
from schemas.profile import BrowserProfileCreate
from storage.db import init_db, reset_engine_for_tests


def _setup(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()
    init_db()
    repository = ProfileRepository()
    profile = repository.create_profile(
        BrowserProfileCreate(
            agent_alias="import-target",
            display_name="Import Target",
        )
    )
    storage = ProfileStorageManager(tmp_path / "WebFA")
    return repository, profile, storage


def _json_cookie_payload(*, secret: str = "cookie-secret") -> bytes:
    return json.dumps(
        [
            {
                "name": "session_id",
                "value": secret,
                "domain": ".example.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
                "sameSite": "no_restriction",
                "expirationDate": time.time() + 3600,
            },
            {
                "name": "host_cookie",
                "value": "host-secret",
                "domain": "accounts.example.com",
                "hostOnly": True,
                "path": "/login",
                "secure": True,
                "session": True,
            },
            {
                "name": "expired_cookie",
                "value": "expired-secret",
                "domain": "example.com",
                "path": "/",
                "expirationDate": 1,
            },
        ]
    ).encode("utf-8")


def test_json_cookie_preview_is_redacted_and_rejects_expired_entries() -> None:
    parsed = parse_cookie_import(_json_cookie_payload(), input_format="auto")

    assert parsed.source_format == "json"
    assert parsed.total_entries == 3
    assert len(parsed.cookies) == 2
    assert parsed.rejected_count == 1
    warning_codes = {warning.code for warning in parsed.warnings}
    assert "cookie_expired" in warning_codes


def test_netscape_cookie_file_supports_http_only_and_host_only() -> None:
    content = (
        "# Netscape HTTP Cookie File\n"
        "#HttpOnly_.example.com\tTRUE\t/\tTRUE\t4102444800\tsid\tsecret-a\n"
        "accounts.example.com\tFALSE\t/\tFALSE\t0\thost\tsecret-b\n"
    ).encode("utf-8")

    parsed = parse_cookie_import(content, input_format="netscape")

    assert parsed.source_format == "netscape"
    assert parsed.total_entries == 2
    assert len(parsed.cookies) == 2
    assert parsed.cookies[0].http_only is True
    assert parsed.cookies[1].session is True
    assert "url" in parsed.cookies[1].params
    assert "domain" not in parsed.cookies[1].params


def test_cookie_parse_errors_never_include_raw_cookie_values() -> None:
    secret = "do-not-echo-cookie-secret"
    malformed = f'{{"cookies":[{{"name":"sid","value":"{secret}"}}]'.encode()

    with pytest.raises(CookieImportParseError) as exc_info:
        parse_cookie_import(malformed, input_format="json")

    assert secret not in str(exc_info.value)


def test_preview_commit_is_control_bound_single_use_and_updates_profile(monkeypatch, tmp_path: Path) -> None:
    repository, profile, storage = _setup(monkeypatch, tmp_path)
    captured: dict[str, object] = {}

    class FakeMaintenanceHost:
        def __init__(self, selected_profile, selected_storage, mutation_id):
            captured["profile_id"] = selected_profile.profile_id
            captured["mutation_id"] = mutation_id
            captured["storage"] = selected_storage

        def import_cookies(self, cookies):
            captured["cookies"] = cookies
            return len(cookies)

        def close(self):
            captured["closed"] = True

    service = ProfileBootstrapService(
        repository=repository,
        storage=storage,
        host_factory=FakeMaintenanceHost,
    )
    secret = "raw-cookie-never-returned"
    preview = service.preview_cookie_import(
        profile.profile_id,
        expected_version=profile.version,
        content=_json_cookie_payload(secret=secret),
        input_format="auto",
        control_token="control-a",
    )

    serialized_preview = json.dumps(preview.model_dump(mode="json"), sort_keys=True)
    assert secret not in serialized_preview
    assert "session_id" not in serialized_preview
    assert preview.accepted_count == 2
    assert preview.domain_count == 2

    with pytest.raises(CookieImportBindingError):
        service.commit_cookie_import(
            profile.profile_id,
            preview_token=preview.preview_token,
            expected_version=profile.version,
            control_token="control-b",
        )

    result = service.commit_cookie_import(
        profile.profile_id,
        preview_token=preview.preview_token,
        expected_version=profile.version,
        control_token="control-a",
    )

    assert result.status == "cookies_imported"
    assert result.imported_count == 2
    assert result.verified_count == 2
    assert secret not in json.dumps(result.model_dump(mode="json"))
    assert captured["closed"] is True
    assert repository.get_profile(profile.profile_id).bootstrap_source == "imported"
    assert repository.get_profile(profile.profile_id).version == profile.version + 1


def test_preview_can_be_cancelled_only_by_bound_control_session(monkeypatch, tmp_path: Path) -> None:
    repository, profile, storage = _setup(monkeypatch, tmp_path)
    service = ProfileBootstrapService(repository=repository, storage=storage)
    preview = service.preview_cookie_import(
        profile.profile_id,
        expected_version=profile.version,
        content=_json_cookie_payload(),
        input_format="json",
        control_token="control-a",
    )

    with pytest.raises(CookieImportBindingError):
        service.cancel_cookie_import(
            profile.profile_id,
            preview_token=preview.preview_token,
            control_token="control-b",
        )

    cancelled = service.cancel_cookie_import(
        profile.profile_id,
        preview_token=preview.preview_token,
        control_token="control-a",
    )
    assert cancelled.status == "preview_cancelled"


def test_mutation_lease_remains_held_through_profile_metadata_update(monkeypatch, tmp_path: Path) -> None:
    repository, profile, storage = _setup(monkeypatch, tmp_path)

    class FakeMaintenanceHost:
        def __init__(self, selected_profile, selected_storage, mutation_id):
            _ = selected_profile, selected_storage, mutation_id

        def import_cookies(self, cookies):
            return len(cookies)

        def close(self):
            return None

    original_mark = repository.mark_bootstrap_source
    observed = {"lock_held": False}

    def mark_while_checking_lock(profile_ref, *, expected_version=None, bootstrap_source):
        with pytest.raises(ProfileLockBusyError):
            storage.acquire_mutation_lease(
                profile_ref,
                mutation_id="competing-mutation",
                operation="profile_archive",
            )
        observed["lock_held"] = True
        return original_mark(
            profile_ref,
            expected_version=expected_version,
            bootstrap_source=bootstrap_source,
        )

    repository.mark_bootstrap_source = mark_while_checking_lock  # type: ignore[method-assign]
    service = ProfileBootstrapService(
        repository=repository,
        storage=storage,
        host_factory=FakeMaintenanceHost,
    )
    preview = service.preview_cookie_import(
        profile.profile_id,
        expected_version=profile.version,
        content=_json_cookie_payload(),
        input_format="json",
        control_token="control-a",
    )

    service.commit_cookie_import(
        profile.profile_id,
        preview_token=preview.preview_token,
        expected_version=profile.version,
        control_token="control-a",
    )
    assert observed["lock_held"] is True


def test_active_profile_blocks_import_without_consuming_preview(monkeypatch, tmp_path: Path) -> None:
    repository, profile, storage = _setup(monkeypatch, tmp_path)

    class FakeMaintenanceHost:
        def __init__(self, selected_profile, selected_storage, mutation_id):
            _ = selected_profile, selected_storage, mutation_id

        def import_cookies(self, cookies):
            return len(cookies)

        def close(self):
            return None

    service = ProfileBootstrapService(
        repository=repository,
        storage=storage,
        host_factory=FakeMaintenanceHost,
    )
    preview = service.preview_cookie_import(
        profile.profile_id,
        expected_version=profile.version,
        content=_json_cookie_payload(),
        input_format="json",
        control_token="control-a",
    )
    active_lock = storage.acquire_process_lock(
        profile,
        runtime_instance_id="runtime-active",
        runtime_generation="generation-active",
        session_id="session-active",
    )
    try:
        with pytest.raises(CookieImportBusyError):
            service.commit_cookie_import(
                profile.profile_id,
                preview_token=preview.preview_token,
                expected_version=profile.version,
                control_token="control-a",
            )
    finally:
        active_lock.release()

    result = service.commit_cookie_import(
        profile.profile_id,
        preview_token=preview.preview_token,
        expected_version=profile.version,
        control_token="control-a",
    )
    assert result.status == "cookies_imported"


def test_profile_clone_preview_commit_is_control_bound_and_does_not_inherit_agent_policy(monkeypatch, tmp_path: Path) -> None:
    repository, source, storage = _setup(monkeypatch, tmp_path)
    source_paths = storage.paths_for(source)
    (source_paths.user_data_dir / "Default" / "Local Storage").mkdir(parents=True)
    (source_paths.user_data_dir / "Default" / "Local Storage" / "state.log").write_bytes(b"identity-a")
    (source_paths.user_data_dir / "Default" / "Network").mkdir(parents=True)
    (source_paths.user_data_dir / "Default" / "Network" / "Cookies").write_bytes(b"cookie-db")
    service = ProfileBootstrapService(repository=repository, storage=storage)

    preview = service.preview_profile_clone(
        source.profile_id,
        expected_source_version=source.version,
        control_token="control-a",
    )
    assert preview.file_count == 2
    assert preview.total_bytes > 0
    assert "Cookies" not in json.dumps(preview.model_dump(mode="json"))

    target_payload = BrowserProfileCreate(
        agent_alias="cloned-target",
        display_name="Cloned Target",
        owner="user_owned",
        trust_mode="guarded",
        bound_agent_ids=[],
        allowed_origins=[],
    )
    with pytest.raises(ProfileCloneBindingError):
        service.commit_profile_clone(
            source.profile_id,
            preview_token=preview.preview_token,
            expected_source_version=source.version,
            target_profile=target_payload,
            control_token="control-b",
        )

    result = service.commit_profile_clone(
        source.profile_id,
        preview_token=preview.preview_token,
        expected_source_version=source.version,
        target_profile=target_payload,
        control_token="control-a",
    )

    target = repository.get_profile(result.target_profile_id)
    target_paths = storage.paths_for(target)
    assert result.status == "profile_cloned"
    assert target.bootstrap_source == "cloned"
    assert target.bound_agent_ids == []
    assert target.allowed_origins == []
    assert target.safety_policy_id is None
    assert target.financial_policy_id is None
    assert (
        target_paths.user_data_dir / "Default" / "Network" / "Cookies"
    ).read_bytes() == b"cookie-db"
    assert (
        target_paths.user_data_dir / "Default" / "Local Storage" / "state.log"
    ).read_bytes() == b"identity-a"


def test_profile_clone_rejects_source_changes_after_preview(monkeypatch, tmp_path: Path) -> None:
    repository, source, storage = _setup(monkeypatch, tmp_path)
    source_state = storage.paths_for(source).user_data_dir / "Default" / "Network" / "Cookies"
    source_state.parent.mkdir(parents=True)
    source_state.write_bytes(b"before")
    service = ProfileBootstrapService(repository=repository, storage=storage)
    preview = service.preview_profile_clone(
        source.profile_id,
        expected_source_version=source.version,
        control_token="control-a",
    )
    source_state.write_bytes(b"after-change")

    with pytest.raises(ProfileCloneSourceChangedError):
        service.commit_profile_clone(
            source.profile_id,
            preview_token=preview.preview_token,
            expected_source_version=source.version,
            target_profile=BrowserProfileCreate(
                agent_alias="changed-target",
                display_name="Changed Target",
            ),
            control_token="control-a",
        )
    assert all(
        profile.agent_alias != "changed-target"
        for profile in repository.list_profiles(include_archived=True)
    )


def test_profile_clone_alias_conflict_cleans_storage_and_allows_retry(monkeypatch, tmp_path: Path) -> None:
    repository, source, storage = _setup(monkeypatch, tmp_path)
    source_cookie = storage.paths_for(source).user_data_dir / "Default" / "Network" / "Cookies"
    source_cookie.parent.mkdir(parents=True)
    source_cookie.write_bytes(b"cookie-db")
    repository.create_profile(
        BrowserProfileCreate(
            agent_alias="existing-alias",
            display_name="Existing",
        )
    )
    service = ProfileBootstrapService(repository=repository, storage=storage)
    preview = service.preview_profile_clone(
        source.profile_id,
        expected_source_version=source.version,
        control_token="control-a",
    )
    profiles_before = {path.name for path in storage.profiles_root.iterdir()}

    with pytest.raises(ProfileConflictError):
        service.commit_profile_clone(
            source.profile_id,
            preview_token=preview.preview_token,
            expected_source_version=source.version,
            target_profile=BrowserProfileCreate(
                agent_alias="existing-alias",
                display_name="Conflict",
            ),
            control_token="control-a",
        )
    profiles_after_failure = {path.name for path in storage.profiles_root.iterdir()}
    assert profiles_after_failure == profiles_before

    result = service.commit_profile_clone(
        source.profile_id,
        preview_token=preview.preview_token,
        expected_source_version=source.version,
        target_profile=BrowserProfileCreate(
            agent_alias="retry-target",
            display_name="Retry Target",
        ),
        control_token="control-a",
    )
    assert repository.get_profile(result.target_profile_id).agent_alias == "retry-target"


def test_active_source_profile_blocks_clone_preview(monkeypatch, tmp_path: Path) -> None:
    repository, source, storage = _setup(monkeypatch, tmp_path)
    service = ProfileBootstrapService(repository=repository, storage=storage)
    active_lock = storage.acquire_process_lock(
        source,
        runtime_instance_id="runtime-active",
        runtime_generation="generation-active",
        session_id="session-active",
    )
    try:
        with pytest.raises(ProfileCloneBusyError):
            service.preview_profile_clone(
                source.profile_id,
                expected_source_version=source.version,
                control_token="control-a",
            )
    finally:
        active_lock.release()
