from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import secrets
import shutil
import stat
import struct
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from threading import RLock
from typing import Any, Callable, Literal
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from browser.profile_repository import (
    ProfileRepository,
    ProfileStateError,
    ProfileVersionConflictError,
)
from browser.profile_storage import (
    ProfileCloneStorageSnapshot,
    ProfileLockBusyError,
    ProfileMutationLease,
    ProfileProcessLock,
    ProfileStorageConflictError,
    ProfileStorageError,
    ProfileStorageManager,
    profile_transfer_path_excluded,
)
from schemas.profile import (
    BrowserProfile,
    BrowserProfileCreate,
    ProfileBootstrapSource,
)
from schemas.profile_bootstrap import (
    ProfileBundleExportPreview,
    ProfileBootstrapTarget,
    ProfileBundleRestorePreview,
    ProfileBundleRestoreResult,
)


BUNDLE_CONTENT_TYPE = "application/vnd.webfa.profile-bundle"
BUNDLE_PASSPHRASE_HEADER = "X-WebFA-Bundle-Passphrase"
BUNDLE_EXTENSION = ".webfa-profile"
BUNDLE_MAGIC = b"WEBFAPB1"
BUNDLE_FORMAT_VERSION = 1
BUNDLE_MANIFEST_NAME = "manifest.json"
BUNDLE_PROFILE_PREFIX = "profile/"
BUNDLE_HEADER_MAX_BYTES = 16 * 1024
BUNDLE_MANIFEST_MAX_BYTES = 2 * 1024 * 1024
MAX_BUNDLE_FILES = 200_000
MAX_BUNDLE_PLAINTEXT_BYTES = 50 * 1024 * 1024 * 1024
MAX_BUNDLE_ENCRYPTED_BYTES = 52 * 1024 * 1024 * 1024
BUNDLE_TAG_BYTES = 16
BUNDLE_CHUNK_BYTES = 1024 * 1024
BUNDLE_PREVIEW_TTL_SECONDS = 600
_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_LENGTH = 32


class ProfileBundleError(RuntimeError):
    code = "profile_bundle_error"


class ProfileBundlePreviewNotFoundError(ProfileBundleError):
    code = "profile_bundle_preview_not_found"


class ProfileBundlePreviewExpiredError(ProfileBundleError):
    code = "profile_bundle_preview_expired"


class ProfileBundleBindingError(ProfileBundleError):
    code = "profile_bundle_binding_mismatch"


class ProfileBundleBusyError(ProfileBundleError):
    code = "profile_bundle_busy"


class ProfileBundleSourceChangedError(ProfileBundleError):
    code = "profile_bundle_source_changed"


class ProfileBundlePassphraseError(ProfileBundleError):
    code = "profile_bundle_passphrase_invalid"


class ProfileBundleFormatError(ProfileBundleError):
    code = "profile_bundle_format_invalid"


class ProfileBundleIntegrityError(ProfileBundleError):
    code = "profile_bundle_integrity_failed"


class ProfileBundleLimitError(ProfileBundleError):
    code = "profile_bundle_limit_exceeded"


class ProfileBundleApplyError(ProfileBundleError):
    code = "profile_bundle_failed"


class _StrictBundleModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _BundleManifestEntry(_StrictBundleModel):
    path: str = Field(min_length=1, max_length=4096)
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class _BundleManifest(_StrictBundleModel):
    format: Literal["webfa-profile-bundle"] = "webfa-profile-bundle"
    version: Literal[1] = 1
    created_at: datetime
    source_agent_alias: str = Field(min_length=1, max_length=64)
    source_display_name: str = Field(min_length=1, max_length=200)
    source_bootstrap_source: str = Field(min_length=1, max_length=50)
    source_platform: str = Field(default="unknown", min_length=1, max_length=100)
    file_count: int = Field(ge=0, le=MAX_BUNDLE_FILES)
    total_bytes: int = Field(ge=0, le=MAX_BUNDLE_PLAINTEXT_BYTES)
    excluded_count: int = Field(ge=0)
    entries: list[_BundleManifestEntry] = Field(max_length=MAX_BUNDLE_FILES)


