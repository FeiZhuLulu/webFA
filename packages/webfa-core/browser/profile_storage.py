from __future__ import annotations

import hashlib
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


class ProfileStorageUnsafeError(ProfileStorageError):
    code = "profile_storage_unsafe"


@dataclass(frozen=True)
class ProfileCloneStorageSnapshot:
    file_count: int
    total_bytes: int
    excluded_count: int
    fingerprint: str


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
        _reject_unsafe_managed_directory(self.profiles_root)
        self.profiles_root.mkdir(parents=True, exist_ok=True)
        _reject_unsafe_managed_directory(self.profiles_root)

    def paths_for(self, profile: BrowserProfile | str, *, create: bool = True) -> ProfileStoragePaths:
        profile_id = profile.profile_id if isinstance(profile, BrowserProfile) else profile
        _validate_profile_id(profile_id)
        profile_root = self.profiles_root / profile_id
        _reject_unsafe_managed_directory(profile_root)
        paths = ProfileStoragePaths(
            profile_root=profile_root,
            user_data_dir=profile_root / "chromium-user-data",
            downloads_dir=profile_root / "downloads",
            maintenance_dir=profile_root / "maintenance",
            lock_file=profile_root / "profile.lock",
        )
        managed_directories = (
            paths.user_data_dir,
            paths.downloads_dir,
            paths.maintenance_dir,
        )
        for directory in managed_directories:
            _reject_unsafe_managed_directory(directory)
        if create:
            profile_root.mkdir(parents=True, exist_ok=True)
            _reject_unsafe_managed_directory(profile_root)
            for directory in managed_directories:
                directory.mkdir(parents=False, exist_ok=True)
                _reject_unsafe_managed_directory(directory)
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

    def inspect_clone_source(
        self,
        profile: BrowserProfile | str,
    ) -> ProfileCloneStorageSnapshot:
        paths = self.paths_for(profile)
        return _snapshot_clone_storage(paths.user_data_dir)

    def iter_clone_files(
        self,
        profile: BrowserProfile | str,
    ):
        paths = self.paths_for(profile)
        for relative, path, is_directory, excluded in _walk_clone_storage(
            paths.user_data_dir
        ):
            if not excluded and not is_directory:
                yield relative, path

    def clone_profile_storage(
        self,
        source: BrowserProfile | str,
        target_profile_id: str,
        *,
        mutation_id: str,
        expected_fingerprint: str,
    ) -> ProfileCloneStorageSnapshot:
        source_paths = self.paths_for(source)
        target_paths = self.paths_for(target_profile_id)
        source_snapshot = _snapshot_clone_storage(source_paths.user_data_dir)
        if source_snapshot.fingerprint != expected_fingerprint:
            raise ProfileStorageConflictError(
                "source Profile storage changed after clone preview"
            )
        if target_paths.user_data_dir.exists() and any(target_paths.user_data_dir.iterdir()):
            raise ProfileStorageConflictError("target Profile storage is not empty")
        required_bytes = source_snapshot.total_bytes + max(64 * 1024 * 1024, source_snapshot.total_bytes // 20)
        if shutil.disk_usage(target_paths.profile_root).free < required_bytes:
            raise ProfileStorageError("insufficient disk space for Profile clone")

        staging = target_paths.profile_root / ".clone"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True, exist_ok=False)
        try:
            _copy_clone_storage(source_paths.user_data_dir, staging)
            staged_snapshot = _snapshot_clone_storage(staging)
            if (
                staged_snapshot.file_count != source_snapshot.file_count
                or staged_snapshot.total_bytes != source_snapshot.total_bytes
                or staged_snapshot.fingerprint != source_snapshot.fingerprint
            ):
                raise ProfileStorageConflictError(
                    "cloned Profile storage did not match the source snapshot"
                )
            if target_paths.user_data_dir.exists():
                target_paths.user_data_dir.rmdir()
            os.replace(staging, target_paths.user_data_dir)
            return source_snapshot
        except Exception:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            raise

    def discard_unregistered_profile_storage(self, profile_id: str) -> None:
        _validate_profile_id(profile_id)
        if profile_id == "default":
            raise ProfileStorageError("default Profile storage cannot be discarded")
        profile_root = self.paths_for(profile_id, create=False).profile_root
        if profile_root.exists():
            shutil.rmtree(profile_root)

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


# Profile transfer is intentionally identity-focused. The top-level allowlist is
# only `Local State` plus the Chromium `Default` profile. Within `Default`, WebFA
# excludes human-browser history, password/autofill data, open tabs, extensions,
# caches, and other data that is not required to provision an Agent internet
# identity.

_IDENTITY_TRANSFER_EXCLUDED_PROFILE_NAMES = {
    "account web data",
    "account web data-journal",
    "affiliation database",
    "affiliation database-journal",
    "archived history",
    "autofillstrike database",
    "bookmarks",
    "bookmarks.bak",
    "commerce_subscription_db",
    "current session",
    "current tabs",
    "discounts_db",
    "download service",
    "extension cookies",
    "extension cookies-journal",
    "favicons",
    "favicons-journal",
    "history",
    "history-journal",
    "last session",
    "last tabs",
    "login data",
    "login data for account",
    "login data for account-journal",
    "login data-journal",
    "network action predictor",
    "network action predictor-journal",
    "parcel_tracking_db",
    "secure preferences",
    "shortcuts",
    "shortcuts-journal",
    "site characteristics database",
    "top sites",
    "top sites-journal",
    "visited links",
    "web data",
    "web data for account",
    "web data for account-journal",
    "web data-journal",
}

