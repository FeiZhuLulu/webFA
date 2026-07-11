from __future__ import annotations

import base64
import binascii
import errno
import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Callable
from urllib.parse import urlparse
from uuid import uuid4

from schemas.safety import LocalResourceGrant, LocalResourceGrantState, ResourceOwner
from storage.file_store import ensure_webfa_data_dir


MAX_LOCAL_RESOURCE_BYTES = 20 * 1024 * 1024
STALE_RESOURCE_SESSION_SECONDS = 86_700
Clock = Callable[[], datetime]


class LocalResourceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class LocalResourceAuthorization:
    resource_ref: str
    path: Path
    grant: LocalResourceGrant


@dataclass
class _ManagedLocalResource:
    grant: LocalResourceGrant
    path: Path
    size_bytes: int
    created_at: datetime
    remaining_uses: int
    revoked: bool = False


class LocalResourceBroker:
    """Session-local broker for scoped, opaque local resource references.

    The Agent never receives the backing path. The Visualizer copies user-selected
    bytes into a WebFA-managed directory and receives only a resource_ref.
    """

    def __init__(self, *, clock: Clock | None = None, resource_dir: Path | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        if resource_dir is None:
            data_dir = Path(ensure_webfa_data_dir()["data_dir"])
            resource_dir = data_dir / "resources"
        self._resource_root = resource_dir.resolve()
        self._resource_root.mkdir(parents=True, exist_ok=True)
        self._purge_orphaned_session_resources()
        self._resource_dir = (
            self._resource_root / f"session_{os.getpid()}_{uuid4().hex}"
        ).resolve()
        self._resource_dir.mkdir(parents=True, exist_ok=False)
        self._resources: dict[str, _ManagedLocalResource] = {}
        self._lock = RLock()

    def register_base64(
        self,
        *,
        display_name: str,
        content_base64: str,
        owner: ResourceOwner,
        purpose: str,
        allowed_origins: list[str],
        bound_agent_ids: list[str] | None = None,
        bound_profile_ids: list[str] | None = None,
        expires_in_seconds: int | None = 3600,
        max_uses: int = 1,
    ) -> LocalResourceGrantState:
        try:
            content = base64.b64decode(content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise LocalResourceError("invalid_resource_content", "resource content must be valid base64") from exc
        return self.register_bytes(
            display_name=display_name,
            content=content,
            owner=owner,
            purpose=purpose,
            allowed_origins=allowed_origins,
            bound_agent_ids=bound_agent_ids,
            bound_profile_ids=bound_profile_ids,
            expires_in_seconds=expires_in_seconds,
            max_uses=max_uses,
        )

    def register_bytes(
        self,
        *,
        display_name: str,
        content: bytes,
        owner: ResourceOwner,
        purpose: str,
        allowed_origins: list[str],
        bound_agent_ids: list[str] | None = None,
        bound_profile_ids: list[str] | None = None,
        expires_in_seconds: int | None = 3600,
        max_uses: int = 1,
    ) -> LocalResourceGrantState:
        safe_name = _safe_display_name(display_name)
        if not content:
            raise LocalResourceError("empty_resource", "resource content cannot be empty")
        if len(content) > MAX_LOCAL_RESOURCE_BYTES:
            raise LocalResourceError(
                "resource_too_large",
                f"resource exceeds the {MAX_LOCAL_RESOURCE_BYTES} byte limit",
            )
        normalized_origins = [_normalize_origin(value) for value in allowed_origins]
        if not normalized_origins or any(not value for value in normalized_origins):
            raise LocalResourceError("invalid_resource_origin", "at least one valid allowed origin is required")
        if len(set(normalized_origins)) != len(normalized_origins):
            raise LocalResourceError("duplicate_resource_origin", "allowed origins must be unique")
        if not purpose.strip():
            raise LocalResourceError("invalid_resource_purpose", "resource purpose is required")
        if max_uses < 1 or max_uses > 10_000:
            raise LocalResourceError("invalid_resource_use_count", "max_uses must be between 1 and 10000")
        if expires_in_seconds is not None and not 1 <= expires_in_seconds <= 86_400:
            raise LocalResourceError("invalid_resource_expiry", "expires_in_seconds must be between 1 and 86400")

        now = self._now()
        resource_ref = f"resource_{uuid4().hex}"
        backing_dir = (self._resource_dir / resource_ref).resolve()
        backing_path = (backing_dir / safe_name).resolve()
        if self._resource_dir not in backing_dir.parents or backing_dir not in backing_path.parents:
            raise LocalResourceError("invalid_resource_name", "resource name is invalid")
        backing_dir.mkdir(parents=True, exist_ok=False)
        backing_path.write_bytes(content)
        expires_at = now + timedelta(seconds=expires_in_seconds) if expires_in_seconds is not None else None
        grant = LocalResourceGrant(
            resource_ref=resource_ref,
            display_name=safe_name,
            owner=owner,
            purpose=purpose.strip(),
            allowed_origins=normalized_origins,
            bound_agent_ids=_unique_non_empty(bound_agent_ids or []),
            bound_profile_ids=_unique_non_empty(bound_profile_ids or []),
            expires_at=expires_at,
            max_uses=max_uses,
        )
        managed = _ManagedLocalResource(
            grant=grant,
            path=backing_path,
            size_bytes=len(content),
            created_at=now,
            remaining_uses=max_uses,
        )
        with self._lock:
            self._resources[resource_ref] = managed
        return self._state(managed)

    def authorize(
        self,
        resource_ref: str,
        *,
        agent_id: str,
        profile_id: str,
        origin: str,
        purpose: str | None = None,
    ) -> LocalResourceAuthorization:
        with self._lock:
            managed = self._require(resource_ref)
            status = self._status(managed)
            if status != "active":
                raise LocalResourceError(
                    f"resource_{status}",
                    f"local resource grant is {status}",
                )
            normalized_origin = _normalize_origin(origin)
            if normalized_origin not in managed.grant.allowed_origins:
                raise LocalResourceError(
                    "resource_origin_mismatch",
                    "current origin is outside the local resource grant scope",
                )
            if managed.grant.bound_agent_ids and agent_id not in managed.grant.bound_agent_ids:
                raise LocalResourceError(
                    "resource_agent_mismatch",
                    "active Agent is outside the local resource grant scope",
                )
            if managed.grant.bound_profile_ids and profile_id not in managed.grant.bound_profile_ids:
                raise LocalResourceError(
                    "resource_profile_mismatch",
                    "active profile is outside the local resource grant scope",
                )
            if purpose is not None and purpose.strip() != managed.grant.purpose:
                raise LocalResourceError(
                    "resource_purpose_mismatch",
                    "operation purpose does not match the local resource grant",
                )
            if not managed.path.is_file():
                raise LocalResourceError("resource_missing", "local resource backing data is unavailable")
            return LocalResourceAuthorization(
                resource_ref=resource_ref,
                path=managed.path,
                grant=managed.grant.model_copy(deep=True),
            )

    def consume(self, resource_ref: str) -> LocalResourceGrantState:
        with self._lock:
            managed = self._require(resource_ref)
            if self._status(managed) != "active":
                return self._state(managed)
            managed.remaining_uses = max(0, managed.remaining_uses - 1)
            return self._state(managed)

    def revoke(self, resource_ref: str) -> LocalResourceGrantState:
        with self._lock:
            managed = self._require(resource_ref)
            managed.revoked = True
            self._delete_backing_data(managed)
            return self._state(managed)

    def list(self) -> list[LocalResourceGrantState]:
        with self._lock:
            return [
                self._state(item)
                for item in sorted(self._resources.values(), key=lambda value: value.created_at, reverse=True)
            ]

    def close(self) -> None:
        with self._lock:
            for managed in self._resources.values():
                self._delete_backing_data(managed)
            shutil.rmtree(self._resource_dir, ignore_errors=True)

    def _require(self, resource_ref: str) -> _ManagedLocalResource:
        managed = self._resources.get(resource_ref)
        if managed is None:
            raise LocalResourceError("resource_not_found", "local resource grant was not found")
        return managed

    def _state(self, managed: _ManagedLocalResource) -> LocalResourceGrantState:
        return LocalResourceGrantState(
            grant=managed.grant.model_copy(deep=True),
            status=self._status(managed),
            remaining_uses=managed.remaining_uses,
            size_bytes=managed.size_bytes,
            created_at=managed.created_at,
        )

    def _status(self, managed: _ManagedLocalResource) -> str:
        if managed.revoked:
            return "revoked"
        expires_at = managed.grant.expires_at
        if expires_at is not None and _as_utc(expires_at) <= self._now():
            self._delete_backing_data(managed)
            return "expired"
        if managed.remaining_uses <= 0:
            return "consumed"
        return "active"

    def _now(self) -> datetime:
        return _as_utc(self._clock())

    def _delete_backing_data(self, managed: _ManagedLocalResource) -> None:
        try:
            managed.path.unlink(missing_ok=True)
            managed.path.parent.rmdir()
        except OSError:
            pass

    def _purge_orphaned_session_resources(self) -> None:
        cutoff = time.time() - STALE_RESOURCE_SESSION_SECONDS
        session_candidates = list(self._resource_root.glob("session_*"))
        legacy_candidates = list(self._resource_root.glob("resource_*"))
        for candidate in session_candidates:
            try:
                if not candidate.is_dir():
                    continue
                owner_pid = _session_owner_pid(candidate.name)
                owner_dead = owner_pid is not None and not _process_is_alive(owner_pid)
                stale = candidate.stat().st_mtime <= cutoff
            except OSError:
                continue
            if owner_dead or stale:
                shutil.rmtree(candidate, ignore_errors=True)
        for candidate in legacy_candidates:
            try:
                stale = candidate.is_dir() and candidate.stat().st_mtime <= cutoff
            except OSError:
                continue
            if stale:
                shutil.rmtree(candidate, ignore_errors=True)


def _session_owner_pid(name: str) -> int | None:
    parts = name.split("_", 2)
    if len(parts) < 3 or parts[0] != "session":
        return None
    try:
        pid = int(parts[1])
    except ValueError:
        return None
    return pid if pid > 0 else None


def _process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError as exc:
        if exc.errno in {errno.EPERM, errno.EACCES}:
            return True
        return False
    return True


def _safe_display_name(value: str) -> str:
    normalized = Path(value.strip()).name
    if not normalized or normalized in {".", ".."}:
        raise LocalResourceError("invalid_resource_name", "resource display name is invalid")
    return normalized[:500]


def _normalize_origin(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
    if parsed.scheme == "file":
        return "file://"
    return ""


def _unique_non_empty(values: list[str]) -> list[str]:
    normalized = [value.strip() for value in values if value and value.strip()]
    return list(dict.fromkeys(normalized))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