@dataclass(frozen=True)
class ProfileBundleArtifact:
    path: Path = field(repr=False)
    suggested_filename: str
    byte_count: int
    sha256: str
    content_type: str = BUNDLE_CONTENT_TYPE

    def delete(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass


@dataclass
class _PendingExport:
    token: str
    control_digest: str
    source_profile_id: str
    source_profile_version: int
    storage_snapshot: ProfileCloneStorageSnapshot
    summary: ProfileBundleExportPreview
    expires_at: datetime
    in_progress: bool = False


@dataclass
class _PendingRestore:
    token: str
    control_digest: str
    encrypted_path: Path = field(repr=False)
    manifest: _BundleManifest
    manifest_digest: str
    summary: ProfileBundleRestorePreview
    expires_at: datetime
    in_progress: bool = False


Clock = Callable[[], datetime]


class ProfileBundleService:
    def __init__(
        self,
        *,
        repository: ProfileRepository | None = None,
        storage: ProfileStorageManager | None = None,
        clock: Clock | None = None,
        preview_ttl_seconds: int = BUNDLE_PREVIEW_TTL_SECONDS,
        temp_root: Path | None = None,
    ) -> None:
        self._repository = repository or ProfileRepository()
        self._storage = storage or ProfileStorageManager()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._preview_ttl = max(60, min(preview_ttl_seconds, 3600))
        self._temp_root = (
            temp_root or (self._storage.data_dir / "profile-bundles" / "tmp")
        ).resolve()
        self._temp_root.mkdir(parents=True, exist_ok=True)
        service_identity = uuid4().hex
        try:
            self._service_lock = ProfileProcessLock(
                self._temp_root.parent / f".{self._temp_root.name}.service.lock",
                {
                    "profile_id": "profile-bundle-service",
                    "runtime_instance_id": f"bundle-service:{service_identity}",
                    "runtime_generation": f"bundle-service:{service_identity}",
                    "session_id": "profile-bundle-service",
                    "pid": os.getpid(),
                },
            ).acquire()
        except ProfileLockBusyError as exc:
            raise ProfileBundleBusyError(
                "another Runtime is already using the Profile Bundle temporary store"
            ) from exc
        self._exports: dict[str, _PendingExport] = {}
        self._restores: dict[str, _PendingRestore] = {}
        self._lock = RLock()
        self._closed = False
        try:
            self._purge_orphaned_temp_files()
        except Exception:
            self._service_lock.release()
            raise

    @property
    def temp_root(self) -> Path:
        return self._temp_root

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._exports.clear()
            self._restores.clear()
        try:
            self._purge_orphaned_temp_files()
        finally:
            self._service_lock.release()

    def create_upload_path(self) -> Path:
        path = self._temp_root / f"upload-{uuid4().hex}.bundle"
        path.touch(mode=0o600, exist_ok=False)
        _restrict_file_permissions(path)
        return path

    def preview_export(
        self,
        source_profile_ref: str,
        *,
        expected_source_version: int,
        control_token: str,
    ) -> ProfileBundleExportPreview:
        source = self._repository.get_profile(source_profile_ref)
        _require_persistent_ready(source, expected_version=expected_source_version)
        mutation_id = f"bundle_export_preview_{uuid4().hex}"
        try:
            lease = self._storage.acquire_mutation_lease(
                source,
                mutation_id=mutation_id,
                operation="profile_bundle_export_preview",
            )
        except ProfileLockBusyError as exc:
            raise ProfileBundleBusyError(
                "source Profile is active; close its Browser Session before export"
            ) from exc
        try:
            snapshot = self._storage.inspect_clone_source(source)
        except ProfileStorageError as exc:
            raise ProfileBundleApplyError(
                "unable to inspect source Profile storage"
            ) from exc
        finally:
            lease.release()
        _enforce_bundle_limits(snapshot.file_count, snapshot.total_bytes)

        now = self._clock()
        expires_at = now + timedelta(seconds=self._preview_ttl)
        token = f"bundle_export_{secrets.token_urlsafe(32)}"
        filename = f"{_safe_filename(source.agent_alias)}{BUNDLE_EXTENSION}"
        summary = ProfileBundleExportPreview(
            preview_token=token,
            source_profile_id=source.profile_id,
            source_profile_version=source.version,
            source_agent_alias=source.agent_alias,
            source_display_name=source.display_name,
            file_count=snapshot.file_count,
            total_bytes=snapshot.total_bytes,
            excluded_count=snapshot.excluded_count,
            suggested_filename=filename,
            expires_at=expires_at,
        )
        pending = _PendingExport(
            token=token,
            control_digest=_control_digest(control_token),
            source_profile_id=source.profile_id,
            source_profile_version=source.version,
            storage_snapshot=snapshot,
            summary=summary,
            expires_at=expires_at,
        )
        with self._lock:
            self._purge_expired_locked(now)
            self._cap_pending_locked(self._exports)
            self._exports[token] = pending
        self._record_event(
            profile_id=source.profile_id,
            event_type="profile_bundle_export_previewed",
            safe_metadata={
                "file_count": snapshot.file_count,
                "total_bytes": snapshot.total_bytes,
                "excluded_count": snapshot.excluded_count,
            },
        )
        return summary.model_copy(deep=True)

    def cancel_export(
        self,
        source_profile_ref: str,
        *,
        preview_token: str,
        control_token: str,
    ) -> ProfileBundleExportPreview:
        source = self._repository.get_profile(source_profile_ref)
        now = self._clock()
        with self._lock:
            self._purge_expired_locked(now)
            pending = self._exports.get(preview_token)
            if pending is None:
                raise ProfileBundlePreviewNotFoundError(
                    "Profile Bundle export preview was not found"
                )
            if pending.in_progress:
                raise ProfileBundleBusyError(
                    "Profile Bundle export is already in progress"
                )
            _require_pending_binding(
                pending.control_digest,
                control_token,
                pending.source_profile_id == source.profile_id,
            )
            removed = self._exports.pop(preview_token)
        return removed.summary.model_copy(deep=True)

    def export_bundle(
        self,
        source_profile_ref: str,
        *,
        preview_token: str,
        expected_source_version: int,
        passphrase: str,
        control_token: str,
    ) -> ProfileBundleArtifact:
        _validate_passphrase(passphrase)
        source = self._repository.get_profile(source_profile_ref)
        now = self._clock()
        with self._lock:
            pending = self._exports.get(preview_token)
            if pending is not None and pending.expires_at <= now:
                self._exports.pop(preview_token, None)
                raise ProfileBundlePreviewExpiredError(
                    "Profile Bundle export preview has expired"
                )
            self._purge_expired_locked(now)
            pending = self._exports.get(preview_token)
            if pending is None:
                raise ProfileBundlePreviewNotFoundError(
                    "Profile Bundle export preview was not found"
                )
            if pending.in_progress:
                raise ProfileBundleBusyError(
                    "Profile Bundle export is already in progress"
                )
            _require_pending_binding(
                pending.control_digest,
                control_token,
                pending.source_profile_id == source.profile_id
                and pending.source_profile_version == expected_source_version,
            )
            pending.in_progress = True

        try:
            _require_persistent_ready(
                source,
                expected_version=expected_source_version,
            )
        except Exception:
            with self._lock:
                pending.in_progress = False
            raise

        mutation_id = f"profile_bundle_export_{uuid4().hex}"
        try:
            lease = self._storage.acquire_mutation_lease(
                source,
                mutation_id=mutation_id,
                operation="profile_bundle_export",
            )
        except ProfileLockBusyError as exc:
            with self._lock:
                pending.in_progress = False
            raise ProfileBundleBusyError(
                "source Profile is active; close its Browser Session before export"
            ) from exc

        try:
            current = self._storage.inspect_clone_source(source)
            if current.fingerprint != pending.storage_snapshot.fingerprint:
                with self._lock:
                    self._exports.pop(preview_token, None)
                raise ProfileBundleSourceChangedError(
                    "source Profile storage changed after export preview"
                )
            artifact = self._build_encrypted_bundle(
                source,
                current,
                passphrase=passphrase,
                suggested_filename=pending.summary.suggested_filename,
            )
            with self._lock:
                self._exports.pop(preview_token, None)
            self._record_event(
                profile_id=source.profile_id,
                event_type="profile_bundle_exported",
                safe_metadata={
                    "file_count": current.file_count,
                    "total_bytes": current.total_bytes,
                    "bundle_bytes": artifact.byte_count,
                },
            )
            return artifact
        except ProfileBundleSourceChangedError:
            with self._lock:
                self._exports.pop(preview_token, None)
            raise
        except ProfileBundleError:
            with self._lock:
                pending.in_progress = False
            raise
        except ProfileStorageError as exc:
            with self._lock:
                pending.in_progress = False
            raise ProfileBundleApplyError("Profile Bundle export failed") from exc
        except Exception as exc:
            with self._lock:
                pending.in_progress = False
            raise ProfileBundleApplyError("Profile Bundle export failed") from exc
        finally:
            lease.release()

    def preview_restore(
        self,
        encrypted_path: Path,
        *,
        passphrase: str,
        control_token: str,
    ) -> ProfileBundleRestorePreview:
        _validate_passphrase(passphrase)
        encrypted_path = encrypted_path.resolve()
        _require_temp_child(encrypted_path, self._temp_root)
        if not encrypted_path.is_file():
            raise ProfileBundleFormatError("Profile Bundle upload is unavailable")
        if encrypted_path.stat().st_size > MAX_BUNDLE_ENCRYPTED_BYTES:
            _delete_file(encrypted_path)
            raise ProfileBundleLimitError("Profile Bundle exceeds the size limit")

        plaintext_path = self._temp_root / f"inspect-{uuid4().hex}.zip"
        try:
            _decrypt_bundle_file(
                encrypted_path,
                plaintext_path,
                passphrase=passphrase,
            )
            manifest, manifest_digest = _inspect_bundle_zip(plaintext_path)
        except Exception:
            _delete_file(encrypted_path)
            raise
        finally:
            _delete_file(plaintext_path)

        now = self._clock()
        expires_at = now + timedelta(seconds=self._preview_ttl)
        token = f"bundle_restore_{secrets.token_urlsafe(32)}"
        summary = ProfileBundleRestorePreview(
            preview_token=token,
            bundle_format_version=manifest.version,
            source_agent_alias=manifest.source_agent_alias,
            source_display_name=manifest.source_display_name,
            source_bootstrap_source=manifest.source_bootstrap_source,
            source_platform=manifest.source_platform,
            current_platform=_current_platform_id(),
            restoration_scope="browser_storage_only",
            compatibility_warning=_bundle_compatibility_warning(manifest.source_platform),
            file_count=manifest.file_count,
            total_bytes=manifest.total_bytes,
            created_at=manifest.created_at,
            expires_at=expires_at,
        )
        pending = _PendingRestore(
            token=token,
            control_digest=_control_digest(control_token),
            encrypted_path=encrypted_path,
            manifest=manifest,
            manifest_digest=manifest_digest,
            summary=summary,
            expires_at=expires_at,
        )
        with self._lock:
            self._purge_expired_locked(now)
            self._cap_restore_pending_locked()
            self._restores[token] = pending
        return summary.model_copy(deep=True)

    def cancel_restore(
        self,
        *,
        preview_token: str,
        control_token: str,
    ) -> ProfileBundleRestorePreview:
        now = self._clock()
        with self._lock:
            self._purge_expired_locked(now)
            pending = self._restores.get(preview_token)
            if pending is None:
                raise ProfileBundlePreviewNotFoundError(
                    "Profile Bundle restore preview was not found"
                )
            if pending.in_progress:
                raise ProfileBundleBusyError(
                    "Profile Bundle restore is already in progress"
                )
            _require_pending_binding(
                pending.control_digest,
                control_token,
                True,
            )
            removed = self._restores.pop(preview_token)
        _delete_file(removed.encrypted_path)
        return removed.summary.model_copy(deep=True)

    def restore_bundle(
        self,
        *,
        preview_token: str,
        passphrase: str,
        target_profile: ProfileBootstrapTarget | BrowserProfileCreate,
        control_token: str,
    ) -> ProfileBundleRestoreResult:
        _validate_passphrase(passphrase)
        now = self._clock()
        with self._lock:
            pending = self._restores.get(preview_token)
            if pending is not None and pending.expires_at <= now:
                removed = self._restores.pop(preview_token)
                _delete_file(removed.encrypted_path)
                raise ProfileBundlePreviewExpiredError(
                    "Profile Bundle restore preview has expired"
                )
            self._purge_expired_locked(now)
            pending = self._restores.get(preview_token)
            if pending is None:
                raise ProfileBundlePreviewNotFoundError(
                    "Profile Bundle restore preview was not found"
                )
            if pending.in_progress:
                raise ProfileBundleBusyError(
                    "Profile Bundle restore is already in progress"
                )
            _require_pending_binding(
                pending.control_digest,
                control_token,
                True,
            )
            pending.in_progress = True

        target_profile_id = f"profile_{uuid4().hex}"
        mutation_id = f"profile_bundle_restore_{uuid4().hex}"
        target_lease: ProfileMutationLease | None = None
        created_profile: BrowserProfile | None = None
        plaintext_path = self._temp_root / f"restore-{uuid4().hex}.zip"
        try:
            target_lease = self._storage.acquire_mutation_lease(
                target_profile_id,
                mutation_id=mutation_id,
                operation="profile_bundle_restore_target",
            )
            _decrypt_bundle_file(
                pending.encrypted_path,
                plaintext_path,
                passphrase=passphrase,
            )
            manifest, manifest_digest = _inspect_bundle_zip(plaintext_path)
            if manifest_digest != pending.manifest_digest:
                raise ProfileBundleIntegrityError(
                    "Profile Bundle manifest changed after restore preview"
                )
            self._restore_zip_to_profile(
                plaintext_path,
                target_profile_id=target_profile_id,
                manifest=manifest,
            )
            target_payload = _bootstrap_target_payload(
                target_profile,
                bootstrap_source="restored",
            )
            created_profile = self._repository.create_profile(
                target_payload,
                profile_id=target_profile_id,
            )
            occurred_at = self._clock()
            self._record_event(
                profile_id=created_profile.profile_id,
                event_type="profile_bundle_restored",
                safe_metadata={
                    "file_count": manifest.file_count,
                    "total_bytes": manifest.total_bytes,
                    "source_bootstrap_source": manifest.source_bootstrap_source,
                },
            )
            with self._lock:
                self._restores.pop(preview_token, None)
            _delete_file(pending.encrypted_path)
            return ProfileBundleRestoreResult(
                target_profile_id=created_profile.profile_id,
                target_agent_alias=created_profile.agent_alias,
                target_profile_version=created_profile.version,
                file_count=manifest.file_count,
                total_bytes=manifest.total_bytes,
                occurred_at=occurred_at,
            )
        except ProfileLockBusyError as exc:
            with self._lock:
                pending.in_progress = False
            raise ProfileBundleBusyError("Profile Bundle restore target is busy") from exc
        except ProfileBundleError:
            with self._lock:
                pending.in_progress = False
            raise
        except ProfileStorageError as exc:
            with self._lock:
                pending.in_progress = False
            raise ProfileBundleApplyError(
                "Profile Bundle restore failed"
            ) from exc
        except Exception:
            with self._lock:
                pending.in_progress = False
            raise
        finally:
            _delete_file(plaintext_path)
            if target_lease is not None:
                target_lease.release()
            if created_profile is None:
                try:
                    self._storage.discard_unregistered_profile_storage(
                        target_profile_id
                    )
                except Exception:
                    pass

    def _build_encrypted_bundle(
        self,
        source: BrowserProfile,
        snapshot: ProfileCloneStorageSnapshot,
        *,
        passphrase: str,
        suggested_filename: str,
    ) -> ProfileBundleArtifact:
        plaintext_path = self._temp_root / f"plain-{uuid4().hex}.zip"
        encrypted_path = self._temp_root / f"bundle-{uuid4().hex}{BUNDLE_EXTENSION}"
        try:
            manifest = self._build_manifest(source, snapshot)
            _write_bundle_zip(
                plaintext_path,
                source_files=list(self._storage.iter_clone_files(source)),
                manifest=manifest,
            )
            verified_manifest, _ = _inspect_bundle_zip(plaintext_path)
            if verified_manifest.model_dump(mode="json") != manifest.model_dump(mode="json"):
                raise ProfileBundleSourceChangedError(
                    "source Profile storage changed while writing the Bundle archive"
                )
            _encrypt_bundle_file(
                plaintext_path,
                encrypted_path,
                passphrase=passphrase,
                created_at=self._clock(),
            )
            bundle_hash = _sha256_file(encrypted_path)
            return ProfileBundleArtifact(
                path=encrypted_path,
                suggested_filename=suggested_filename,
                byte_count=encrypted_path.stat().st_size,
                sha256=bundle_hash,
            )
        except Exception:
            _delete_file(encrypted_path)
            raise
        finally:
            _delete_file(plaintext_path)

    def _build_manifest(
        self,
        source: BrowserProfile,
        snapshot: ProfileCloneStorageSnapshot,
    ) -> _BundleManifest:
        entries: list[_BundleManifestEntry] = []
        total_bytes = 0
        for relative, path in self._storage.iter_clone_files(source):
            size = path.stat(follow_symlinks=False).st_size
            entries.append(
                _BundleManifestEntry(
                    path=f"{BUNDLE_PROFILE_PREFIX}{relative.as_posix()}",
                    size=size,
                    sha256=_sha256_file(path),
                )
            )
            total_bytes += size
        if len(entries) != snapshot.file_count or total_bytes != snapshot.total_bytes:
            raise ProfileBundleSourceChangedError(
                "source Profile storage changed while building the Bundle manifest"
            )
        return _BundleManifest(
            created_at=self._clock(),
            source_agent_alias=source.agent_alias,
            source_display_name=source.display_name,
            source_bootstrap_source=source.bootstrap_source,
            source_platform=_current_platform_id(),
            file_count=len(entries),
            total_bytes=total_bytes,
            excluded_count=snapshot.excluded_count,
            entries=entries,
        )

    def _restore_zip_to_profile(
        self,
        zip_path: Path,
        *,
        target_profile_id: str,
        manifest: _BundleManifest,
    ) -> None:
        target_paths = self._storage.paths_for(target_profile_id)
        if target_paths.user_data_dir.exists() and any(
            target_paths.user_data_dir.iterdir()
        ):
            raise ProfileStorageConflictError(
                "target Profile storage is not empty"
            )
        required_bytes = manifest.total_bytes + max(
            64 * 1024 * 1024,
            manifest.total_bytes // 20,
        )
        if shutil.disk_usage(target_paths.profile_root).free < required_bytes:
            raise ProfileBundleLimitError(
                "insufficient disk space for Profile Bundle restore"
            )
        staging = target_paths.profile_root / ".restore"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True, exist_ok=False)
        entry_by_path = {entry.path: entry for entry in manifest.entries}
        try:
            with zipfile.ZipFile(zip_path, "r") as archive:
                for info in archive.infolist():
                    if info.filename == BUNDLE_MANIFEST_NAME:
                        continue
                    entry = entry_by_path[info.filename]
                    relative = PurePosixPath(info.filename).relative_to(
                        PurePosixPath(BUNDLE_PROFILE_PREFIX.rstrip("/"))
                    )
                    target = staging.joinpath(*relative.parts)
                    _require_path_within(target, staging)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    digest = hashlib.sha256()
                    written = 0
                    with archive.open(info, "r") as source, target.open("xb") as output:
                        while True:
                            chunk = source.read(BUNDLE_CHUNK_BYTES)
                            if not chunk:
                                break
                            written += len(chunk)
                            if written > entry.size:
                                raise ProfileBundleIntegrityError(
                                    "Profile Bundle entry exceeded its declared size"
                                )
                            digest.update(chunk)
                            output.write(chunk)
                        output.flush()
                        os.fsync(output.fileno())
                    if written != entry.size or digest.hexdigest() != entry.sha256:
                        raise ProfileBundleIntegrityError(
                            "Profile Bundle entry failed integrity verification"
                        )
            if target_paths.user_data_dir.exists():
                target_paths.user_data_dir.rmdir()
            os.replace(staging, target_paths.user_data_dir)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            raise

    def _purge_expired_locked(self, now: datetime) -> None:
        for token in [
            token
            for token, pending in self._exports.items()
            if pending.expires_at <= now and not pending.in_progress
        ]:
            self._exports.pop(token, None)
        expired_restores = [
            token
            for token, pending in self._restores.items()
            if pending.expires_at <= now and not pending.in_progress
        ]
        for token in expired_restores:
            pending = self._restores.pop(token)
            _delete_file(pending.encrypted_path)

    @staticmethod
    def _cap_pending_locked(pending: dict[str, _PendingExport]) -> None:
        if len(pending) < 20:
            return
        oldest = min(pending.values(), key=lambda item: item.expires_at)
        pending.pop(oldest.token, None)

    def _cap_restore_pending_locked(self) -> None:
        if len(self._restores) < 10:
            return
        oldest = min(self._restores.values(), key=lambda item: item.expires_at)
        self._restores.pop(oldest.token, None)
        _delete_file(oldest.encrypted_path)

    def _purge_orphaned_temp_files(self) -> None:
        # Preview state is intentionally in-memory only. After service restart or
        # shutdown no temporary artifact can belong to a valid operation, so
        # retaining even a recent plaintext ZIP would only extend secret lifetime.
        for path in self._temp_root.iterdir():
            try:
                if path.is_file() or path.is_symlink():
                    path.unlink(missing_ok=True)
                elif path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
            except OSError:
                continue

    def _record_event(
        self,
        *,
        profile_id: str,
        event_type: str,
        safe_metadata: dict[str, Any],
    ) -> None:
        try:
            self._repository.record_runtime_event(
                profile_id=profile_id,
                event_type=event_type,
                safe_metadata=safe_metadata,
            )
        except Exception:
            pass


