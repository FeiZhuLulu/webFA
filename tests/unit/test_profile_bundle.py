from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from browser.profile_bundle import (
    BUNDLE_MANIFEST_NAME,
    BUNDLE_PROFILE_PREFIX,
    ProfileBundleBusyError,
    ProfileBundleFormatError,
    ProfileBundleIntegrityError,
    ProfileBundlePassphraseError,
    ProfileBundleService,
    ProfileBundleSourceChangedError,
    _decrypt_bundle_file,
    _encrypt_bundle_file,
)
from browser.profile_repository import ProfileConflictError, ProfileRepository
from browser.profile_storage import ProfileStorageManager
from pydantic import ValidationError

from schemas.profile import BrowserProfileCreate
from schemas.profile_bootstrap import ProfileBundleRestoreCommitRequest
from storage.db import init_db, reset_engine_for_tests


PASSPHRASE = "correct horse battery staple"


def _setup(monkeypatch, tmp_path: Path):
    home = tmp_path / "WebFA"
    monkeypatch.setenv("WEBFA_HOME", str(home))
    reset_engine_for_tests()
    init_db()
    repository = ProfileRepository()
    source = repository.create_profile(
        BrowserProfileCreate(
            agent_alias="bundle-source",
            display_name="Bundle Source",
            bound_agent_ids=["agent-source"],
            allowed_origins=["https://source.example"],
            safety_policy_id="safety-source",
            financial_policy_id="finance-source",
        )
    )
    storage = ProfileStorageManager(home)
    return repository, source, storage


def _seed_source(storage: ProfileStorageManager, source) -> None:
    paths = storage.paths_for(source)
    (paths.user_data_dir / "Default" / "Local Storage").mkdir(parents=True)
    (paths.user_data_dir / "Default" / "Local Storage" / "state.log").write_bytes(
        b"bundle-local-state"
    )
    (paths.user_data_dir / "Default" / "Network").mkdir(parents=True)
    (paths.user_data_dir / "Default" / "Network" / "Cookies").write_bytes(
        b"bundle-cookie-db"
    )
    (paths.user_data_dir / "DevToolsActivePort").write_text("9222", encoding="utf-8")


