from __future__ import annotations

from pathlib import Path

import pytest

from browser.profile_storage import (
    ProfileLockBusyError,
    ProfileStorageConflictError,
    ProfileStorageManager,
    ProfileStorageUnsafeError,
)


def test_profile_storage_paths_are_isolated(tmp_path: Path):
    manager = ProfileStorageManager(tmp_path / "WebFA")

    profile_a = manager.paths_for("profile_a")
    profile_b = manager.paths_for("profile_b")

    assert profile_a.user_data_dir != profile_b.user_data_dir
    assert profile_a.user_data_dir.is_dir()
    assert profile_b.downloads_dir.is_dir()
    assert profile_a.profile_root.parent == manager.profiles_root


def test_profile_process_lock_is_cross_handle_exclusive(tmp_path: Path):
    manager = ProfileStorageManager(tmp_path / "WebFA")
    first = manager.acquire_process_lock(
        "profile_a",
        runtime_instance_id="runtime_a",
        runtime_generation="generation_a",
        session_id="session_a",
    )
    try:
        with pytest.raises(ProfileLockBusyError):
            manager.acquire_process_lock(
                "profile_a",
                runtime_instance_id="runtime_b",
                runtime_generation="generation_b",
                session_id="session_b",
            )
    finally:
        first.release()

    second = manager.acquire_process_lock(
        "profile_a",
        runtime_instance_id="runtime_b",
        runtime_generation="generation_b",
        session_id="session_b",
    )
    second.release()


def test_profile_clone_storage_excludes_runtime_artifacts_and_matches_snapshot(tmp_path: Path):
    manager = ProfileStorageManager(tmp_path / "WebFA")
    source = manager.paths_for("profile_source")
    (source.user_data_dir / "Default" / "Local Storage").mkdir(parents=True)
    (source.user_data_dir / "Default" / "Local Storage" / "leveldb.log").write_bytes(b"local-state")
    (source.user_data_dir / "Cookies").write_bytes(b"cookie-state")
    (source.user_data_dir / "DevToolsActivePort").write_text("9222", encoding="utf-8")
    (source.user_data_dir / "SingletonLock").write_text("stale", encoding="utf-8")
    (source.user_data_dir / "ShaderCache").mkdir()
    (source.user_data_dir / "ShaderCache" / "cache.bin").write_bytes(b"cache")

    source_lock = manager.acquire_mutation_lease(
        "profile_source",
        mutation_id="clone-test",
        operation="profile_clone_source",
    )
    target_lock = manager.acquire_mutation_lease(
        "profile_target",
        mutation_id="clone-test",
        operation="profile_clone_target",
    )
    try:
        snapshot = manager.inspect_clone_source("profile_source")
        copied = manager.clone_profile_storage(
            "profile_source",
            "profile_target",
            mutation_id="clone-test",
            expected_fingerprint=snapshot.fingerprint,
        )
    finally:
        target_lock.release()
        source_lock.release()

    target = manager.paths_for("profile_target").user_data_dir
    assert copied.file_count == 2
    assert copied.excluded_count == 3
    assert (target / "Cookies").read_bytes() == b"cookie-state"
    assert (target / "Default" / "Local Storage" / "leveldb.log").read_bytes() == b"local-state"
    assert not (target / "DevToolsActivePort").exists()
    assert not (target / "SingletonLock").exists()
    assert not (target / "ShaderCache").exists()


def test_profile_clone_rejects_changed_source_snapshot(tmp_path: Path):
    manager = ProfileStorageManager(tmp_path / "WebFA")
    source = manager.paths_for("profile_source")
    state = source.user_data_dir / "Cookies"
    state.write_bytes(b"before")
    snapshot = manager.inspect_clone_source("profile_source")
    state.write_bytes(b"after-change")

    with pytest.raises(ProfileStorageConflictError, match="changed"):
        manager.clone_profile_storage(
            "profile_source",
            "profile_target",
            mutation_id="clone-change",
            expected_fingerprint=snapshot.fingerprint,
        )


def test_profile_clone_rejects_symbolic_links(tmp_path: Path):
    manager = ProfileStorageManager(tmp_path / "WebFA")
    source = manager.paths_for("profile_source")
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("secret", encoding="utf-8")
    link = source.user_data_dir / "linked-secret.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symbolic links are unavailable in this test environment")

    with pytest.raises(ProfileStorageUnsafeError):
        manager.inspect_clone_source("profile_source")


def test_legacy_default_profile_migrates_idempotently(tmp_path: Path):
    data_dir = tmp_path / "WebFA"
    legacy = data_dir / "browser" / "managed-chromium-profile-default"
    legacy.mkdir(parents=True)
    (legacy / "Cookies").write_text("legacy-state", encoding="utf-8")
    manager = ProfileStorageManager(data_dir)

    migrated = manager.migrate_legacy_default_profile()

    target = manager.paths_for("default").user_data_dir
    assert migrated.status == "migrated"
    assert (target / "Cookies").read_text(encoding="utf-8") == "legacy-state"
    assert not legacy.exists()

    repeated = manager.migrate_legacy_default_profile()
    assert repeated.status == "already_migrated"
    assert (target / "Cookies").exists()