def _bootstrap_target_payload(
    target: ProfileBootstrapTarget | BrowserProfileCreate,
    *,
    bootstrap_source: ProfileBootstrapSource,
) -> BrowserProfileCreate:
    if isinstance(target, ProfileBootstrapTarget):
        return target.to_profile_create(bootstrap_source=bootstrap_source)
    return ProfileBootstrapTarget(
        agent_alias=target.agent_alias,
        display_name=target.display_name,
        agent_description=target.agent_description,
        owner=target.owner,
        trust_mode=target.trust_mode,
    ).to_profile_create(bootstrap_source=bootstrap_source)


def _write_bundle_zip(
    path: Path,
    *,
    source_files: list[tuple[Path, Path]],
    manifest: _BundleManifest,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600, exist_ok=False)
    _restrict_file_permissions(path)
    with zipfile.ZipFile(
        path,
        mode="w",
        compression=zipfile.ZIP_STORED,
        allowZip64=True,
        strict_timestamps=False,
    ) as archive:
        manifest_bytes = _canonical_json_bytes(manifest.model_dump(mode="json"))
        if len(manifest_bytes) > BUNDLE_MANIFEST_MAX_BYTES:
            raise ProfileBundleLimitError("Profile Bundle manifest exceeds the size limit")
        archive.writestr(BUNDLE_MANIFEST_NAME, manifest_bytes)
        for relative, source in source_files:
            archive.write(
                source,
                arcname=f"{BUNDLE_PROFILE_PREFIX}{relative.as_posix()}",
                compress_type=zipfile.ZIP_STORED,
            )
    _restrict_file_permissions(path)


