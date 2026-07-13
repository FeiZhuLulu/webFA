from __future__ import annotations

import threading
from typing import Any, Callable
from uuid import uuid4

from browser.config import resolve_browser_runtime_config
from browser.driver import BrowserDriver
from browser.driver_factory import create_default_driver_factory
from browser.profile_repository import BrowserSessionRepository, ProfileRepository
from browser.profile_storage import ProfileProcessLock, ProfileStorageManager
from browser.runtime import BrowserSessionRuntime, DriverFactory
from storage.db import init_db


class BrowserRuntimeSupervisor:
    """P12 supervisor foundation preserving one default Session through P12.3.

    Global multi-Profile routing is added in P12.4. This class already owns the
    durable Profile, process lock, Session metadata, explicit launch spec, and
    SessionRuntime lifecycle so the application singleton no longer owns page
    state directly.
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
        self._runtime: BrowserSessionRuntime | None = None
        self._profile_lock: ProfileProcessLock | None = None
        self._session_id: str | None = None
        self._profile_id: str | None = None
        self._runtime_generation: str | None = None
        self._closed = False
        self._lock = threading.RLock()

    @property
    def runtime_instance_id(self) -> str:
        return self._runtime_instance_id

    @property
    def current_session_id(self) -> str | None:
        return self._session_id

    @property
    def current_profile_id(self) -> str | None:
        return self._profile_id

    @property
    def profile_repository(self) -> ProfileRepository:
        return self._profile_repository

    @property
    def session_repository(self) -> BrowserSessionRepository:
        return self._session_repository

    def current_session_runtime(self) -> BrowserSessionRuntime:
        return self._ensure_runtime()

    def status(self) -> dict[str, Any]:
        with self._lock:
            runtime = self._runtime
            generation = self._runtime_generation
        if runtime is None:
            return {
                "runtime_instance_id": self._runtime_instance_id,
                "session_id": None,
                "profile_id": None,
                "runtime_generation": None,
                "supervisor_lifecycle": "inactive",
                "selected_driver": self._driver_name,
                "headless": self._headless,
                "host_status": "not_started",
                "last_error": None,
            }
        runtime_status = runtime.status()
        return {
            **runtime_status,
            "runtime_instance_id": self._runtime_instance_id,
            "runtime_generation": generation,
            "supervisor_lifecycle": "active",
        }

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            runtime = self._runtime
        if runtime is not None:
            runtime.close()
        self._release_profile_lock()

    def __getattr__(self, name: str):
        if name.startswith("__"):
            raise AttributeError(name)
        runtime = self._ensure_runtime()
        return getattr(runtime, name)

    def _ensure_runtime(self) -> BrowserSessionRuntime:
        with self._lock:
            if self._closed:
                raise RuntimeError("browser runtime supervisor is closed")
            if self._runtime is not None:
                return self._runtime

            profile = (
                self._profile_repository.ensure_default_profile()
                if self._default_profile_ref == "default"
                else self._profile_repository.get_profile(self._default_profile_ref)
            )
            if profile.catalog_state != "ready":
                raise RuntimeError(
                    f"browser profile '{profile.agent_alias}' is not ready"
                )
            session_id = f"session_{uuid4().hex}"
            generation = f"generation_{uuid4().hex}"
            process_lock = self._storage_manager.acquire_process_lock(
                profile,
                runtime_instance_id=self._runtime_instance_id,
                runtime_generation=generation,
                session_id=session_id,
            )
            try:
                if profile.profile_id == "default":
                    self._storage_manager.migrate_legacy_default_profile()
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
                )
                runtime = BrowserSessionRuntime(
                    headless=self._headless,
                    driver_factory=driver_factory,
                    session_id=session_id,
                    profile_id=profile.profile_id,
                    runtime_generation=generation,
                    profile_repository=self._profile_repository,
                    session_repository=self._session_repository,
                    terminal_callback=self._on_session_terminal,
                )
            except Exception:
                process_lock.release()
                raise

            self._runtime = runtime
            self._profile_lock = process_lock
            self._session_id = session_id
            self._profile_id = profile.profile_id
            self._runtime_generation = generation
            self._profile_repository.mark_profile_used(profile.profile_id)
            self._profile_repository.record_runtime_event(
                profile_id=profile.profile_id,
                session_id=session_id,
                event_type="session_runtime_created",
                safe_metadata={"runtime_generation": generation},
            )
            return runtime

    def _on_session_terminal(self, lifecycle: str, reason: str | None) -> None:
        with self._lock:
            profile_id = self._profile_id
            session_id = self._session_id
        if profile_id is not None:
            self._profile_repository.record_runtime_event(
                profile_id=profile_id,
                session_id=session_id,
                event_type=f"session_{lifecycle}",
                safe_metadata={"reason": (reason or "")[:200]},
            )
        self._release_profile_lock()

    def _release_profile_lock(self) -> None:
        with self._lock:
            process_lock = self._profile_lock
            self._profile_lock = None
        if process_lock is not None:
            process_lock.release()
