from __future__ import annotations

import os
from pathlib import Path

import pytest

import browser.profile_storage as profile_storage_module
from browser.profile_storage import (
    ProfileLockBusyError,
    ProfileStorageConflictError,
    ProfileStorageError,
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


@pytest.mark.parametrize(
    "profile_id",
    ("", ".", "..", "../outside", "..\\outside", "C:outside", "bad/profile"),
)
def test_profile_storage_rejects_non_local_profile_ids(tmp_path: Path, profile_id: str):
    manager = ProfileStorageManager(tmp_path / "WebFA")
    with pytest.raises(ProfileStorageError, match="invalid profile id"):
        manager.paths_for(profile_id)


def test_profile_storage_rejects_profile_root_link_or_junction(monkeypatch, tmp_path: Path):
    manager = ProfileStorageManager(tmp_path / "WebFA")
    unsafe_root = manager.profiles_root / "profile_unsafe"
    original = profile_storage_module._path_is_unsafe_link
    monkeypatch.setattr(
        profile_storage_module,
        "_path_is_unsafe_link",
        lambda path: path == unsafe_root or original(path),
    )

    with pytest.raises(ProfileStorageUnsafeError, match="symbolic link or directory junction"):
        manager.paths_for("profile_unsafe")
    assert not unsafe_root.exists()


def test_profile_storage_rejects_managed_child_link_without_creating_paths(monkeypatch, tmp_path: Path):
    manager = ProfileStorageManager(tmp_path / "WebFA")
    unsafe_child = manager.profiles_root / "profile_unsafe_child" / "chromium-user-data"
    original = profile_storage_module._path_is_unsafe_link
    monkeypatch.setattr(
        profile_storage_module,
        "_path_is_unsafe_link",
        lambda path: path == unsafe_child or original(path),
    )

    with pytest.raises(ProfileStorageUnsafeError, match="symbolic link or directory junction"):
        manager.paths_for("profile_unsafe_child", create=False)
    assert not unsafe_child.parent.exists()


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
    (source.user_data_dir / "Default" / "Network").mkdir(parents=True)
    (source.user_data_dir / "Default" / "Network" / "Cookies").write_bytes(b"cookie-state")
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
    assert (target / "Default" / "Network" / "Cookies").read_bytes() == b"cookie-state"
    assert (target / "Default" / "Local Storage" / "leveldb.log").read_bytes() == b"local-state"
    assert not (target / "DevToolsActivePort").exists()
    assert not (target / "SingletonLock").exists()
    assert not (target / "ShaderCache").exists()


def test_profile_transfer_excludes_human_browser_history_vault_and_extensions(tmp_path: Path):
    manager = ProfileStorageManager(tmp_path / "WebFA")
    source = manager.paths_for("profile_source")
    default = source.user_data_dir / "Default"
    (default / "Network").mkdir(parents=True)
    (default / "Network" / "Cookies").write_bytes(b"site-cookie-state")
    (default / "Local Storage").mkdir(parents=True)
    (default / "Local Storage" / "state.log").write_bytes(b"site-storage")

    excluded_files = {
        default / "History": b"browsing-history",
        default / "Bookmarks": b"human-bookmarks",
        default / "Login Data": b"password-vault",
        default / "Web Data": b"autofill-and-payment-data",
        default / "Secure Preferences": b"extension-policy-state",
        default / "Network" / "TransportSecurity": b"transport-policy",
    }
    for path, payload in excluded_files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    (default / "Extensions" / "malicious-extension").mkdir(parents=True)
    (default / "Extensions" / "malicious-extension" / "manifest.json").write_text(
        "{}",
        encoding="utf-8",
    )
    (source.user_data_dir / "Profile 1" / "Network").mkdir(parents=True)
    (source.user_data_dir / "Profile 1" / "Network" / "Cookies").write_bytes(
        b"second-chromium-profile"
    )
    (default / "Sessions").mkdir()
    (default / "Sessions" / "Tabs_1").write_bytes(b"open-human-tabs")

    snapshot = manager.inspect_clone_source("profile_source")
    source_lock = manager.acquire_mutation_lease(
        "profile_source",
        mutation_id="identity-transfer-test",
        operation="profile_clone_source",
    )
    target_lock = manager.acquire_mutation_lease(
        "profile_target",
        mutation_id="identity-transfer-test",
        operation="profile_clone_target",
    )
    try:
        manager.clone_profile_storage(
            "profile_source",
            "profile_target",
            mutation_id="identity-transfer-test",
            expected_fingerprint=snapshot.fingerprint,
        )
    finally:
        target_lock.release()
        source_lock.release()

    target = manager.paths_for("profile_target").user_data_dir
    assert (target / "Default" / "Network" / "Cookies").read_bytes() == b"site-cookie-state"
    assert (target / "Default" / "Local Storage" / "state.log").read_bytes() == b"site-storage"
    for path in excluded_files:
        relative = path.relative_to(source.user_data_dir)
        assert not (target / relative).exists()
    assert not (target / "Default" / "Extensions").exists()
    assert not (target / "Default" / "Sessions").exists()
    assert not (target / "Profile 1").exists()
    assert snapshot.excluded_count >= len(excluded_files) + 3


def test_profile_clone_rejects_changed_source_snapshot(tmp_path: Path):
    manager = ProfileStorageManager(tmp_path / "WebFA")
    source = manager.paths_for("profile_source")
    state = source.user_data_dir / "Default" / "Network" / "Cookies"
    state.parent.mkdir(parents=True)
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


def test_profile_clone_detects_same_size_change_with_restored_mtime(tmp_path: Path):
    manager = ProfileStorageManager(tmp_path / "WebFA")
    source = manager.paths_for("profile_source")
    state = source.user_data_dir / "Default" / "Network" / "Cookies"
    state.parent.mkdir(parents=True)
    state.write_bytes(b"before")
    original = state.stat()
    snapshot = manager.inspect_clone_source("profile_source")

    state.write_bytes(b"after!")
    os.utime(state, ns=(original.st_atime_ns, original.st_mtime_ns))

    with pytest.raises(ProfileStorageConflictError, match="changed"):
        manager.clone_profile_storage(
            "profile_source",
            "profile_target",
            mutation_id="clone-content-change",
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