def _inspect_bundle_zip(path: Path) -> tuple[_BundleManifest, str]:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            infos = archive.infolist()
            if len(infos) > MAX_BUNDLE_FILES + 1:
                raise ProfileBundleLimitError(
                    "Profile Bundle contains too many archive members"
                )
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise ProfileBundleFormatError(
                    "Profile Bundle contains duplicate archive members"
                )
            if names.count(BUNDLE_MANIFEST_NAME) != 1:
                raise ProfileBundleFormatError(
                    "Profile Bundle manifest is missing or duplicated"
                )
            info_by_name: dict[str, zipfile.ZipInfo] = {}
            total_bytes = 0
            for info in infos:
                _validate_zip_info(info)
                if info.filename == BUNDLE_MANIFEST_NAME:
                    if info.file_size > BUNDLE_MANIFEST_MAX_BYTES:
                        raise ProfileBundleLimitError(
                            "Profile Bundle manifest exceeds the size limit"
                        )
                    continue
                total_bytes += info.file_size
                if total_bytes > MAX_BUNDLE_PLAINTEXT_BYTES:
                    raise ProfileBundleLimitError(
                        "Profile Bundle exceeds the uncompressed size limit"
                    )
                info_by_name[info.filename] = info
            manifest_bytes = archive.read(BUNDLE_MANIFEST_NAME)
            try:
                manifest = _BundleManifest.model_validate_json(manifest_bytes)
            except ValidationError as exc:
                raise ProfileBundleFormatError(
                    "Profile Bundle manifest is invalid"
                ) from exc
            manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
            if manifest.file_count != len(manifest.entries):
                raise ProfileBundleFormatError(
                    "Profile Bundle manifest file count is inconsistent"
                )
            manifest_names = [entry.path for entry in manifest.entries]
            if len(manifest_names) != len(set(manifest_names)):
                raise ProfileBundleFormatError(
                    "Profile Bundle manifest contains duplicate entry paths"
                )
            if manifest.file_count != len(info_by_name):
                raise ProfileBundleFormatError(
                    "Profile Bundle manifest and archive file counts differ"
                )
            if manifest.total_bytes != sum(entry.size for entry in manifest.entries):
                raise ProfileBundleFormatError(
                    "Profile Bundle manifest byte count is inconsistent"
                )
            if manifest.total_bytes != total_bytes:
                raise ProfileBundleFormatError(
                    "Profile Bundle archive byte count is inconsistent"
                )
            expected_names = {entry.path for entry in manifest.entries}
            if expected_names != set(info_by_name):
                raise ProfileBundleFormatError(
                    "Profile Bundle archive members do not match the manifest"
                )
            for entry in manifest.entries:
                relative = _validate_bundle_member_name(entry.path)
                if profile_transfer_path_excluded(Path(*relative.parts)):
                    raise ProfileBundleFormatError(
                        "Profile Bundle contains browser data outside the WebFA identity-transfer scope"
                    )
                info = info_by_name[entry.path]
                if info.file_size != entry.size:
                    raise ProfileBundleIntegrityError(
                        "Profile Bundle entry size does not match the manifest"
                    )
                digest = hashlib.sha256()
                read_bytes = 0
                with archive.open(info, "r") as source:
                    while True:
                        chunk = source.read(BUNDLE_CHUNK_BYTES)
                        if not chunk:
                            break
                        read_bytes += len(chunk)
                        if read_bytes > entry.size:
                            raise ProfileBundleIntegrityError(
                                "Profile Bundle entry exceeded its declared size"
                            )
                        digest.update(chunk)
                if read_bytes != entry.size or digest.hexdigest() != entry.sha256:
                    raise ProfileBundleIntegrityError(
                        "Profile Bundle entry failed integrity verification"
                    )
            return manifest, manifest_digest
    except zipfile.BadZipFile as exc:
        raise ProfileBundleFormatError("Profile Bundle payload is not a valid ZIP") from exc


