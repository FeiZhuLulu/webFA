from __future__ import annotations

import threading
from pathlib import Path

import pytest

from browser.driver import RawPageSnapshot
from browser.exceptions import BrowserHostClosedError
from browser.profile_repository import BrowserSessionRepository, ProfileRepository
from browser.raw_snapshot import RawWebSnapshot
from browser.profile_storage import ProfileStorageManager
from browser.runtime_supervisor import BrowserRuntimeSupervisor
from schemas.browser import BrowserActionRequest, BrowserTab, BrowserViewport
from schemas.profile import BrowserProfileCreate
from schemas.web import WebOpenRequest
from storage.db import init_db, reset_engine_for_tests


class FakeDriver:
    def __init__(self, *, fail_close: bool = False) -> None:
        self.url = ""
        self.host_status = "running"
        self.closed = False
        self.fail_close = fail_close

    def open(self, url: str) -> None:
        self.url = url

    def observe_raw(self) -> RawPageSnapshot:
        return RawPageSnapshot(
            url=self.url,
            title="Session Page",
            loading=False,
            focused_element_id=None,
            viewport=BrowserViewport(width=1280, height=720),
            tabs=[BrowserTab(id="tab_1", url=self.url, title="Session Page", active=True)],
            visible_text="Session content",
            interactive_elements=[],
        )

    def observe_web_raw(self) -> RawWebSnapshot:
        if self.host_status == "exited":
            raise BrowserHostClosedError()
        return RawWebSnapshot(
            url=self.url,
            title="Session Page",
            loading=False,
            focused_element_id=None,
            viewport=BrowserViewport(width=1280, height=720),
            tabs=[BrowserTab(id="tab_1", url=self.url, title="Session Page", active=True)],
            visible_text="Session content",
        )

    def act(self, request: BrowserActionRequest) -> None:
        _ = request

    def tabs(self) -> list[BrowserTab]:
        return [BrowserTab(id="tab_1", url=self.url, title="Session Page", active=True)]

    def switch_tab(self, tab_id: str) -> None:
        _ = tab_id

    def close(self) -> None:
        self.closed = True
        if self.fail_close:
            raise RuntimeError("driver close failed")

    def status(self) -> dict:
        return {"host_status": self.host_status}


class BlockingCloseDriver(FakeDriver):
    def __init__(self, close_entered: threading.Event, allow_close: threading.Event) -> None:
        super().__init__()
        self.close_entered = close_entered
        self.allow_close = allow_close

    def close(self) -> None:
        self.close_entered.set()
        if not self.allow_close.wait(timeout=5):
            raise RuntimeError("close was not released")
        super().close()


def _setup(monkeypatch, tmp_path: Path):
    home = tmp_path / "WebFA"
    monkeypatch.setenv("WEBFA_HOME", str(home))
    reset_engine_for_tests()
    init_db()
    return ProfileRepository(), BrowserSessionRepository(), ProfileStorageManager(home)


def test_supervisor_creates_explicit_profile_session_and_generation(monkeypatch, tmp_path: Path):
    profiles, sessions, storage = _setup(monkeypatch, tmp_path)
    drivers: list[FakeDriver] = []
    supervisor = BrowserRuntimeSupervisor(
        driver_factory=lambda: (drivers.append(FakeDriver()) or drivers[-1]),
        profile_repository=profiles,
        session_repository=sessions,
        storage_manager=storage,
        initialize_storage=False,
    )

    result = supervisor.open("https://example.com", agent_id="agent-a")

    assert result.state.session_id.startswith("session_")
    assert result.state.agent.profile_id == "default"
    assert supervisor.current_session_id == result.state.session_id
    session = sessions.get_session(result.state.session_id)
    assert session.profile_id == "default"
    assert session.runtime_generation.startswith("generation_")
    assert session.lifecycle == "running"
    assert storage.paths_for("default").lock_file.exists()

    supervisor.close()
    assert sessions.get_session(session.session_id).lifecycle == "closed"
    assert drivers[0].closed is True


def test_supervisor_marks_host_crash_and_releases_profile_lock(monkeypatch, tmp_path: Path):
    profiles, sessions, storage = _setup(monkeypatch, tmp_path)
    drivers: list[FakeDriver] = []
    first = BrowserRuntimeSupervisor(
        driver_factory=lambda: (drivers.append(FakeDriver()) or drivers[-1]),
        profile_repository=profiles,
        session_repository=sessions,
        storage_manager=storage,
        initialize_storage=False,
    )
    first.open("https://example.com", agent_id="agent-a")
    first_session_id = first.current_session_id
    assert first_session_id is not None
    first_runtime = first.get_session_runtime(first_session_id)
    drivers[-1].host_status = "exited"

    with pytest.raises(BrowserHostClosedError):
        first.observe()

    crashed = sessions.get_session(first_session_id)
    assert crashed.lifecycle == "crashed"
    assert crashed.health == "failed"
    assert first_runtime.status()["host_status"] == "closed"
    assert first_runtime._thread is not None
    assert first_runtime._thread.is_alive() is False

    second = BrowserRuntimeSupervisor(
        driver_factory=lambda: (drivers.append(FakeDriver()) or drivers[-1]),
        profile_repository=profiles,
        session_repository=sessions,
        storage_manager=storage,
        initialize_storage=False,
    )
    second.open("https://example.org", agent_id="agent-b")
    assert second.current_session_id != first_session_id

    second.close()
    first.close()


