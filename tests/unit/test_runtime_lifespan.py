from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.runtime.api.routes import browser as browser_routes
from apps.runtime.api.routes import monitor as monitor_routes
from apps.runtime.api.routes import profiles as profile_routes
from apps.runtime.api import action_log as action_log_api
from apps.runtime.api import monitor_access as monitor_access_api
from apps.runtime import main as runtime_main
from apps.runtime.main import _close_runtime_services
from apps.runtime.main import create_app
from browser.monitor_gateway import MonitorAccessError


class RecordingService:
    def __init__(self, name: str, calls: list[str], *, fail: bool = False) -> None:
        self.name = name
        self.calls = calls
        self.fail = fail

    def close(self) -> None:
        self.calls.append(self.name)
        if self.fail:
            raise RuntimeError(f"{self.name} close failed")


def test_runtime_shutdown_attempts_every_service_after_failures() -> None:
    app = FastAPI()
    calls: list[str] = []
    app.state.profile_bootstrap_service = RecordingService("bootstrap", calls, fail=True)
    app.state.profile_bundle_service = RecordingService("bundle", calls, fail=True)
    app.state.browser_runtime = RecordingService("runtime", calls)

    with pytest.raises(ExceptionGroup) as excinfo:
        _close_runtime_services(app)

    assert calls == ["bootstrap", "bundle", "runtime"]
    assert len(excinfo.value.exceptions) == 2


def test_runtime_shutdown_is_noop_when_services_were_never_created() -> None:
    _close_runtime_services(FastAPI())


def test_runtime_shutdown_closes_supervisor_when_runtime_alias_was_not_set() -> None:
    app = FastAPI()
    calls: list[str] = []
    app.state.browser_runtime_supervisor = RecordingService("supervisor", calls)

    _close_runtime_services(app)

    assert calls == ["supervisor"]


def test_runtime_shutdown_closes_aliased_supervisor_only_once() -> None:
    app = FastAPI()
    calls: list[str] = []
    supervisor = RecordingService("supervisor", calls)
    app.state.browser_runtime = supervisor
    app.state.browser_runtime_supervisor = supervisor

    _close_runtime_services(app)

    assert calls == ["supervisor"]


def test_runtime_shutdown_revokes_service_state_and_is_idempotent() -> None:
    app = FastAPI()
    calls: list[str] = []
    bootstrap = RecordingService("bootstrap", calls)
    supervisor = RecordingService("supervisor", calls)
    app.state.profile_bootstrap_service = bootstrap
    app.state.browser_runtime = supervisor
    app.state.browser_runtime_supervisor = supervisor

    _close_runtime_services(app)
    _close_runtime_services(app)

    assert calls == ["bootstrap", "supervisor"]
    assert app.state.profile_bootstrap_service is None
    assert app.state.browser_runtime is None
    assert app.state.browser_runtime_supervisor is None


def test_lifespan_closes_runtime_services_when_host_context_fails(monkeypatch) -> None:
    app = FastAPI()
    calls: list[str] = []
    registry = SimpleNamespace(as_json=lambda: [])
    repository = SimpleNamespace(ensure_default_profile=lambda: None)
    monkeypatch.setattr(runtime_main, "ensure_webfa_data_dir", lambda: {})
    monkeypatch.setattr(runtime_main, "init_db", lambda: "test.db")
    monkeypatch.setattr(runtime_main, "default_resources_root", lambda: "resources")
    monkeypatch.setattr(runtime_main, "build_default_registry", lambda _root: registry)
    monkeypatch.setattr(runtime_main, "upsert_transactions", lambda _transactions: None)
    monkeypatch.setattr(runtime_main, "ProfileRepository", lambda: repository)

    async def exercise_failure() -> None:
        async with runtime_main.lifespan(app):
            app.state.browser_runtime = RecordingService("runtime", calls)
            raise RuntimeError("host context failed")

    with pytest.raises(RuntimeError, match="host context failed"):
        asyncio.run(exercise_failure())

    assert calls == ["runtime"]


def test_concurrent_first_requests_share_one_runtime_supervisor(monkeypatch) -> None:
    app = create_app()
    request = SimpleNamespace(app=app)
    constructor_calls = 0
    constructor_calls_lock = threading.Lock()
    start = threading.Barrier(12)

    class FakeSupervisor:
        def __init__(self, *, profile_repository=None) -> None:
            nonlocal constructor_calls
            del profile_repository
            with constructor_calls_lock:
                constructor_calls += 1
            # Keep the constructor window open long enough for every worker to
            # exercise the first-request path.
            time.sleep(0.05)

    monkeypatch.setattr(browser_routes, "BrowserRuntimeSupervisor", FakeSupervisor)

    def resolve_runtime(_index: int):
        start.wait()
        return browser_routes.get_browser_runtime(request)

    with ThreadPoolExecutor(max_workers=12) as executor:
        runtimes = list(executor.map(resolve_runtime, range(12)))

    assert constructor_calls == 1
    assert len({id(runtime) for runtime in runtimes}) == 1
    assert app.state.browser_runtime is app.state.browser_runtime_supervisor