def _encrypt_bundle_file(
    plaintext_path: Path,
    encrypted_path: Path,
    *,
    passphrase: str,
    created_at: datetime,
) -> None:
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(12)
    plaintext_bytes = plaintext_path.stat().st_size
    if plaintext_bytes > MAX_BUNDLE_PLAINTEXT_BYTES:
        raise ProfileBundleLimitError("Profile Bundle plaintext exceeds the size limit")
    header = {
        "format": "webfa-profile-bundle-encrypted",
        "version": BUNDLE_FORMAT_VERSION,
        "cipher": "AES-256-GCM",
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "kdf": {
            "name": "scrypt",
            "salt": base64.b64encode(salt).decode("ascii"),
            "n": _SCRYPT_N,
            "r": _SCRYPT_R,
            "p": _SCRYPT_P,
            "length": _SCRYPT_LENGTH,
        },
        "plaintext_bytes": plaintext_bytes,
        "created_at": created_at.astimezone(timezone.utc).isoformat(),
    }
    header_bytes = _canonical_json_bytes(header)
    if len(header_bytes) > BUNDLE_HEADER_MAX_BYTES:
        raise ProfileBundleFormatError("Profile Bundle encryption header is too large")
    header_length = struct.pack(">I", len(header_bytes))
    aad = BUNDLE_MAGIC + header_length + header_bytes
    key = _derive_key(passphrase, salt=salt)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(aad)
    encrypted_path.parent.mkdir(parents=True, exist_ok=True)
    with plaintext_path.open("rb") as source, encrypted_path.open("xb") as output:
        _restrict_file_permissions(encrypted_path)
        output.write(aad)
        while True:
            chunk = source.read(BUNDLE_CHUNK_BYTES)
            if not chunk:
                break
            output.write(encryptor.update(chunk))
        output.write(encryptor.finalize())
        output.write(encryptor.tag)
        output.flush()
        os.fsync(output.fileno())
    _restrict_file_permissions(encrypted_path)


