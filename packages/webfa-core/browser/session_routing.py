from __future__ import annotations

import hashlib
import os
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import uuid4

from browser.agent_lease import DEFAULT_LEASE_TTL_SECONDS
from browser.runtime_errors import BrowserRuntimeError
from schemas.browser import BrowserTab
from schemas.profile import BrowserProfile
from schemas.web import (
    WebObserveQuery,
    WebObserveRequest,
    WebOpenResult,
    WebOperationRequest,
    WebOperationResult,
    WebState,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class AgentConnectionContext:
    connection_id: str
    agent_id: str
    current_session_id: str | None = None
    current_profile_id: str | None = None
    authorized_profile_ids: set[str] = field(default_factory=set)
    leased_session_ids: set[str] = field(default_factory=set)
    binding_revision: int = 0
    created_at: datetime = field(default_factory=_utc_now)
    last_seen_at: datetime = field(default_factory=_utc_now)
    expires_at: datetime = field(default_factory=lambda: _utc_now() + timedelta(minutes=30))
    operation_lock: threading.RLock = field(default_factory=threading.RLock, repr=False)


class AgentConnectionRegistry:
    def __init__(
        self,
        *,
        ttl_seconds: int = 1800,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._ttl = timedelta(seconds=max(60, ttl_seconds))
        self._clock = clock or _utc_now
        self._contexts: dict[str, AgentConnectionContext] = {}
        self._lock = threading.RLock()

    def get_or_create(self, *, connection_id: str, agent_id: str) -> AgentConnectionContext:
        normalized_connection = connection_id.strip()
        normalized_agent = agent_id.strip() or "anonymous-mcp"
        if not normalized_connection:
            raise BrowserRuntimeError(
                code="connection_id_required",
                message="Agent connection identity is required",
                recover_hint="Reconnect through the WebFA MCP server",
                http_status=400,
            )
        with self._lock:
            self._prune_locked()
            existing = self._contexts.get(normalized_connection)
            now = self._now()
            if existing is not None:
                if existing.agent_id != normalized_agent:
                    raise BrowserRuntimeError(
                        code="connection_identity_mismatch",
                        message="Agent connection identity changed during an active connection",
                        recover_hint="Create a new MCP connection for the new Agent identity",
                        http_status=409,
                    )
                existing.last_seen_at = now
                existing.expires_at = now + self._ttl
                return existing
            context = AgentConnectionContext(
                connection_id=normalized_connection,
                agent_id=normalized_agent,
                created_at=now,
                last_seen_at=now,
                expires_at=now + self._ttl,
            )
            self._contexts[normalized_connection] = context
            return context

    def get(self, connection_id: str) -> AgentConnectionContext | None:
        with self._lock:
            self._prune_locked()
            return self._contexts.get(connection_id)

    def bind_session(
        self,
        context: AgentConnectionContext,
        *,
        session_id: str,
        profile_id: str,
    ) -> None:
        with self._lock:
            context.current_session_id = session_id
            context.current_profile_id = profile_id
            context.authorized_profile_ids.add(profile_id)
            context.leased_session_ids.add(session_id)
            context.binding_revision += 1
            context.last_seen_at = self._now()
            context.expires_at = context.last_seen_at + self._ttl

    def authorize_profile(self, context: AgentConnectionContext, profile_id: str) -> None:
        with self._lock:
            context.authorized_profile_ids.add(profile_id)
            context.binding_revision += 1

    def unbind_session(self, session_id: str) -> None:
        with self._lock:
            for context in self._contexts.values():
                if session_id in context.leased_session_ids:
                    context.leased_session_ids.discard(session_id)
                    if context.current_session_id == session_id:
                        context.current_session_id = None
                        context.current_profile_id = None
                    context.binding_revision += 1

    def release(self, connection_id: str) -> AgentConnectionContext | None:
        with self._lock:
            return self._contexts.pop(connection_id, None)

    def list(self) -> list[AgentConnectionContext]:
        with self._lock:
            self._prune_locked()
            return list(self._contexts.values())

    def _prune_locked(self) -> None:
        now = self._now()
        for connection_id, context in tuple(self._contexts.items()):
            if context.expires_at <= now:
                self._contexts.pop(connection_id, None)

    def _now(self) -> datetime:
        value = self._clock()
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class AgentProfileGrant:
    grant_id: str
    agent_id: str
    connection_id: str
    profile_id: str
    profile_version: int
    issued_at: datetime
    expires_at: datetime


class AgentProfileGrantManager:
    def __init__(
        self,
        *,
        ttl_seconds: int = 1800,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._ttl = timedelta(seconds=max(60, ttl_seconds))
        self._clock = clock or _utc_now
        self._grants: dict[tuple[str, str], AgentProfileGrant] = {}
        self._lock = threading.RLock()

    def authorize(
        self,
        *,
        profile: BrowserProfile,
        agent_id: str,
        connection_id: str,
    ) -> AgentProfileGrant:
        self._validate_profile_access(profile, agent_id=agent_id)
        key = (connection_id, profile.profile_id)
        with self._lock:
            now = self._now()
            existing = self._grants.get(key)
            if existing is not None and existing.expires_at > now and existing.agent_id == agent_id:
                renewed = AgentProfileGrant(
                    grant_id=existing.grant_id,
                    agent_id=agent_id,
                    connection_id=connection_id,
                    profile_id=profile.profile_id,
                    profile_version=profile.version,
                    issued_at=existing.issued_at,
                    expires_at=now + self._ttl,
                )
                self._grants[key] = renewed
                return renewed
            grant = AgentProfileGrant(
                grant_id=f"pgrant_{uuid4().hex}",
                agent_id=agent_id,
                connection_id=connection_id,
                profile_id=profile.profile_id,
                profile_version=profile.version,
                issued_at=now,
                expires_at=now + self._ttl,
            )
            self._grants[key] = grant
            return grant

    def require(
        self,
        *,
        connection_id: str,
        agent_id: str,
        profile: BrowserProfile,
    ) -> AgentProfileGrant:
        self._validate_profile_access(profile, agent_id=agent_id)
        with self._lock:
            now = self._now()
            key = (connection_id, profile.profile_id)
            grant = self._grants.get(key)
            if grant is None or grant.expires_at <= now or grant.agent_id != agent_id:
                raise BrowserRuntimeError(
                    code="profile_grant_required",
                    message="The current Agent connection is not authorized for this Browser Profile",
                    recover_hint="Open a URL with the target profile_ref to establish an authorized Profile context",
                    http_status=403,
                )
            renewed = AgentProfileGrant(
                grant_id=grant.grant_id,
                agent_id=grant.agent_id,
                connection_id=grant.connection_id,
                profile_id=grant.profile_id,
                profile_version=profile.version,
                issued_at=grant.issued_at,
                expires_at=now + self._ttl,
            )
            self._grants[key] = renewed
            return renewed

    def revoke_connection(self, connection_id: str) -> None:
        with self._lock:
            for key in tuple(self._grants):
                if key[0] == connection_id:
                    self._grants.pop(key, None)

    def _now(self) -> datetime:
        value = self._clock()
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)

    @staticmethod
    def _validate_profile_access(profile: BrowserProfile, *, agent_id: str) -> None:
        if profile.catalog_state != "ready":
            raise BrowserRuntimeError(
                code="profile_unavailable",
                message=f"Browser Profile '{profile.agent_alias}' is not ready",
                recover_hint="Choose an available Browser Profile",
                http_status=409,
            )
        if profile.bound_agent_ids and agent_id not in profile.bound_agent_ids:
            raise BrowserRuntimeError(
                code="profile_access_denied",
                message=f"Agent is not authorized to use Browser Profile '{profile.agent_alias}'",
                recover_hint="Bind this Agent to the Profile in the local Control Center",
                http_status=403,
            )


@dataclass(frozen=True)
class AgentSessionLease:
    lease_id: str
    agent_id: str
    connection_id: str
    session_id: str
    profile_id: str
    runtime_generation: str
    issued_at: datetime
    expires_at: datetime


class AgentSessionLeaseManager:
    def __init__(
        self,
        *,
        ttl_seconds: int | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl_seconds is None:
            raw = os.getenv("WEBFA_AGENT_LEASE_TTL_SECONDS")
            ttl_seconds = int(raw) if raw else DEFAULT_LEASE_TTL_SECONDS
        self._ttl = timedelta(seconds=max(1, ttl_seconds))
        self._clock = clock or _utc_now
        self._leases: dict[str, AgentSessionLease] = {}
        self._lock = threading.RLock()

    def acquire(
        self,
        *,
        agent_id: str,
        connection_id: str,
        session_id: str,
        profile_id: str,
        runtime_generation: str,
    ) -> AgentSessionLease:
        with self._lock:
            now = self._now()
            existing = self._active_locked(session_id, now)
            if existing is not None and existing.connection_id != connection_id:
                raise BrowserRuntimeError(
                    code="session_busy",
                    message=f"Browser Session is controlled by agent '{existing.agent_id}'",
                    recover_hint="Use another Profile or wait for the active Session lease to expire",
                    http_status=409,
                )
            if existing is not None and existing.agent_id != agent_id:
                raise BrowserRuntimeError(
                    code="session_identity_mismatch",
                    message="The active Session lease belongs to another Agent identity",
                    recover_hint="Create a separate Agent connection",
                    http_status=409,
                )
            if existing is not None:
                self._require_binding(existing, profile_id=profile_id, runtime_generation=runtime_generation)
                lease = self._renewed(existing, now=now)
            else:
                lease = AgentSessionLease(
                    lease_id=f"slease_{uuid4().hex}",
                    agent_id=agent_id,
                    connection_id=connection_id,
                    session_id=session_id,
                    profile_id=profile_id,
                    runtime_generation=runtime_generation,
                    issued_at=now,
                    expires_at=now + self._ttl,
                )
            self._leases[session_id] = lease
            return lease

    def require(
        self,
        *,
        agent_id: str,
        connection_id: str,
        session_id: str,
        profile_id: str,
        runtime_generation: str,
    ) -> AgentSessionLease:
        with self._lock:
            now = self._now()
            lease = self._active_locked(session_id, now)
            if lease is None:
                raise BrowserRuntimeError(
                    code="session_lease_required",
                    message="The current Agent connection does not hold the Session lease",
                    recover_hint="Open the target Profile before performing a write operation",
                    http_status=409,
                )
            if lease.agent_id != agent_id or lease.connection_id != connection_id:
                raise BrowserRuntimeError(
                    code="session_busy",
                    message=f"Browser Session is controlled by agent '{lease.agent_id}'",
                    recover_hint="Use another Profile or wait for the active Session lease to expire",
                    http_status=409,
                )
            self._require_binding(lease, profile_id=profile_id, runtime_generation=runtime_generation)
            renewed = self._renewed(lease, now=now)
            self._leases[session_id] = renewed
            return renewed

    def renew_if_owned(
        self,
        *,
        agent_id: str,
        connection_id: str,
        session_id: str,
        profile_id: str,
        runtime_generation: str,
    ) -> AgentSessionLease | None:
        """Renew an active owned lease for read activity without acquiring a free lease."""

        with self._lock:
            now = self._now()
            lease = self._active_locked(session_id, now)
            if lease is None:
                return None
            if lease.agent_id != agent_id or lease.connection_id != connection_id:
                return None
            self._require_binding(lease, profile_id=profile_id, runtime_generation=runtime_generation)
            renewed = self._renewed(lease, now=now)
            self._leases[session_id] = renewed
            return renewed

    def active(self, session_id: str) -> AgentSessionLease | None:
        with self._lock:
            return self._active_locked(session_id, self._now())

    def release_session(self, session_id: str) -> AgentSessionLease | None:
        with self._lock:
            return self._leases.pop(session_id, None)

    def release_connection(self, connection_id: str) -> list[AgentSessionLease]:
        released: list[AgentSessionLease] = []
        with self._lock:
            for session_id, lease in tuple(self._leases.items()):
                if lease.connection_id == connection_id:
                    released.append(self._leases.pop(session_id))
        return released

    def _active_locked(self, session_id: str, now: datetime) -> AgentSessionLease | None:
        lease = self._leases.get(session_id)
        if lease is not None and lease.expires_at <= now:
            self._leases.pop(session_id, None)
            return None
        return lease

    def _require_binding(
        self,
        lease: AgentSessionLease,
        *,
        profile_id: str,
        runtime_generation: str,
    ) -> None:
        if lease.profile_id != profile_id:
            raise BrowserRuntimeError(
                code="session_profile_mismatch",
                message="The Session lease belongs to another Browser Profile",
                recover_hint="Refresh the current Session and Profile binding",
                http_status=409,
            )
        if lease.runtime_generation != runtime_generation:
            raise BrowserRuntimeError(
                code="session_generation_mismatch",
                message="The Session was replaced and the previous lease is no longer valid",
                recover_hint="Call webfa.open_url to enter the current Session generation",
                http_status=409,
            )

    def _renewed(
        self,
        lease: AgentSessionLease,
        *,
        now: datetime,
    ) -> AgentSessionLease:
        return AgentSessionLease(
            lease_id=lease.lease_id,
            agent_id=lease.agent_id,
            connection_id=lease.connection_id,
            session_id=lease.session_id,
            profile_id=lease.profile_id,
            runtime_generation=lease.runtime_generation,
            issued_at=lease.issued_at,
            expires_at=now + self._ttl,
        )

    def _now(self) -> datetime:
        value = self._clock()
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class TabRoute:
    public_id: str
    session_id: str
    profile_id: str
    runtime_generation: str
    local_id: str


@dataclass(frozen=True)
class ObjectRoute:
    public_id: str
    session_id: str
    profile_id: str
    runtime_generation: str
    local_id: str


class GlobalRouteRegistry:
    def __init__(self, *, secret: bytes | None = None) -> None:
        self._secret = secret or secrets.token_bytes(32)
        self._tabs_by_public: dict[str, TabRoute] = {}
        self._tabs_by_local: dict[tuple[str, str, str], TabRoute] = {}
        self._objects_by_public: dict[str, ObjectRoute] = {}
        self._objects_by_local: dict[tuple[str, str, str], ObjectRoute] = {}
        self._lock = threading.RLock()

    def bind_tab(
        self,
        *,
        session_id: str,
        profile_id: str,
        runtime_generation: str,
        local_id: str,
    ) -> TabRoute:
        key = (session_id, runtime_generation, local_id)
        with self._lock:
            existing = self._tabs_by_local.get(key)
            if existing is not None:
                return existing
            public_id = self._public_id("tab", session_id, runtime_generation, local_id)
            route = TabRoute(public_id, session_id, profile_id, runtime_generation, local_id)
            self._tabs_by_local[key] = route
            self._tabs_by_public[public_id] = route
            return route

    def bind_object(
        self,
        *,
        session_id: str,
        profile_id: str,
        runtime_generation: str,
        local_id: str,
    ) -> ObjectRoute:
        key = (session_id, runtime_generation, local_id)
        with self._lock:
            existing = self._objects_by_local.get(key)
            if existing is not None:
                return existing
            public_id = self._public_id("obj", session_id, runtime_generation, local_id)
            route = ObjectRoute(public_id, session_id, profile_id, runtime_generation, local_id)
            self._objects_by_local[key] = route
            self._objects_by_public[public_id] = route
            return route

    def resolve_tab(self, public_id: str) -> TabRoute | None:
        with self._lock:
            return self._tabs_by_public.get(public_id)

    def resolve_object(self, public_id: str) -> ObjectRoute | None:
        with self._lock:
            return self._objects_by_public.get(public_id)

    def project_tab(
        self,
        tab: BrowserTab,
        *,
        session_id: str,
        profile_id: str,
        profile_ref: str,
        runtime_generation: str,
        active: bool,
    ) -> dict[str, object]:
        route = self.bind_tab(
            session_id=session_id,
            profile_id=profile_id,
            runtime_generation=runtime_generation,
            local_id=tab.id,
        )
        return {
            "id": route.public_id,
            "session_id": session_id,
            "profile_id": profile_id,
            "profile_ref": profile_ref,
            "runtime_generation": runtime_generation,
            "url": tab.url,
            "title": tab.title,
            "active": active,
        }

    def project_web_state(
        self,
        state: WebState,
        *,
        profile_id: str,
        runtime_generation: str,
    ) -> WebState:
        data = state.model_dump(mode="python")
        session_id = state.session_id

        def project(local_id: str | None) -> str | None:
            if not local_id:
                return local_id
            return self.bind_object(
                session_id=session_id,
                profile_id=profile_id,
                runtime_generation=runtime_generation,
                local_id=local_id,
            ).public_id

        for item in data.get("outline", []):
            item["object_id"] = project(item.get("object_id"))
        for item in data.get("regions", []):
            item["object_id"] = project(item.get("object_id"))
        relation_single = {
            "parent",
            "belongs_to",
            "owned_by",
            "form",
            "submit_control",
        }
        relation_many = {
            "children",
            "labelled_by",
            "described_by",
            "controls",
            "controlled_by",
            "owns",
            "fields",
            "items",
            "rows",
            "cells",
            "headers",
        }
        for obj in data.get("objects", []):
            obj["id"] = project(obj.get("id"))
            relations = obj.get("relations")
            if isinstance(relations, dict):
                for key in relation_single:
                    relations[key] = project(relations.get(key))
                for key in relation_many:
                    relations[key] = [project(value) for value in relations.get(key, [])]
        changes = data.get("changes")
        if isinstance(changes, dict):
            for obj in changes.get("added", []):
                obj["id"] = project(obj.get("id"))
            for update in changes.get("updated", []):
                update["id"] = project(update.get("id"))
            changes["removed"] = [project(value) for value in changes.get("removed", [])]
            changes["invalidated"] = [project(value) for value in changes.get("invalidated", [])]
        takeover = data.get("takeover")
        if isinstance(takeover, dict) and takeover.get("target"):
            takeover["target"] = project(takeover["target"])
        return WebState.model_validate(data)

    def project_open_result(
        self,
        result: WebOpenResult,
        *,
        profile_id: str,
        runtime_generation: str,
    ) -> WebOpenResult:
        return result.model_copy(
            update={
                "state": self.project_web_state(
                    result.state,
                    profile_id=profile_id,
                    runtime_generation=runtime_generation,
                )
            }
        )

    def project_operation_result(
        self,
        result: WebOperationResult,
        *,
        profile_id: str,
        runtime_generation: str,
    ) -> WebOperationResult:
        target = self.bind_object(
            session_id=result.state.session_id,
            profile_id=profile_id,
            runtime_generation=runtime_generation,
            local_id=result.target,
        ).public_id
        return result.model_copy(
            update={
                "target": target,
                "state": self.project_web_state(
                    result.state,
                    profile_id=profile_id,
                    runtime_generation=runtime_generation,
                ),
            }
        )

    def localize_observe_request(
        self,
        request: WebObserveRequest,
        *,
        session_id: str,
        runtime_generation: str,
    ) -> WebObserveRequest:
        data = request.model_dump(mode="python")
        if request.target:
            data["target"] = self._require_local_object(
                request.target,
                session_id=session_id,
                runtime_generation=runtime_generation,
            )
        query = data.get("query")
        if isinstance(query, dict):
            for key in ("id", "within"):
                value = query.get(key)
                if value:
                    query[key] = self._require_local_object(
                        value,
                        session_id=session_id,
                        runtime_generation=runtime_generation,
                    )
        return WebObserveRequest.model_validate(data)

    def localize_operation_request(
        self,
        request: WebOperationRequest,
        *,
        session_id: str,
        runtime_generation: str,
    ) -> WebOperationRequest:
        data = request.model_dump(mode="python")
        data["target"] = self._require_local_object(
            request.target,
            session_id=session_id,
            runtime_generation=runtime_generation,
        )
        return WebOperationRequest.model_validate(data)

    def invalidate_session(self, session_id: str) -> None:
        with self._lock:
            for public_id, route in tuple(self._tabs_by_public.items()):
                if route.session_id == session_id:
                    self._tabs_by_public.pop(public_id, None)
                    self._tabs_by_local.pop((route.session_id, route.runtime_generation, route.local_id), None)
            for public_id, route in tuple(self._objects_by_public.items()):
                if route.session_id == session_id:
                    self._objects_by_public.pop(public_id, None)
                    self._objects_by_local.pop((route.session_id, route.runtime_generation, route.local_id), None)

    def _require_local_object(
        self,
        value: str,
        *,
        session_id: str,
        runtime_generation: str,
    ) -> str:
        route = self.resolve_object(value)
        if route is None:
            # Compatibility for internal callers that still use Session-local IDs.
            return value
        if route.session_id != session_id or route.runtime_generation != runtime_generation:
            raise BrowserRuntimeError(
                code="object_session_mismatch",
                message="WebObject belongs to another Browser Session or an expired Session generation",
                recover_hint="Switch to the correct tab and call webfa.observe again",
                http_status=409,
            )
        return route.local_id

    def _public_id(self, kind: str, session_id: str, generation: str, local_id: str) -> str:
        digest = hashlib.sha256(
            self._secret + b"\0" + kind.encode() + b"\0" + session_id.encode() + b"\0" + generation.encode() + b"\0" + local_id.encode()
        ).hexdigest()[:28]
        return f"{kind}r_{digest}"