_IDENTITY_TRANSFER_EXCLUDED_PROFILE_PREFIXES = {
    "autofillstrikedatabase",
    "cache",
    "code cache",
    "dawngraphitecache",
    "dawnwebgpucache",
    "download service",
    "extension rules",
    "extension scripts",
    "extension state",
    "extensions",
    "gpucache",
    "local extension settings",
    "managed extension settings",
    "segmentation platform",
    "sessions",
    "sync data",
    "sync extension settings",
    "web applications",
}

_IDENTITY_TRANSFER_EXCLUDED_NETWORK_NAMES = {
    "network persistent state",
    "reporting and nel",
    "reporting and nel-journal",
    "transportsecurity",
}


def _snapshot_clone_storage(root: Path) -> ProfileCloneStorageSnapshot:
    digest = hashlib.sha256()
    file_count = 0
    total_bytes = 0
    excluded_count = 0
    for relative, path, is_directory, excluded in _walk_clone_storage(root):
        if excluded:
            excluded_count += 1
            continue
        encoded_relative = relative.as_posix().encode("utf-8", errors="surrogatepass")
        if is_directory:
            digest.update(b"D\0")
            digest.update(encoded_relative)
            digest.update(b"\0")
            continue
        stat_before = path.stat(follow_symlinks=False)
        content_digest = hashlib.sha256()
        try:
            with path.open("rb") as source:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    content_digest.update(chunk)
        except OSError as exc:
            raise ProfileStorageError("unable to hash Profile storage entry") from exc
        stat_after = path.stat(follow_symlinks=False)
        if (
            stat_before.st_size != stat_after.st_size
            or stat_before.st_mtime_ns != stat_after.st_mtime_ns
        ):
            raise ProfileStorageConflictError(
                "Profile storage changed while its transfer snapshot was being created"
            )
        file_count += 1
        total_bytes += stat_after.st_size
        digest.update(b"F\0")
        digest.update(encoded_relative)
        digest.update(b"\0")
        digest.update(str(stat_after.st_size).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(stat_after.st_mtime_ns).encode("ascii"))
        digest.update(b"\0")
        digest.update(content_digest.digest())
        digest.update(b"\0")
    return ProfileCloneStorageSnapshot(
        file_count=file_count,
        total_bytes=total_bytes,
        excluded_count=excluded_count,
        fingerprint=digest.hexdigest(),
    )


def _copy_clone_storage(source_root: Path, target_root: Path) -> None:
    for relative, source, is_directory, excluded in _walk_clone_storage(source_root):
        if excluded:
            continue
        target = target_root / relative
        if is_directory:
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target, follow_symlinks=False)


def _walk_clone_storage(root: Path):
    root.mkdir(parents=True, exist_ok=True)

    def visit(directory: Path, relative_root: Path):
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda item: item.name.casefold())
        except OSError as exc:
            raise ProfileStorageError("unable to inspect Profile storage for cloning") from exc
        for entry in entries:
            path = Path(entry.path)
            relative = relative_root / entry.name
            if _is_unsafe_link(path, entry):
                raise ProfileStorageUnsafeError(
                    "Profile storage contains a symbolic link or directory junction"
                )
            excluded = _clone_path_excluded(relative)
            try:
                is_directory = entry.is_dir(follow_symlinks=False)
                is_file = entry.is_file(follow_symlinks=False)
            except OSError as exc:
                raise ProfileStorageError("unable to inspect Profile storage entry") from exc
            if not is_directory and not is_file:
                raise ProfileStorageUnsafeError(
                    "Profile storage contains an unsupported filesystem entry"
                )
            yield relative, path, is_directory, excluded
            if is_directory and not excluded:
                yield from visit(path, relative)

    yield from visit(root, Path())


def profile_transfer_path_excluded(relative: Path) -> bool:
    parts = tuple(part.casefold() for part in relative.parts)
    if not parts:
        return False
    root = parts[0]
    if root == "local state":
        return len(parts) != 1
    if root != "default":
        return True
    if len(parts) == 1:
        return False
    child = parts[1]
    if (
        child == "network"
        and len(parts) >= 3
        and parts[2] in _IDENTITY_TRANSFER_EXCLUDED_NETWORK_NAMES
    ):
        return True
    if child in _IDENTITY_TRANSFER_EXCLUDED_PROFILE_NAMES:
        return True
    if child in _IDENTITY_TRANSFER_EXCLUDED_PROFILE_PREFIXES:
        return True
    return False


# Backward-compatible internal name used by older tests and call sites.
_clone_path_excluded = profile_transfer_path_excluded


def _is_unsafe_link(path: Path, entry: os.DirEntry[str]) -> bool:
    if entry.is_symlink() or _path_is_unsafe_link(path):
        return True
    return False


def _path_is_unsafe_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction()) if callable(is_junction) else False


def _reject_unsafe_managed_directory(path: Path) -> None:
    if _path_is_unsafe_link(path):
        raise ProfileStorageUnsafeError(
            "Profile storage path cannot be a symbolic link or directory junction"
        )


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
    if profile_id in {".", ".."} or any(char in profile_id for char in ("/", "\\", ":", "\0")):
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