def _decrypt_bundle_file(
    encrypted_path: Path,
    plaintext_path: Path,
    *,
    passphrase: str,
) -> dict[str, Any]:
    _validate_passphrase(passphrase)
    file_size = encrypted_path.stat().st_size
    if file_size > MAX_BUNDLE_ENCRYPTED_BYTES:
        raise ProfileBundleLimitError("Profile Bundle exceeds the size limit")
    minimum_size = len(BUNDLE_MAGIC) + 4 + 2 + BUNDLE_TAG_BYTES
    if file_size < minimum_size:
        raise ProfileBundleFormatError("Profile Bundle is truncated")
    with encrypted_path.open("rb") as source:
        magic = source.read(len(BUNDLE_MAGIC))
        if magic != BUNDLE_MAGIC:
            raise ProfileBundleFormatError("Profile Bundle magic is invalid")
        raw_header_length = source.read(4)
        if len(raw_header_length) != 4:
            raise ProfileBundleFormatError("Profile Bundle header is truncated")
        header_size = struct.unpack(">I", raw_header_length)[0]
        if header_size <= 0 or header_size > BUNDLE_HEADER_MAX_BYTES:
            raise ProfileBundleFormatError("Profile Bundle header length is invalid")
        header_bytes = source.read(header_size)
        if len(header_bytes) != header_size:
            raise ProfileBundleFormatError("Profile Bundle header is truncated")
        try:
            header = json.loads(header_bytes)
        except json.JSONDecodeError as exc:
            raise ProfileBundleFormatError("Profile Bundle header JSON is invalid") from exc
        salt, nonce, plaintext_bytes = _validate_encryption_header(header)
        ciphertext_offset = len(BUNDLE_MAGIC) + 4 + header_size
        ciphertext_bytes = file_size - ciphertext_offset - BUNDLE_TAG_BYTES
        if ciphertext_bytes < 0 or ciphertext_bytes != plaintext_bytes:
            raise ProfileBundleFormatError(
                "Profile Bundle encrypted length is inconsistent"
            )
        source.seek(file_size - BUNDLE_TAG_BYTES)
        tag = source.read(BUNDLE_TAG_BYTES)
        source.seek(ciphertext_offset)
        key = _derive_key(passphrase, salt=salt)
        decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        decryptor.authenticate_additional_data(
            BUNDLE_MAGIC + raw_header_length + header_bytes
        )
        plaintext_path.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        try:
            with plaintext_path.open("xb") as output:
                _restrict_file_permissions(plaintext_path)
                remaining = ciphertext_bytes
                while remaining:
                    chunk = source.read(min(BUNDLE_CHUNK_BYTES, remaining))
                    if not chunk:
                        raise ProfileBundleFormatError(
                            "Profile Bundle ciphertext is truncated"
                        )
                    remaining -= len(chunk)
                    plain = decryptor.update(chunk)
                    written += len(plain)
                    if written > plaintext_bytes:
                        raise ProfileBundleLimitError(
                            "Profile Bundle plaintext exceeded its declared size"
                        )
                    output.write(plain)
                final = decryptor.finalize()
                written += len(final)
                output.write(final)
                output.flush()
                os.fsync(output.fileno())
        except InvalidTag as exc:
            _delete_file(plaintext_path)
            raise ProfileBundlePassphraseError(
                "Profile Bundle passphrase is incorrect or the bundle was modified"
            ) from exc
        except Exception:
            _delete_file(plaintext_path)
            raise
        if written != plaintext_bytes:
            _delete_file(plaintext_path)
            raise ProfileBundleIntegrityError(
                "Profile Bundle plaintext length is inconsistent"
            )
        _restrict_file_permissions(plaintext_path)
        return header