def test_http_and_monitor_first_connections_share_one_runtime_supervisor(monkeypatch) -> None:
    app = create_app()
    connection = SimpleNamespace(app=app)
    constructor_calls = 0
    constructor_calls_lock = threading.Lock()
    start = threading.Barrier(12)

    class FakeSupervisor:
        def __init__(self, *, profile_repository=None) -> None:
            nonlocal constructor_calls
            del profile_repository
            with constructor_calls_lock:
                constructor_calls += 1
            time.sleep(0.05)

    monkeypatch.setattr(browser_routes, "BrowserRuntimeSupervisor", FakeSupervisor)
    monkeypatch.setattr(monitor_routes, "BrowserRuntimeSupervisor", FakeSupervisor)

    def resolve_runtime(index: int):
        start.wait()
        if index % 2:
            return monitor_routes._get_runtime(connection)
        return browser_routes.get_browser_runtime(connection)

    with ThreadPoolExecutor(max_workers=12) as executor:
        runtimes = list(executor.map(resolve_runtime, range(12)))

    assert constructor_calls == 1
    assert len({id(runtime) for runtime in runtimes}) == 1


def test_concurrent_profile_services_share_singletons(monkeypatch) -> None:
    app = create_app()
    app.state.profile_repository = object()
    request = SimpleNamespace(app=app)
    calls = {"storage": 0, "bootstrap": 0, "bundle": 0}
    calls_lock = threading.Lock()
    start = threading.Barrier(12)

    class FakeStorage:
        def __init__(self) -> None:
            with calls_lock:
                calls["storage"] += 1
            time.sleep(0.03)

    class FakeBootstrap:
        def __init__(self, *, repository, storage) -> None:
            del repository, storage
            with calls_lock:
                calls["bootstrap"] += 1
            time.sleep(0.03)

    class FakeBundle:
        def __init__(self, *, repository, storage) -> None:
            del repository, storage
            with calls_lock:
                calls["bundle"] += 1
            time.sleep(0.03)

    monkeypatch.setattr(profile_routes, "ProfileStorageManager", FakeStorage)
    monkeypatch.setattr(profile_routes, "ProfileBootstrapService", FakeBootstrap)
    monkeypatch.setattr(profile_routes, "ProfileBundleService", FakeBundle)

    def resolve_service(index: int):
        start.wait()
        if index % 2:
            return profile_routes.get_profile_bootstrap_service(request)
        return profile_routes.get_profile_bundle_service(request)

    with ThreadPoolExecutor(max_workers=12) as executor:
        services = list(executor.map(resolve_service, range(12)))

    assert calls == {"storage": 1, "bootstrap": 1, "bundle": 1}
    assert len({id(service) for service in services[::2]}) == 1
    assert len({id(service) for service in services[1::2]}) == 1


def test_concurrent_control_services_share_singletons(monkeypatch) -> None:
    app = create_app()
    connection = SimpleNamespace(app=app)
    calls = {"action_log": 0, "monitor_access": 0}
    calls_lock = threading.Lock()
    start = threading.Barrier(12)

    class FakeActionLog:
        def __init__(self) -> None:
            with calls_lock:
                calls["action_log"] += 1
            time.sleep(0.03)

    class FakeMonitorAccessManager:
        def __init__(self) -> None:
            with calls_lock:
                calls["monitor_access"] += 1
            time.sleep(0.03)

    monkeypatch.setattr(action_log_api, "ActionLog", FakeActionLog)
    monkeypatch.setattr(monitor_access_api, "MonitorAccessManager", FakeMonitorAccessManager)

    def resolve_service(index: int):
        start.wait()
        if index % 2:
            return action_log_api.get_action_log(connection)
        return monitor_access_api.get_monitor_access_manager(connection)

    with ThreadPoolExecutor(max_workers=12) as executor:
        services = list(executor.map(resolve_service, range(12)))

    assert calls == {"action_log": 1, "monitor_access": 1}
    assert len({id(service) for service in services[::2]}) == 1
    assert len({id(service) for service in services[1::2]}) == 1


def test_shutdown_invalidates_monitor_grants_and_ephemeral_control_state() -> None:
    app = create_app()
    connection = SimpleNamespace(app=app)
    manager = monitor_access_api.get_monitor_access_manager(connection)
    grant = manager.issue(session_id="session_1")
    action_log = action_log_api.get_action_log(connection)
    app.state.visualizer_preview_cache = object()

    _close_runtime_services(app)

    replacement = monitor_access_api.get_monitor_access_manager(connection)
    assert replacement is not manager
    assert action_log_api.get_action_log(connection) is not action_log
    assert app.state.visualizer_preview_cache is None
    with pytest.raises(MonitorAccessError):
        replacement.consume(grant.token)


def test_reentered_app_does_not_accept_previous_runtime_monitor_token(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    app = create_app()
    connection = SimpleNamespace(app=app)

    with TestClient(app):
        first_manager = monitor_access_api.get_monitor_access_manager(connection)
        grant = first_manager.issue(session_id="session_1")

    with TestClient(app):
        replacement = monitor_access_api.get_monitor_access_manager(connection)
        assert replacement is not first_manager
        with pytest.raises(MonitorAccessError):
            replacement.consume(grant.token)
