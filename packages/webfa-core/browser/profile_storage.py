from __future__ import annotations

import json
import os
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from schemas.profile import BrowserProfile
from storage.file_store import ensure_webfa_data_dir


class ProfileStorageError(RuntimeError):
    code = "profile_storage_error"


class ProfileLockBusyError(ProfileStorageError):
    code = "profile_busy"


class ProfileStorageConflictError(ProfileStorageError):
    code = "profile_storage_conflict"


@dataclass(frozen=True)
class ProfileStoragePaths:
    profile_root: Path
    user_data_dir: Path
    downloads_dir: Path
    maintenance_dir: Path
    lock_file: Path


@dataclass(frozen=True)
class ProfileLaunchSpec:
    profile_id: str
    user_data_dir: Path
    downloads_dir: Path
    headless: bool
    runtime_instance_id: str
    runtime_generation: str
    network_policy: str | None = None


@dataclass(frozen=True)
class DefaultProfileMigrationResult:
    status: str
    source: Path | None = None
    target: Path | None = None


class ProfileProcessLock:
    """Cross-process exclusive lock held for the lifetime of one active Profile host."""

    def __init__(self, path: Path, metadata: dict[str, Any]) -> None:
        self.path = path
        self.metadata = _safe_lock_metadata(metadata)
        self._handle = None
        self._owner_thread: int | None = None
        self._released = False

    @property
    def acquired(self) -> bool:
        return self._handle is not None and not self._released

    def acquire(self) -> "ProfileProcessLock":
        if self.acquired:
            return self
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            _lock_file_handle(handle)
            handle.seek(1)
            handle.truncate()
            handle.write(json.dumps(self.metadata, sort_keys=True).encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        except OSError as exc:
            handle.close()
            raise ProfileLockBusyError("browser profile is already active in another runtime") from exc
        self._handle = handle
        self._owner_thread = threading.get_ident()
        self._released = False
        return self

    def release(self) -> None:
        handle = self._handle
        if handle is None or self._released:
            return
        try:
            handle.seek(0)
            _unlock_file_handle(handle)
        finally:
            handle.close()
            self._handle = None
            self._released = True

    def __enter__(self) -> "ProfileProcessLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


@dataclass
class ProfileMutationLease:
    """Exclusive maintenance lease sharing the Profile's process lock.

    A mutation lease cannot coexist with a normal BrowserSession host or another
    maintenance operation. It contains only safe identifiers and never carries
    imported browser data.
    """

    profile_id: str
    mutation_id: str
    operation: str
    process_lock: ProfileProcessLock

    @property
    def acquired(self) -> bool:
        return self.process_lock.acquired

    def release(self) -> None:
        self.process_lock.release()

    def __enter__(self) -> "ProfileMutationLease":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


class ProfileStorageManager:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = (data_dir or ensure_webfa_data_dir()["data_dir"]).resolve()
        self.profiles_root = self.data_dir / "profiles"
        self.profiles_root.mkdir(parents=True, exist_ok=True)

    def paths_for(self, profile: BrowserProfile | str, *, create: bool = True) -> ProfileStoragePaths:
        profile_id = profile.profile_id if isinstance(profile, BrowserProfile) else profile
        _validate_profile_id(profile_id)
        profile_root = self.profiles_root / profile_id
        paths = ProfileStoragePaths(
            profile_root=profile_root,
            user_data_dir=profile_root / "chromium-user-data",
            downloads_dir=profile_root / "downloads",
            maintenance_dir=profile_root / "maintenance",
            lock_file=profile_root / "profile.lock",
        )
        if create:
            paths.user_data_dir.mkdir(parents=True, exist_ok=True)
            paths.downloads_dir.mkdir(parents=True, exist_ok=True)
            paths.maintenance_dir.mkdir(parents=True, exist_ok=True)
        return paths

    def launch_spec(
        self,
        profile: BrowserProfile,
        *,
        headless: bool,
        runtime_instance_id: str,
        runtime_generation: str,
    ) -> ProfileLaunchSpec:
        if profile.persistence != "persistent":
            raise ProfileStorageError("ephemeral Profile hosts are not implemented in P12 Core")
        if profile.catalog_state != "ready":
            raise ProfileStorageError(
                f"profile in state '{profile.catalog_state}' cannot launch a browser host"
            )
        paths = self.paths_for(profile)
        return ProfileLaunchSpec(
            profile_id=profile.profile_id,
            user_data_dir=paths.user_data_dir,
            downloads_dir=paths.downloads_dir,
            headless=headless,
            runtime_instance_id=runtime_instance_id,
            runtime_generation=runtime_generation,
        )

    def acquire_process_lock(
        self,
        profile: BrowserProfile | str,
        *,
        runtime_instance_id: str,
        runtime_generation: str,
        session_id: str,
    ) -> ProfileProcessLock:
        profile_id = profile.profile_id if isinstance(profile, BrowserProfile) else profile
        paths = self.paths_for(profile_id)
        return ProfileProcessLock(
            paths.lock_file,
            {
                "profile_id": profile_id,
                "runtime_instance_id": runtime_instance_id,
                "runtime_generation": runtime_generation,
                "session_id": session_id,
                "pid": os.getpid(),
            },
        ).acquire()

    def acquire_mutation_lease(
        self,
        profile: BrowserProfile | str,
        *,
        mutation_id: str,
        operation: str,
    ) -> ProfileMutationLease:
        profile_id = profile.profile_id if isinstance(profile, BrowserProfile) else profile
        if not mutation_id.strip():
            raise ProfileStorageError("mutation_id is required")
        if not operation.strip():
            raise ProfileStorageError("mutation operation is required")
        process_lock = self.acquire_process_lock(
            profile_id,
            runtime_instance_id=f"maintenance:{mutation_id}",
            runtime_generation=f"maintenance:{mutation_id}",
            session_id=f"maintenance:{operation}",
        )
        return ProfileMutationLease(
            profile_id=profile_id,
            mutation_id=mutation_id,
            operation=operation,
            process_lock=process_lock,
        )

    def migrate_legacy_default_profile(self) -> DefaultProfileMigrationResult:
        source = self.data_dir / "browser" / "managed-chromium-profile-default"
        target = self.paths_for("default", create=False).user_data_dir
        if not source.exists():
            existed = target.exists() and any(target.iterdir())
            self.paths_for("default", create=True)
            return DefaultProfileMigrationResult(
                status="already_migrated" if existed else "not_found",
                source=source,
                target=target,
            )
        if source.resolve() == target.resolve():
            return DefaultProfileMigrationResult(status="already_migrated", source=source, target=target)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if any(target.iterdir()):
                raise ProfileStorageConflictError(
                    "legacy default Profile and P12 default Profile both contain data"
                )
            target.rmdir()
        shutil.move(str(source), str(target))
        self.paths_for("default", create=True)
        legacy_parent = source.parent
        try:
            legacy_parent.rmdir()
        except OSError:
            pass
        return DefaultProfileMigrationResult(status="migrated", source=source, target=target)


def _safe_lock_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "profile_id",
        "runtime_instance_id",
        "runtime_generation",
        "session_id",
        "pid",
    }
    return {key: value for key, value in metadata.items() if key in allowed}


def _validate_profile_id(profile_id: str) -> None:
    if not profile_id or len(profile_id) > 200:
        raise ProfileStorageError("invalid profile id")
    if profile_id in {".", ".."} or any(char in profile_id for char in ("/", "\\", "\0")):
        raise ProfileStorageError("invalid profile id")


def _lock_file_handle(handle) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file_handle(handle) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