def _validate_encryption_header(
    header: object,
) -> tuple[bytes, bytes, int]:
    if not isinstance(header, dict):
        raise ProfileBundleFormatError("Profile Bundle header must be an object")
    if set(header) != {
        "format",
        "version",
        "cipher",
        "nonce",
        "kdf",
        "plaintext_bytes",
        "created_at",
    }:
        raise ProfileBundleFormatError("Profile Bundle header fields are invalid")
    if (
        header.get("format") != "webfa-profile-bundle-encrypted"
        or header.get("version") != BUNDLE_FORMAT_VERSION
        or header.get("cipher") != "AES-256-GCM"
    ):
        raise ProfileBundleFormatError("Profile Bundle encryption format is unsupported")
    kdf = header.get("kdf")
    if not isinstance(kdf, dict) or set(kdf) != {
        "name",
        "salt",
        "n",
        "r",
        "p",
        "length",
    }:
        raise ProfileBundleFormatError("Profile Bundle KDF parameters are invalid")
    if (
        kdf.get("name") != "scrypt"
        or kdf.get("n") != _SCRYPT_N
        or kdf.get("r") != _SCRYPT_R
        or kdf.get("p") != _SCRYPT_P
        or kdf.get("length") != _SCRYPT_LENGTH
    ):
        raise ProfileBundleFormatError("Profile Bundle KDF parameters are unsupported")
    try:
        salt = base64.b64decode(kdf["salt"], validate=True)
        nonce = base64.b64decode(header["nonce"], validate=True)
    except (TypeError, ValueError) as exc:
        raise ProfileBundleFormatError(
            "Profile Bundle binary header fields are invalid"
        ) from exc
    if len(salt) != 16 or len(nonce) != 12:
        raise ProfileBundleFormatError(
            "Profile Bundle salt or nonce length is invalid"
        )
    plaintext_bytes = header.get("plaintext_bytes")
    if (
        not isinstance(plaintext_bytes, int)
        or isinstance(plaintext_bytes, bool)
        or plaintext_bytes < 0
        or plaintext_bytes > MAX_BUNDLE_PLAINTEXT_BYTES
    ):
        raise ProfileBundleLimitError(
            "Profile Bundle plaintext size is invalid"
        )
    try:
        datetime.fromisoformat(str(header.get("created_at")))
    except ValueError as exc:
        raise ProfileBundleFormatError(
            "Profile Bundle creation timestamp is invalid"
        ) from exc
    return salt, nonce, plaintext_bytes


