from __future__ import annotations

from pathlib import Path

import pytest

from browser.profile_storage import (
    ProfileLockBusyError,
    ProfileStorageManager,
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
