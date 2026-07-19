from __future__ import annotations

import threading
from typing import Any
from uuid import uuid4

from browser.agent_lease import normalize_agent_id
from browser.config import resolve_browser_runtime_config
from browser.driver_factory import create_default_driver_factory
from browser.profile_repository import BrowserSessionRepository, ProfileRepository
from browser.profile_storage import ProfileStorageManager
from browser.runtime import BrowserSessionRuntime, DriverFactory
from browser.runtime_errors import BrowserRuntimeError
from browser.session_manager import ActiveBrowserSession, SessionManager
from browser.session_routing import (
    AgentConnectionContext,
    AgentConnectionRegistry,
    AgentProfileGrantManager,
    AgentSessionLeaseManager,
    GlobalRouteRegistry,
)
from browser.web_observe import WebObserveResult
from schemas.browser import BrowserActionRequest, BrowserActionResult, BrowserState, BrowserTab
from schemas.profile import BrowserProfile
from schemas.web import (
    WebObserveRequest,
    WebOpenRequest,
    WebOpenResult,
    WebOperationRequest,
    WebOperationResult,
    WebState,
)
from storage.db import init_db


class BrowserRuntimeSupervisor:
    """Application-level router for isolated Profile and Session runtimes.

    The Supervisor owns no page state. Each active Profile has one dedicated
    BrowserSessionRuntime and one process lock. Agent-facing requests are routed
    through connection, Profile-grant, Session-lease, and global identity layers.
    """

    def __init__(
        self,
        headless: bool | None = None,
        driver_factory: DriverFactory | None = None,
        *,
        profile_repository: ProfileRepository | None = None,
        session_repository: BrowserSessionRepository | None = None,
        storage_manager: ProfileStorageManager | None = None,
        default_profile_ref: str = "default",
        runtime_instance_id: str | None = None,
        initialize_storage: bool = True,
        connection_registry: AgentConnectionRegistry | None = None,
        profile_grants: AgentProfileGrantManager | None = None,
        session_leases: AgentSessionLeaseManager | None = None,
        route_registry: GlobalRouteRegistry | None = None,
        session_manager: SessionManager | None = None,
    ) -> None:
        if initialize_storage:
            init_db()
        config = resolve_browser_runtime_config(headless=headless)
        self._driver_name = config.driver_name
        self._headless = config.headless
        self._custom_driver_factory = driver_factory
        self._profile_repository = profile_repository or ProfileRepository()
        self._session_repository = session_repository or BrowserSessionRepository()
        self._storage_manager = storage_manager or ProfileStorageManager()
        self._default_profile_ref = default_profile_ref
        self._runtime_instance_id = runtime_instance_id or f"runtime_{uuid4().hex}"
        self._connections = connection_registry or AgentConnectionRegistry()
        self._profile_grants = profile_grants or AgentProfileGrantManager()
        self._session_leases = session_leases or AgentSessionLeaseManager()
        self._routes = route_registry or GlobalRouteRegistry()
        self._session_manager = session_manager or SessionManager()
        self._closed = False
        self._lock = threading.RLock()

    @property
    def runtime_instance_id(self) -> str:
        return self._runtime_instance_id

    @property
    def current_session_id(self) -> str | None:
        return self._session_manager.default_session_id

    @property
    def current_profile_id(self) -> str | None:
        entry = self._session_manager.get(self._session_manager.default_session_id)
        return entry.profile.profile_id if entry is not None else None

    @property
    def profile_repository(self) -> ProfileRepository:
        return self._profile_repository

    @property
    def session_repository(self) -> BrowserSessionRepository:
        return self._session_repository

    @property
    def route_registry(self) -> GlobalRouteRegistry:
        return self._routes

    def current_session_runtime(self, connection_id: str | None = None) -> BrowserSessionRuntime:
        if connection_id:
            context = self._connections.get(connection_id)
            if context is not None and context.current_session_id is not None:
                return self.get_session_runtime(context.current_session_id)
        session_id = self._session_manager.default_session_id
        if session_id is None:
            return self._ensure_compat_runtime(agent_id="anonymous-mcp")
        return self.get_session_runtime(session_id)

    def get_session_runtime(self, session_id: str) -> BrowserSessionRuntime:
        entry = self._session_manager.get(session_id)
        if entry is None:
            raise BrowserRuntimeError(
                code="session_not_found",
                message="Browser Session was not found or is no longer active",
                recover_hint="Open a URL in the target Browser Profile to create a new Session",
                http_status=404,
            )
        return entry.runtime

    def find_control_session_runtime(
        self,
        profile_ref: str | None = None,
    ) -> BrowserSessionRuntime | None:
        """Return an existing Session runtime without acquiring Agent authority."""
        if profile_ref is None:
            entry = self._session_manager.get(self._session_manager.default_session_id)
        else:
            profile = self._profile_repository.get_profile(profile_ref)
            entry = self._session_manager.get_by_profile(profile.profile_id)
        return entry.runtime if entry is not None else None

    def ensure_control_session_runtime(
        self,
        profile_ref: str | None = None,
    ) -> BrowserSessionRuntime:
        """Create or resolve a Session for the protected human control plane.

        This path deliberately creates no Agent connection, Profile Grant, or
        Session write lease. It only exposes Session-scoped management state to
        the separately authenticated local control API.
        """
        if profile_ref is None:
            existing = self._session_manager.get(self._session_manager.default_session_id)
            if existing is not None:
                return existing.runtime
            profile_ref = "default"
        profile = (
            self._profile_repository.ensure_default_profile()
            if profile_ref == "default"
            else self._profile_repository.get_profile(profile_ref)
        )
        existing = self._session_manager.get_by_profile(profile.profile_id)
        if existing is not None:
            return existing.runtime
        return self._ensure_session(
            profile,
            created_by_agent_id=None,
            created_by_connection_id="local-control",
        ).runtime

    def get_session_binding(self, session_id: str) -> dict[str, str]:
        entry = self._session_manager.get(session_id)
        if entry is None:
            raise BrowserRuntimeError(
                code="session_not_found",
                message="Browser Session was not found or is no longer active",
                recover_hint="Refresh the Control Center Session list",
                http_status=404,
            )
        return {
            "session_id": entry.session_id,
            "profile_id": entry.profile.profile_id,
            "profile_ref": entry.profile.agent_alias,
            "runtime_generation": entry.runtime_generation,
        }

    def resolve_monitor_session(self, session_id: str | None = None) -> ActiveBrowserSession:
        requested = (session_id or "").strip()
        if requested and requested != "default":
            entry = self._session_manager.get(requested)
        else:
            entry = self._session_manager.get(self._session_manager.default_session_id)
            entries = self._session_manager.values()
            if entry is None and len(entries) == 1:
                entry = entries[0]
        if entry is None:
            raise BrowserRuntimeError(
                code="monitor_session_not_found",
                message="The requested Browser Session is not active",
                recover_hint="Refresh the Control Center Session list and open an active Session",
                http_status=404,
            )
        return entry

    def list_session_summaries(self) -> list[dict[str, object]]:
        entries = self._session_manager.values()
        summaries: list[dict[str, object]] = []
        for entry in entries:
            status = entry.runtime.status()
            status = {**status, **self._session_lease_status(entry)}
            summaries.append(
                {
                    "session_id": entry.session_id,
                    "profile_id": entry.profile.profile_id,
                    "profile_ref": entry.profile.agent_alias,
                    "profile_display_name": entry.profile.display_name,
                    "runtime_generation": entry.runtime_generation,
                    "host_status": status.get("host_status"),
                    "active_agent_id": status.get("active_agent_id"),
                    "human_control_active": entry.runtime.human_control_status() is not None,
                    "url": entry.runtime.monitor_snapshot().get("url", "about:blank")
                    if status.get("host_status") not in {"not_started", "closed"}
                    else "about:blank",
                }
            )
        return summaries

    # ------------------------------------------------------------------
    # Agent-facing P10/P12 surface
    # ------------------------------------------------------------------

    def open_web(
        self,
        request: WebOpenRequest,
        agent_id: str | None = None,
        connection_id: str | None = None,
    ) -> WebOpenResult:
        context = self._connection(agent_id=agent_id, connection_id=connection_id)
        with context.operation_lock:
            profile_ref = request.profile_ref or context.current_profile_id or self._default_profile_ref
            entry = self._enter_profile(context, profile_ref=profile_ref, require_write=True)
            result = entry.runtime.open_web(
                request,
                agent_id=context.agent_id,
                connection_id=context.connection_id,
            )
            self._bind_tabs(entry)
            return result.model_copy(
                update={"state": self._project_web_state(entry, result.state)}
            )

    def observe_web(
        self,
        request: WebObserveRequest | None = None,
        *,
        agent_id: str | None = None,
        connection_id: str | None = None,
    ):
        context = self._connection(agent_id=agent_id, connection_id=connection_id)
        with context.operation_lock:
            entry = self._current_entry(context, create_default=True)
            self._renew_session_if_owned(context, entry)
            localized = self._routes.localize_observe_request(
                request or WebObserveRequest(),
                session_id=entry.session_id,
                runtime_generation=entry.runtime_generation,
            )
            result = entry.runtime.observe_web(
                localized,
                agent_id=context.agent_id,
                connection_id=context.connection_id,
            )
            return WebObserveResult(
                state=self._project_web_state(entry, result.state),
                debug_provenance=result.debug_provenance,
            )

    def act_web(
        self,
        request: WebOperationRequest,
        agent_id: str | None = None,
        connection_id: str | None = None,
    ) -> WebOperationResult:
        context = self._connection(agent_id=agent_id, connection_id=connection_id)
        with context.operation_lock:
            entry = self._current_entry(context, create_default=False)
            self._require_session_write(context, entry)
            localized = self._routes.localize_operation_request(
                request,
                session_id=entry.session_id,
                runtime_generation=entry.runtime_generation,
            )
            result = entry.runtime.act_web(
                localized,
                agent_id=context.agent_id,
                connection_id=context.connection_id,
            )
            self._bind_tabs(entry)
            projected = self._routes.project_operation_result(
                result,
                profile_id=entry.profile.profile_id,
                runtime_generation=entry.runtime_generation,
            )
            return projected.model_copy(
                update={"state": self._with_session_lease_agent(entry, projected.state)}
            )

    def get_tabs(
        self,
        *,
        agent_id: str | None = None,
        connection_id: str | None = None,
    ) -> dict[str, object]:
        context = self._connection(agent_id=agent_id, connection_id=connection_id)
        with context.operation_lock:
            if not context.leased_session_ids:
                self._enter_profile(context, profile_ref=self._default_profile_ref, require_write=True)
            result: list[dict[str, object]] = []
            for session_id in sorted(context.leased_session_ids):
                entry = self._session_manager.get(session_id)
                if entry is None:
                    continue
                self._require_profile_grant(context, entry)
                self._renew_session_if_owned(context, entry)
                local_tabs = entry.runtime.tabs()
                for tab in local_tabs:
                    result.append(
                        self._routes.project_tab(
                            tab,
                            session_id=entry.session_id,
                            profile_id=entry.profile.profile_id,
                            profile_ref=entry.profile.agent_alias,
                            runtime_generation=entry.runtime_generation,
                            active=(
                                context.current_session_id == entry.session_id and tab.active
                            ),
                        )
                    )
            return {
                "tabs": result,
                "current_session_id": context.current_session_id,
                "current_profile_id": context.current_profile_id,
                "binding_revision": context.binding_revision,
            }

    def switch_tab_for_connection(
        self,
        tab_id: str,
        *,
        agent_id: str | None = None,
        connection_id: str | None = None,
    ) -> WebState:
        context = self._connection(agent_id=agent_id, connection_id=connection_id)
        with context.operation_lock:
            route = self._routes.resolve_tab(tab_id)
            if route is None:
                entry = self._current_entry(context, create_default=False)
                self._require_session_write(context, entry)
                local_tab_id = tab_id
            else:
                entry = self._session_manager.get(route.session_id)
                if entry is None or entry.runtime_generation != route.runtime_generation:
                    raise BrowserRuntimeError(
                        code="tab_session_expired",
                        message="Browser tab belongs to a closed or replaced Session",
                        recover_hint="Call webfa.get_tabs and choose a current tab",
                        http_status=409,
                    )
                self._require_profile_grant(context, entry)
                self._acquire_session_write(context, entry)
                self._connections.bind_session(
                    context,
                    session_id=entry.session_id,
                    profile_id=entry.profile.profile_id,
                )
                local_tab_id = route.local_id
            state = entry.runtime.switch_tab(local_tab_id, agent_id=context.agent_id)
            web_state = entry.runtime.observe_web(
                WebObserveRequest(mode="page"),
                agent_id=context.agent_id,
                connection_id=context.connection_id,
            ).state
            return self._project_web_state(entry, web_state)

    def release_connection(self, connection_id: str) -> None:
        context = self._connections.release(connection_id)
        self._profile_grants.revoke_connection(connection_id)
        self._session_leases.release_connection(connection_id)
        if context is not None:
            for session_id in context.leased_session_ids:
                entry = self._session_manager.get(session_id)
                if entry is not None:
                    entry.runtime.release_human_control_connection(connection_id)

    # ------------------------------------------------------------------
    # Compatibility facade for existing local tests and legacy REST paths.
    # ------------------------------------------------------------------

    def open(self, url: str, agent_id: str | None = None) -> BrowserActionResult:
        runtime = self._ensure_compat_runtime(agent_id=agent_id)
        return runtime.open(url, agent_id=agent_id)

    def observe(self) -> BrowserState:
        return self.current_session_runtime().observe()

    def act(self, request: BrowserActionRequest, agent_id: str | None = None) -> BrowserActionResult:
        runtime = self._ensure_compat_runtime(agent_id=agent_id)
        return runtime.act(request, agent_id=agent_id)

    def tabs(self) -> list[BrowserTab]:
        return self.current_session_runtime().tabs()

    def switch_tab(self, tab_id: str, agent_id: str | None = None) -> BrowserState:
        runtime = self._ensure_compat_runtime(agent_id=agent_id)
        return runtime.switch_tab(tab_id, agent_id=agent_id)

    def monitor_snapshot(self, session_id: str | None = None) -> dict[str, Any]:
        entry = self.resolve_monitor_session(session_id)
        snapshot = entry.runtime.monitor_snapshot()
        return {**snapshot, **self._session_lease_status(entry)}

    def status(self, connection_id: str | None = None) -> dict[str, Any]:
        runtime: BrowserSessionRuntime | None = None
        entry: ActiveBrowserSession | None = None
        if connection_id:
            context = self._connections.get(connection_id)
            if context is not None and context.current_session_id:
                entry = self._session_manager.get(context.current_session_id)
                runtime = entry.runtime if entry is not None else None
        active_count = self._session_manager.count()
        if runtime is None:
            entry = self._session_manager.get(self._session_manager.default_session_id)
            runtime = entry.runtime if entry is not None else None
        if runtime is None:
            return {
                "runtime_instance_id": self._runtime_instance_id,
                "session_id": None,
                "profile_id": None,
                "runtime_generation": None,
                "supervisor_lifecycle": "inactive",
                "active_session_count": 0,
                "selected_driver": self._driver_name,
                "headless": self._headless,
                "host_status": "not_started",
                "last_error": None,
            }
        status = runtime.status()
        return {
            **status,
            **(self._session_lease_status(entry) if entry is not None else {}),
            "runtime_instance_id": self._runtime_instance_id,
            "runtime_generation": runtime.runtime_generation,
            "supervisor_lifecycle": "active",
            "active_session_count": active_count,
        }

    def close_session(self, session_id: str, *, reason: str = "supervisor_close") -> None:
        with self._lock:
            entry = self._session_manager.get(session_id)
            if entry is None:
                return
            try:
                entry.runtime.close()
            finally:
                self._finalize_session(entry, lifecycle="closed", reason=reason)

    def close_profile_session(
        self,
        profile_ref: str,
        *,
        reason: str = "profile_control_close",
    ) -> str | None:
        profile = self._profile_repository.get_profile(profile_ref)
        entry = self._session_manager.get_by_profile(profile.profile_id)
        if entry is None:
            return None
        session_id = entry.session_id
        self.close_session(session_id, reason=reason)
        return session_id

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            entries = self._session_manager.values()
        for entry in entries:
            lifecycle = "closed"
            reason = "supervisor_close"
            try:
                entry.runtime.close()
            except Exception as exc:
                lifecycle = "crashed"
                reason = f"supervisor close failed: {exc}"[:500]
                try:
                    self._profile_repository.record_runtime_event(
                        profile_id=entry.profile.profile_id,
                        session_id=entry.session_id,
                        event_type="session_close_failed",
                        safe_metadata={"reason": reason},
                    )
                except Exception:
                    pass
            finally:
                try:
                    self._finalize_session(entry, lifecycle=lifecycle, reason=reason)
                except Exception:
                    # Continue closing the remaining independent Profile Sessions.
                    pass

    def __getattr__(self, name: str):
        if name.startswith("__"):
            raise AttributeError(name)
        runtime = self.current_session_runtime()
        return getattr(runtime, name)

    # ------------------------------------------------------------------
    # Internal routing and lifecycle.
    # ------------------------------------------------------------------

    def _connection(
        self,
        *,
        agent_id: str | None,
        connection_id: str | None,
    ) -> AgentConnectionContext:
        normalized_agent = normalize_agent_id(agent_id)
        normalized_connection = (connection_id or f"compat:{normalized_agent}").strip()
        return self._connections.get_or_create(
            connection_id=normalized_connection,
            agent_id=normalized_agent,
        )

    def _current_entry(
        self,
        context: AgentConnectionContext,
        *,
        create_default: bool,
    ) -> ActiveBrowserSession:
        if context.current_session_id is not None:
            entry = self._session_manager.get(context.current_session_id)
            if entry is not None:
                self._require_profile_grant(context, entry)
                return entry
        if create_default:
            return self._enter_profile(
                context,
                profile_ref=self._default_profile_ref,
                require_write=False,
            )
        raise BrowserRuntimeError(
            code="session_context_required",
            message="The Agent connection has no current Browser Session",
            recover_hint="Call webfa.open_url before acting",
            http_status=409,
        )

    def _enter_profile(
        self,
        context: AgentConnectionContext,
        *,
        profile_ref: str,
        require_write: bool,
    ) -> ActiveBrowserSession:
        profile = (
            self._profile_repository.ensure_default_profile()
            if profile_ref == "default"
            else self._profile_repository.get_profile(profile_ref)
        )
        self._profile_grants.authorize(
            profile=profile,
            agent_id=context.agent_id,
            connection_id=context.connection_id,
        )
        self._connections.authorize_profile(context, profile.profile_id)
        entry = self._ensure_session(
            profile,
            created_by_agent_id=context.agent_id,
            created_by_connection_id=context.connection_id,
        )
        if require_write:
            self._acquire_session_write(context, entry)
        self._connections.bind_session(
            context,
            session_id=entry.session_id,
            profile_id=entry.profile.profile_id,
        )
        return entry

    def _require_session_write(
        self,
        context: AgentConnectionContext,
        entry: ActiveBrowserSession,
    ) -> None:
        self._session_leases.require(
            agent_id=context.agent_id,
            connection_id=context.connection_id,
            session_id=entry.session_id,
            profile_id=entry.profile.profile_id,
            runtime_generation=entry.runtime_generation,
        )

    def _require_profile_grant(
        self,
        context: AgentConnectionContext,
        entry: ActiveBrowserSession,
    ) -> None:
        current_profile = self._profile_repository.get_profile(entry.profile.profile_id)
        self._profile_grants.require(
            connection_id=context.connection_id,
            agent_id=context.agent_id,
            profile=current_profile,
        )

    def _renew_session_if_owned(
        self,
        context: AgentConnectionContext,
        entry: ActiveBrowserSession,
    ) -> None:
        self._session_leases.renew_if_owned(
            agent_id=context.agent_id,
            connection_id=context.connection_id,
            session_id=entry.session_id,
            profile_id=entry.profile.profile_id,
            runtime_generation=entry.runtime_generation,
        )

    def _acquire_session_write(
        self,
        context: AgentConnectionContext,
        entry: ActiveBrowserSession,
    ) -> None:
        self._session_leases.acquire(
            agent_id=context.agent_id,
            connection_id=context.connection_id,
            session_id=entry.session_id,
            profile_id=entry.profile.profile_id,
            runtime_generation=entry.runtime_generation,
        )

    def _ensure_session(
        self,
        profile: BrowserProfile,
        *,
        created_by_agent_id: str | None,
        created_by_connection_id: str | None,
    ) -> ActiveBrowserSession:
        with self._lock:
            if self._closed:
                raise RuntimeError("browser runtime supervisor is closed")
            existing = self._session_manager.get_by_profile(profile.profile_id)
            if existing is not None:
                return existing

            if profile.profile_id == "default":
                self._storage_manager.migrate_legacy_default_profile()
            session_id = f"session_{uuid4().hex}"
            generation = f"generation_{uuid4().hex}"
            process_lock = self._storage_manager.acquire_process_lock(
                profile,
                runtime_instance_id=self._runtime_instance_id,
                runtime_generation=generation,
                session_id=session_id,
            )
            try:
                self._session_repository.interrupt_nonterminal_sessions(
                    profile_id=profile.profile_id
                )
                launch_spec = self._storage_manager.launch_spec(
                    profile,
                    headless=self._headless,
                    runtime_instance_id=self._runtime_instance_id,
                    runtime_generation=generation,
                )
                driver_factory = self._custom_driver_factory or create_default_driver_factory(
                    self._driver_name,
                    self._headless,
                    launch_spec,
                )
                self._session_repository.create_session(
                    session_id=session_id,
                    profile_id=profile.profile_id,
                    runtime_generation=generation,
                    created_by_agent_id=created_by_agent_id,
                    created_by_connection_id=created_by_connection_id,
                )
                runtime = BrowserSessionRuntime(
                    headless=self._headless,
                    driver_factory=driver_factory,
                    session_id=session_id,
                    profile_id=profile.profile_id,
                    runtime_generation=generation,
                    profile_repository=self._profile_repository,
                    session_repository=self._session_repository,
                    terminal_callback=lambda lifecycle, reason, sid=session_id: self._on_session_terminal(
                        sid, lifecycle, reason
                    ),
                )
                entry = ActiveBrowserSession(
                    session_id=session_id,
                    profile=profile,
                    runtime_generation=generation,
                    runtime=runtime,
                    process_lock=process_lock,
                )
                self._session_manager.add(entry)
            except Exception:
                process_lock.release()
                raise

        self._profile_repository.mark_profile_used(profile.profile_id)
        self._profile_repository.record_runtime_event(
            profile_id=profile.profile_id,
            session_id=session_id,
            event_type="session_runtime_created",
            safe_metadata={"runtime_generation": generation},
        )
        return entry

    def _ensure_compat_runtime(self, agent_id: str | None) -> BrowserSessionRuntime:
        context = self._connection(agent_id=agent_id, connection_id=None)
        with context.operation_lock:
            entry = self._enter_profile(
                context,
                profile_ref=self._default_profile_ref,
                require_write=False,
            )
            return entry.runtime

    def _bind_tabs(self, entry: ActiveBrowserSession) -> None:
        try:
            tabs = entry.runtime.tabs()
        except Exception:
            return
        for tab in tabs:
            self._routes.bind_tab(
                session_id=entry.session_id,
                profile_id=entry.profile.profile_id,
                runtime_generation=entry.runtime_generation,
                local_id=tab.id,
            )

    def _project_web_state(self, entry: ActiveBrowserSession, state: WebState) -> WebState:
        projected = self._routes.project_web_state(
            state,
            profile_id=entry.profile.profile_id,
            runtime_generation=entry.runtime_generation,
        )
        return self._with_session_lease_agent(entry, projected)

    def _with_session_lease_agent(
        self,
        entry: ActiveBrowserSession,
        state: WebState,
    ) -> WebState:
        lease_status = self._session_lease_status(entry)
        if not lease_status:
            return state
        agent = state.agent.model_copy(
            update={
                "active_agent_id": lease_status["active_agent_id"],
                "agent_lease_expires_at": lease_status["agent_lease_expires_at"],
            }
        )
        return state.model_copy(update={"agent": agent})

    def _session_lease_status(self, entry: ActiveBrowserSession) -> dict[str, str | None]:
        lease = self._session_leases.active(entry.session_id)
        if lease is None:
            return {}
        return {
            "active_agent_id": lease.agent_id,
            "agent_lease_expires_at": lease.expires_at.isoformat(),
        }

    def _on_session_terminal(
        self,
        session_id: str,
        lifecycle: str,
        reason: str | None,
    ) -> None:
        entry = self._session_manager.get(session_id)
        if entry is None:
            return
        try:
            self._profile_repository.record_runtime_event(
                profile_id=entry.profile.profile_id,
                session_id=session_id,
                event_type=f"session_{lifecycle}",
                safe_metadata={"reason": (reason or "")[:200]},
            )
        except Exception:
            pass
        try:
            if lifecycle == "crashed":
                entry.runtime.close()
        except Exception:
            pass
        finally:
            self._finalize_session(entry, lifecycle=lifecycle, reason=reason)

    def _finalize_session(
        self,
        entry: ActiveBrowserSession,
        *,
        lifecycle: str,
        reason: str | None,
    ) -> None:
        removed = self._session_manager.remove(entry.session_id)
        if removed is not entry:
            return
        self._session_leases.release_session(entry.session_id)
        self._connections.unbind_session(entry.session_id)
        self._routes.invalidate_session(entry.session_id)
        entry.process_lock.release()
        if lifecycle == "crashed":
            try:
                self._session_repository.transition(
                    entry.session_id,
                    lifecycle="crashed",
                    health="failed",
                    close_reason=(reason or "browser host exited")[:500],
                )
            except Exception:
                pass