def _validate_zip_info(info: zipfile.ZipInfo) -> None:
    if info.flag_bits & 0x1:
        raise ProfileBundleFormatError(
            "nested ZIP encryption is not supported in Profile Bundles"
        )
    if info.compress_type != zipfile.ZIP_STORED:
        raise ProfileBundleFormatError(
            "Profile Bundle entries must use the stored ZIP method"
        )
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    if stat.S_ISLNK(unix_mode):
        raise ProfileBundleFormatError(
            "Profile Bundle contains a symbolic-link archive member"
        )
    if info.is_dir():
        raise ProfileBundleFormatError(
            "Profile Bundle must not contain explicit directory entries"
        )
    if info.filename != BUNDLE_MANIFEST_NAME:
        _validate_bundle_member_name(info.filename)


def _validate_bundle_member_name(name: str) -> PurePosixPath:
    if not isinstance(name, str) or not name.startswith(BUNDLE_PROFILE_PREFIX):
        raise ProfileBundleFormatError(
            "Profile Bundle member is outside the profile root"
        )
    if "\\" in name or chr(0) in name or len(name) > 4096:
        raise ProfileBundleFormatError("Profile Bundle member path is invalid")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ProfileBundleFormatError("Profile Bundle member path is unsafe")
    relative = path.relative_to(PurePosixPath(BUNDLE_PROFILE_PREFIX.rstrip("/")))
    if not relative.parts:
        raise ProfileBundleFormatError("Profile Bundle member path is empty")
    for component in relative.parts:
        if _unsafe_windows_component(component):
            raise ProfileBundleFormatError(
                "Profile Bundle member path is incompatible with the local filesystem"
            )
    return relative


def _unsafe_windows_component(component: str) -> bool:
    if any(char in component for char in '<>:"|?*'):
        return True
    if component.endswith((" ", ".")):
        return True
    stem = component.split(".", 1)[0].upper()
    reserved = {"CON", "PRN", "AUX", "NUL", "CLOCK$"}
    reserved.update({f"COM{index}" for index in range(1, 10)})
    reserved.update({f"LPT{index}" for index in range(1, 10)})
    return stem in reserved


def _derive_key(passphrase: str, *, salt: bytes) -> bytes:
    _validate_passphrase(passphrase)
    return Scrypt(
        salt=salt,
        length=_SCRYPT_LENGTH,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
    ).derive(passphrase.encode("utf-8"))


def _validate_passphrase(passphrase: str) -> None:
    if not isinstance(passphrase, str) or not 12 <= len(passphrase) <= 1024:
        raise ProfileBundlePassphraseError(
            "Profile Bundle passphrase must contain 12 to 1024 characters"
        )
    if "\x00" in passphrase:
        raise ProfileBundlePassphraseError(
            "Profile Bundle passphrase contains an invalid character"
        )


def _require_persistent_ready(
    profile: BrowserProfile,
    *,
    expected_version: int,
) -> None:
    if profile.version != expected_version:
        raise ProfileVersionConflictError(
            f"profile version is {profile.version}, expected {expected_version}"
        )
    if profile.catalog_state != "ready":
        raise ProfileStateError(
            f"profile in state '{profile.catalog_state}' cannot be bundled"
        )
    if profile.persistence != "persistent":
        raise ProfileStateError(
            "Profile Bundle operations require a persistent Browser Profile"
        )


def _require_pending_binding(
    expected_control_digest: str,
    control_token: str,
    scope_matches: bool,
) -> None:
    if (
        expected_control_digest != _control_digest(control_token)
        or not scope_matches
    ):
        raise ProfileBundleBindingError(
            "Profile Bundle preview is bound to another Profile, version, or control session"
        )


def _control_digest(control_token: str) -> str:
    if not control_token:
        raise ProfileBundleBindingError("visualizer control token is required")
    return hashlib.sha256(control_token.encode("utf-8")).hexdigest()


def _enforce_bundle_limits(file_count: int, total_bytes: int) -> None:
    if file_count > MAX_BUNDLE_FILES:
        raise ProfileBundleLimitError("Profile contains too many files for a Bundle")
    if total_bytes > MAX_BUNDLE_PLAINTEXT_BYTES:
        raise ProfileBundleLimitError("Profile exceeds the Bundle size limit")


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(BUNDLE_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _current_platform_id() -> str:
    system = platform.system().strip().lower() or "unknown"
    machine = platform.machine().strip().lower() or "unknown"
    return f"{system}-{machine}"[:100]


def _bundle_compatibility_warning(source_platform: str) -> str:
    current = _current_platform_id()
    if source_platform != current:
        return (
            "Bundle storage was created on a different OS or architecture. "
            "Files may restore, but Chromium credentials and website sessions may remain unusable."
        )
    return (
        "Bundle restore recreates browser storage only. Authentication is not guaranteed because "
        "Chromium or websites may bind credentials to the OS user, device, browser build, or hardware."
    )


def _safe_filename(value: str) -> str:
    normalized = "".join(
        char if char.isalnum() or char in {"-", "_"} else "-"
        for char in value.strip()
    ).strip("-_")
    return (normalized or "webfa-profile")[:100]


def _restrict_file_permissions(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _delete_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _require_temp_child(path: Path, root: Path) -> None:
    try:
        if os.path.commonpath([str(path), str(root)]) != str(root):
            raise ProfileBundleFormatError(
                "Profile Bundle upload path is outside the Runtime temporary directory"
            )
    except ValueError as exc:
        raise ProfileBundleFormatError(
            "Profile Bundle upload path is invalid"
        ) from exc


def _require_path_within(path: Path, root: Path) -> None:
    resolved_root = root.resolve()
    resolved_path = path.resolve(strict=False)
    try:
        if os.path.commonpath([str(resolved_path), str(resolved_root)]) != str(
            resolved_root
        ):
            raise ProfileBundleFormatError(
                "Profile Bundle extraction path escaped the target root"
            )
    except ValueError as exc:
        raise ProfileBundleFormatError(
            "Profile Bundle extraction path is invalid"
        ) from exc