def test_supervisor_close_continues_after_one_session_close_failure(monkeypatch, tmp_path: Path):
    profiles, sessions, storage = _setup(monkeypatch, tmp_path)
    profiles.create_profile(
        BrowserProfileCreate(
            agent_alias="work",
            display_name="Work Account",
            owner="shared",
        )
    )
    drivers = [FakeDriver(fail_close=True), FakeDriver()]
    supervisor = BrowserRuntimeSupervisor(
        driver_factory=lambda: drivers.pop(0),
        profile_repository=profiles,
        session_repository=sessions,
        storage_manager=storage,
        initialize_storage=False,
    )
    first = supervisor.open_web(
        WebOpenRequest(url="https://first.example"),
        agent_id="agent-a",
        connection_id="conn-a",
    )
    second = supervisor.open_web(
        WebOpenRequest(url="https://second.example", profile_ref="work"),
        agent_id="agent-b",
        connection_id="conn-b",
    )
    first_driver = supervisor.get_session_runtime(first.state.session_id)._thread
    second_driver = supervisor.get_session_runtime(second.state.session_id)._thread

    supervisor.close()

    assert supervisor.status()["active_session_count"] == 0
    assert sessions.get_session(first.state.session_id).lifecycle == "crashed"
    assert sessions.get_session(second.state.session_id).lifecycle == "closed"
    assert first_driver is not None and first_driver.is_alive() is False
    assert second_driver is not None and second_driver.is_alive() is False
    default_mutation = storage.acquire_mutation_lease(
        profiles.get_profile("default"),
        mutation_id="default-after-close",
        operation="closure_check",
    )
    work_mutation = storage.acquire_mutation_lease(
        profiles.get_profile("work"),
        mutation_id="work-after-close",
        operation="closure_check",
    )
    default_mutation.release()
    work_mutation.release()


def test_crash_cleanup_survives_runtime_event_record_failure(monkeypatch, tmp_path: Path):
    profiles, sessions, storage = _setup(monkeypatch, tmp_path)
    drivers: list[FakeDriver] = []
    supervisor = BrowserRuntimeSupervisor(
        driver_factory=lambda: (drivers.append(FakeDriver()) or drivers[-1]),
        profile_repository=profiles,
        session_repository=sessions,
        storage_manager=storage,
        initialize_storage=False,
    )
    supervisor.open("https://example.com", agent_id="agent-a")
    session_id = supervisor.current_session_id
    assert session_id is not None
    runtime = supervisor.get_session_runtime(session_id)
    drivers[-1].host_status = "exited"
    monkeypatch.setattr(
        profiles,
        "record_runtime_event",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("audit unavailable")),
    )

    with pytest.raises(BrowserHostClosedError):
        supervisor.observe()

    assert supervisor.status()["active_session_count"] == 0
    assert sessions.get_session(session_id).lifecycle == "crashed"
    assert runtime.status()["host_status"] == "closed"
    assert runtime._thread is not None and runtime._thread.is_alive() is False
    mutation = storage.acquire_mutation_lease(
        profiles.get_profile("default"),
        mutation_id="after-audit-failure",
        operation="closure_check",
    )
    mutation.release()


def test_profile_reopen_waits_until_previous_session_is_fully_closed(monkeypatch, tmp_path: Path):
    profiles, sessions, storage = _setup(monkeypatch, tmp_path)
    close_entered = threading.Event()
    allow_close = threading.Event()
    drivers = [BlockingCloseDriver(close_entered, allow_close), FakeDriver()]
    supervisor = BrowserRuntimeSupervisor(
        driver_factory=lambda: drivers.pop(0),
        profile_repository=profiles,
        session_repository=sessions,
        storage_manager=storage,
        initialize_storage=False,
    )
    first = supervisor.open_web(
        WebOpenRequest(url="https://first.example"),
        agent_id="agent-a",
        connection_id="conn-a",
    )

    close_thread = threading.Thread(
        target=lambda: supervisor.close_session(first.state.session_id, reason="maintenance"),
    )
    close_thread.start()
    assert close_entered.wait(timeout=2)

    result: dict[str, object] = {}
    open_attempted = threading.Event()

    def reopen() -> None:
        open_attempted.set()
        result["value"] = supervisor.open_web(
            WebOpenRequest(url="https://second.example"),
            agent_id="agent-a",
            connection_id="conn-a",
        )

    open_thread = threading.Thread(target=reopen)
    open_thread.start()
    assert open_attempted.wait(timeout=2)
    open_thread.join(timeout=0.1)
    assert open_thread.is_alive() is True

    allow_close.set()
    close_thread.join(timeout=5)
    open_thread.join(timeout=5)

    assert close_thread.is_alive() is False
    assert open_thread.is_alive() is False
    reopened = result["value"]
    assert reopened.state.session_id != first.state.session_id  # type: ignore[attr-defined]
    assert sessions.get_session(first.state.session_id).lifecycle == "closed"
    supervisor.close()