def test_streaming_encryption_roundtrip_wrong_passphrase_and_tamper(tmp_path: Path) -> None:
    plaintext = tmp_path / "plain.zip"
    encrypted = tmp_path / "bundle.webfa-profile"
    restored = tmp_path / "restored.zip"
    plaintext.write_bytes(b"plain-profile-bundle-payload" * 4096)

    _encrypt_bundle_file(
        plaintext,
        encrypted,
        passphrase=PASSPHRASE,
        created_at=datetime.now(timezone.utc),
    )
    _decrypt_bundle_file(encrypted, restored, passphrase=PASSPHRASE)
    assert restored.read_bytes() == plaintext.read_bytes()

    wrong_output = tmp_path / "wrong.zip"
    with pytest.raises(ProfileBundlePassphraseError):
        _decrypt_bundle_file(encrypted, wrong_output, passphrase="this is the wrong passphrase")
    assert not wrong_output.exists()

    payload = bytearray(encrypted.read_bytes())
    payload[len(payload) // 2] ^= 0x01
    tampered = tmp_path / "tampered.webfa-profile"
    tampered.write_bytes(payload)
    tampered_output = tmp_path / "tampered.zip"
    with pytest.raises(ProfileBundlePassphraseError):
        _decrypt_bundle_file(tampered, tampered_output, passphrase=PASSPHRASE)
    assert not tampered_output.exists()


def test_export_restore_roundtrip_is_redacted_and_drops_policy_bindings(monkeypatch, tmp_path: Path) -> None:
    repository, source, storage = _setup(monkeypatch, tmp_path)
    _seed_source(storage, source)
    service = ProfileBundleService(
        repository=repository,
        storage=storage,
        temp_root=tmp_path / "bundle-temp",
    )
    try:
        export_preview = service.preview_export(
            source.profile_id,
            expected_source_version=source.version,
            control_token="control-a",
        )
        serialized_preview = json.dumps(export_preview.model_dump(mode="json"))
        assert "Cookies" not in serialized_preview
        assert "state.log" not in serialized_preview
        assert export_preview.file_count == 2
        assert export_preview.excluded_count == 1

        artifact = service.export_bundle(
            source.profile_id,
            preview_token=export_preview.preview_token,
            expected_source_version=source.version,
            passphrase=PASSPHRASE,
            control_token="control-a",
        )
        assert artifact.path.is_file()
        assert artifact.path.read_bytes()[:8] == b"WEBFAPB1"
        assert b"bundle-cookie-db" not in artifact.path.read_bytes()

        restore_preview = service.preview_restore(
            artifact.path,
            passphrase=PASSPHRASE,
            control_token="control-a",
        )
        serialized_restore = json.dumps(restore_preview.model_dump(mode="json"))
        assert "Cookies" not in serialized_restore
        assert "bundle-cookie-db" not in serialized_restore
        assert restore_preview.source_agent_alias == source.agent_alias
        assert restore_preview.source_platform
        assert restore_preview.current_platform
        assert restore_preview.restoration_scope == "browser_storage_only"
        assert "not guaranteed" in restore_preview.compatibility_warning.lower()
        assert restore_preview.file_count == 2

        result = service.restore_bundle(
            preview_token=restore_preview.preview_token,
            passphrase=PASSPHRASE,
            target_profile=BrowserProfileCreate(
                agent_alias="bundle-restored",
                display_name="Bundle Restored",
            ),
            control_token="control-a",
        )
        target = repository.get_profile(result.target_profile_id)
        target_paths = storage.paths_for(target)
        assert result.status == "profile_restored"
        assert target.bootstrap_source == "restored"
        assert target.bound_agent_ids == []
        assert target.allowed_origins == []
        assert target.safety_policy_id is None
        assert target.financial_policy_id is None
        assert (
            target_paths.user_data_dir / "Default" / "Network" / "Cookies"
        ).read_bytes() == b"bundle-cookie-db"
        assert (
            target_paths.user_data_dir / "Default" / "Local Storage" / "state.log"
        ).read_bytes() == b"bundle-local-state"
        assert not (target_paths.user_data_dir / "DevToolsActivePort").exists()
        assert not artifact.path.exists()
    finally:
        service.close()


def test_restore_does_not_retain_passphrase_and_requires_it_again_on_commit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repository, source, storage = _setup(monkeypatch, tmp_path)
    _seed_source(storage, source)
    service = ProfileBundleService(
        repository=repository,
        storage=storage,
        temp_root=tmp_path / "bundle-temp",
    )
    try:
        export_preview = service.preview_export(
            source.profile_id,
            expected_source_version=source.version,
            control_token="control-a",
        )
        artifact = service.export_bundle(
            source.profile_id,
            preview_token=export_preview.preview_token,
            expected_source_version=source.version,
            passphrase=PASSPHRASE,
            control_token="control-a",
        )
        restore_preview = service.preview_restore(
            artifact.path,
            passphrase=PASSPHRASE,
            control_token="control-a",
        )
        pending = service._restores[restore_preview.preview_token]
        assert "passphrase" not in vars(pending)

        with pytest.raises(ProfileBundlePassphraseError):
            service.restore_bundle(
                preview_token=restore_preview.preview_token,
                passphrase="this is the wrong passphrase",
                target_profile=BrowserProfileCreate(
                    agent_alias="wrong-passphrase",
                    display_name="Wrong Passphrase",
                ),
                control_token="control-a",
            )

        result = service.restore_bundle(
            preview_token=restore_preview.preview_token,
            passphrase=PASSPHRASE,
            target_profile=BrowserProfileCreate(
                agent_alias="correct-passphrase",
                display_name="Correct Passphrase",
            ),
            control_token="control-a",
        )
        assert repository.get_profile(result.target_profile_id).agent_alias == "correct-passphrase"
    finally:
        service.close()


def test_export_rejects_source_change_after_preview(monkeypatch, tmp_path: Path) -> None:
    repository, source, storage = _setup(monkeypatch, tmp_path)
    _seed_source(storage, source)
    service = ProfileBundleService(
        repository=repository,
        storage=storage,
        temp_root=tmp_path / "bundle-temp",
    )
    try:
        preview = service.preview_export(
            source.profile_id,
            expected_source_version=source.version,
            control_token="control-a",
        )
        (
            storage.paths_for(source).user_data_dir / "Default" / "Network" / "Cookies"
        ).write_bytes(b"changed")

        with pytest.raises(ProfileBundleSourceChangedError):
            service.export_bundle(
                source.profile_id,
                preview_token=preview.preview_token,
                expected_source_version=source.version,
                passphrase=PASSPHRASE,
                control_token="control-a",
            )
    finally:
        service.close()


def test_bundle_service_startup_and_close_purge_all_orphaned_temp_files(tmp_path: Path) -> None:
    temp_root = tmp_path / "bundle-temp"
    nested = temp_root / "orphaned-directory"
    nested.mkdir(parents=True)
    (temp_root / "plain-stale.zip").write_bytes(b"plaintext identity archive")
    (temp_root / "upload-stale.bundle").write_bytes(b"encrypted upload")
    (nested / "restore-stale.zip").write_bytes(b"decrypted restore archive")

    service = ProfileBundleService(temp_root=temp_root)
    assert list(temp_root.iterdir()) == []

    (temp_root / "created-after-start.zip").write_bytes(b"temporary")
    service.close()
    assert list(temp_root.iterdir()) == []


def test_bundle_service_temp_store_is_cross_process_exclusive(tmp_path: Path) -> None:
    temp_root = tmp_path / "bundle-temp"
    first = ProfileBundleService(temp_root=temp_root)
    try:
        with pytest.raises(ProfileBundleBusyError, match="another Runtime"):
            ProfileBundleService(temp_root=temp_root)
    finally:
        first.close()

    replacement = ProfileBundleService(temp_root=temp_root)
    sentinel = temp_root / "replacement-active.tmp"
    sentinel.write_bytes(b"active")
    first.close()
    assert sentinel.exists()
    replacement.close()


def test_restore_rejects_path_traversal_even_inside_authenticated_bundle(tmp_path: Path) -> None:
    plain = tmp_path / "malicious.zip"
    encrypted = tmp_path / "bundle-temp" / "upload-malicious.bundle"
    encrypted.parent.mkdir(parents=True)
    member = f"{BUNDLE_PROFILE_PREFIX}../../outside.txt"
    content = b"malicious"
    manifest = {
        "format": "webfa-profile-bundle",
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_agent_alias": "malicious-source",
        "source_display_name": "Malicious Source",
        "source_bootstrap_source": "blank",
        "file_count": 1,
        "total_bytes": len(content),
        "excluded_count": 0,
        "entries": [
            {
                "path": member,
                "size": len(content),
                "sha256": __import__("hashlib").sha256(content).hexdigest(),
            }
        ],
    }
    with zipfile.ZipFile(plain, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(BUNDLE_MANIFEST_NAME, json.dumps(manifest))
        archive.writestr(member, content)
    service = ProfileBundleService(temp_root=encrypted.parent)
    _encrypt_bundle_file(
        plain,
        encrypted,
        passphrase=PASSPHRASE,
        created_at=datetime.now(timezone.utc),
    )

    try:
        with pytest.raises(ProfileBundleFormatError):
            service.preview_restore(
                encrypted,
                passphrase=PASSPHRASE,
                control_token="control-a",
            )
        assert not encrypted.exists()
        assert not (tmp_path / "outside.txt").exists()
    finally:
        service.close()


def test_restore_rejects_compressed_archive_members(tmp_path: Path) -> None:
    plain = tmp_path / "compressed.zip"
    encrypted = tmp_path / "bundle-temp" / "upload-compressed.bundle"
    encrypted.parent.mkdir(parents=True)
    member = f"{BUNDLE_PROFILE_PREFIX}Cookies"
    content = b"compressed-content" * 100
    manifest = {
        "format": "webfa-profile-bundle",
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_agent_alias": "compressed-source",
        "source_display_name": "Compressed Source",
        "source_bootstrap_source": "blank",
        "file_count": 1,
        "total_bytes": len(content),
        "excluded_count": 0,
        "entries": [
            {
                "path": member,
                "size": len(content),
                "sha256": __import__("hashlib").sha256(content).hexdigest(),
            }
        ],
    }
    with zipfile.ZipFile(plain, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(BUNDLE_MANIFEST_NAME, json.dumps(manifest), compress_type=zipfile.ZIP_STORED)
        archive.writestr(member, content, compress_type=zipfile.ZIP_DEFLATED)
    service = ProfileBundleService(temp_root=encrypted.parent)
    _encrypt_bundle_file(
        plain,
        encrypted,
        passphrase=PASSPHRASE,
        created_at=datetime.now(timezone.utc),
    )

    try:
        with pytest.raises(ProfileBundleFormatError, match="stored ZIP method"):
            service.preview_restore(
                encrypted,
                passphrase=PASSPHRASE,
                control_token="control-a",
            )
    finally:
        service.close()


@pytest.mark.parametrize(
    "member",
    [
        f"{BUNDLE_PROFILE_PREFIX}Default/History",
        f"{BUNDLE_PROFILE_PREFIX}Profile 1/Network/Cookies",
    ],
)
def test_restore_rejects_browser_data_outside_identity_transfer_scope(
    tmp_path: Path,
    member: str,
) -> None:
    plain = tmp_path / "excluded-data.zip"
    encrypted = tmp_path / "bundle-temp" / "upload-excluded-data.bundle"
    encrypted.parent.mkdir(parents=True)
    content = b"human-browsing-history"
    manifest = {
        "format": "webfa-profile-bundle",
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_agent_alias": "history-source",
        "source_display_name": "History Source",
        "source_bootstrap_source": "blank",
        "file_count": 1,
        "total_bytes": len(content),
        "excluded_count": 0,
        "entries": [
            {
                "path": member,
                "size": len(content),
                "sha256": __import__("hashlib").sha256(content).hexdigest(),
            }
        ],
    }
    with zipfile.ZipFile(plain, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(BUNDLE_MANIFEST_NAME, json.dumps(manifest))
        archive.writestr(member, content)
    service = ProfileBundleService(temp_root=encrypted.parent)
    _encrypt_bundle_file(
        plain,
        encrypted,
        passphrase=PASSPHRASE,
        created_at=datetime.now(timezone.utc),
    )

    try:
        with pytest.raises(ProfileBundleFormatError, match="identity-transfer scope"):
            service.preview_restore(
                encrypted,
                passphrase=PASSPHRASE,
                control_token="control-a",
            )
    finally:
        service.close()


def test_restore_request_rejects_authority_and_policy_fields() -> None:
    with pytest.raises(ValidationError):
        ProfileBundleRestoreCommitRequest.model_validate(
            {
                "preview_token": "preview-token",
                "target_profile": {
                    "agent_alias": "restored-target",
                    "display_name": "Restored Target",
                    "bound_agent_ids": ["agent-a"],
                    "safety_policy_id": "policy-a",
                },
            }
        )


def test_restore_alias_conflict_cleans_storage_and_allows_retry(monkeypatch, tmp_path: Path) -> None:
    repository, source, storage = _setup(monkeypatch, tmp_path)
    _seed_source(storage, source)
    repository.create_profile(
        BrowserProfileCreate(
            agent_alias="existing-bundle-alias",
            display_name="Existing Bundle Alias",
        )
    )
    service = ProfileBundleService(
        repository=repository,
        storage=storage,
        temp_root=tmp_path / "bundle-temp",
    )
    try:
        export_preview = service.preview_export(
            source.profile_id,
            expected_source_version=source.version,
            control_token="control-a",
        )
        artifact = service.export_bundle(
            source.profile_id,
            preview_token=export_preview.preview_token,
            expected_source_version=source.version,
            passphrase=PASSPHRASE,
            control_token="control-a",
        )
        restore_preview = service.preview_restore(
            artifact.path,
            passphrase=PASSPHRASE,
            control_token="control-a",
        )
        profiles_before = {path.name for path in storage.profiles_root.iterdir()}

        with pytest.raises(ProfileConflictError):
            service.restore_bundle(
                preview_token=restore_preview.preview_token,
                passphrase=PASSPHRASE,
                target_profile=BrowserProfileCreate(
                    agent_alias="existing-bundle-alias",
                    display_name="Conflict",
                ),
                control_token="control-a",
            )
        profiles_after = {path.name for path in storage.profiles_root.iterdir()}
        assert profiles_after == profiles_before

        result = service.restore_bundle(
            preview_token=restore_preview.preview_token,
            passphrase=PASSPHRASE,
            target_profile=BrowserProfileCreate(
                agent_alias="bundle-retry",
                display_name="Bundle Retry",
            ),
            control_token="control-a",
        )
        assert repository.get_profile(result.target_profile_id).agent_alias == "bundle-retry"
    finally:
        service.close()
