from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from browser.driver import RawPageSnapshot
from browser.exceptions import BrowserHostClosedError
from browser.profile_repository import BrowserSessionRepository, ProfileRepository
from browser.raw_snapshot import RawWebSnapshot
from browser.profile_storage import ProfileStorageManager
from browser.runtime_errors import BrowserRuntimeError
from browser.runtime_supervisor import BrowserRuntimeSupervisor
from browser.session_routing import AgentSessionLeaseManager
from schemas.browser import BrowserActionRequest, BrowserTab, BrowserViewport
from schemas.profile import BrowserProfileCreate, BrowserProfileUpdate
from schemas.web import WebObserveRequest, WebOpenRequest
from storage.db import init_db, reset_engine_for_tests


class FakeDriver:
    def __init__(self) -> None:
        self.url = ""
        self.host_status = "running"
        self.closed = False

    def open(self, url: str) -> None:
        self.url = url

    def observe_web_raw(self) -> RawWebSnapshot:
        if self.host_status == "exited":
            raise BrowserHostClosedError()
        return RawWebSnapshot(
            url=self.url,
            title=self.url or "Session",
            loading=False,
            focused_element_id=None,
            viewport=BrowserViewport(width=1280, height=720),
            tabs=[BrowserTab(id="tab_1", url=self.url, title=self.url or "Session", active=True)],
            visible_text=f"content:{self.url}",
        )

    def observe_raw(self) -> RawPageSnapshot:
        return self.observe_web_raw().to_page_snapshot()

    def legacy_observe_raw(self) -> RawPageSnapshot:
        if self.host_status == "exited":
            raise BrowserHostClosedError()
        return RawPageSnapshot(
            url=self.url,
            title=self.url or "Session",
            loading=False,
            focused_element_id=None,
            viewport=BrowserViewport(width=1280, height=720),
            tabs=[BrowserTab(id="tab_1", url=self.url, title=self.url or "Session", active=True)],
            visible_text=f"content:{self.url}",
            interactive_elements=[],
        )

    def act(self, request: BrowserActionRequest) -> None:
        _ = request

    def tabs(self) -> list[BrowserTab]:
        if self.host_status == "exited":
            raise BrowserHostClosedError()
        return [BrowserTab(id="tab_1", url=self.url, title=self.url or "Session", active=True)]

    def switch_tab(self, tab_id: str) -> None:
        assert tab_id == "tab_1"

    def dispatch_human_input(self, event) -> None:
        _ = event

    def close(self) -> None:
        self.closed = True

    def status(self) -> dict:
        return {"host_status": self.host_status}


def _setup(monkeypatch, tmp_path: Path):
    home = tmp_path / "WebFA"
    monkeypatch.setenv("WEBFA_HOME", str(home))
    reset_engine_for_tests()
    init_db()
    profiles = ProfileRepository()
    profiles.ensure_default_profile()
    profiles.create_profile(
        BrowserProfileCreate(
            agent_alias="work",
            display_name="Work Account",
            owner="shared",
        )
    )
    return profiles, BrowserSessionRepository(), ProfileStorageManager(home)


def test_one_connection_can_use_two_profiles_and_switch_across_global_tabs(monkeypatch, tmp_path: Path) -> None:
    profiles, sessions, storage = _setup(monkeypatch, tmp_path)
    drivers: list[FakeDriver] = []
    supervisor = BrowserRuntimeSupervisor(
        driver_factory=lambda: (drivers.append(FakeDriver()) or drivers[-1]),
        profile_repository=profiles,
        session_repository=sessions,
        storage_manager=storage,
        initialize_storage=False,
    )

    personal = supervisor.open_web(
        WebOpenRequest(url="https://personal.example"),
        agent_id="agent-a",
        connection_id="conn-a",
    )
    work = supervisor.open_web(
        WebOpenRequest(url="https://work.example", profile_ref="work"),
        agent_id="agent-a",
        connection_id="conn-a",
    )

    assert personal.state.session_id != work.state.session_id
    assert personal.state.agent.profile_id == "default"
    assert work.state.agent.profile_id != "default"
    assert supervisor.status()["active_session_count"] == 2
    assert len(drivers) == 2

    tabs = supervisor.get_tabs(agent_id="agent-a", connection_id="conn-a")
    assert len(tabs["tabs"]) == 2
    assert {tab["profile_ref"] for tab in tabs["tabs"]} == {"default", "work"}
    assert len({tab["id"] for tab in tabs["tabs"]}) == 2

    personal_tab = next(tab for tab in tabs["tabs"] if tab["profile_ref"] == "default")
    switched = supervisor.switch_tab_for_connection(
        personal_tab["id"],
        agent_id="agent-a",
        connection_id="conn-a",
    )
    assert switched.session_id == personal.state.session_id
    assert switched.url == "https://personal.example"

    supervisor.close()


def test_same_profile_is_exclusive_between_agent_connections(monkeypatch, tmp_path: Path) -> None:
    profiles, sessions, storage = _setup(monkeypatch, tmp_path)
    supervisor = BrowserRuntimeSupervisor(
        driver_factory=FakeDriver,
        profile_repository=profiles,
        session_repository=sessions,
        storage_manager=storage,
        initialize_storage=False,
    )
    supervisor.open_web(
        WebOpenRequest(url="https://example.com"),
        agent_id="agent-a",
        connection_id="conn-a",
    )

    with pytest.raises(BrowserRuntimeError) as excinfo:
        supervisor.open_web(
            WebOpenRequest(url="https://example.org"),
            agent_id="agent-b",
            connection_id="conn-b",
        )
    assert excinfo.value.code == "session_busy"

    supervisor.close()


def test_control_session_creation_does_not_mint_agent_authority(monkeypatch, tmp_path: Path) -> None:
    profiles, sessions, storage = _setup(monkeypatch, tmp_path)
    work = profiles.get_profile("work")
    profiles.update_profile(
        work.profile_id,
        BrowserProfileUpdate(
            expected_version=work.version,
            bound_agent_ids=["agent-a"],
        ),
    )
    supervisor = BrowserRuntimeSupervisor(
        driver_factory=FakeDriver,
        profile_repository=profiles,
        session_repository=sessions,
        storage_manager=storage,
        initialize_storage=False,
    )

    control_runtime = supervisor.ensure_control_session_runtime("work")

    assert control_runtime.profile_id == work.profile_id
    assert supervisor.ensure_control_session_runtime() is control_runtime
    assert supervisor.status()["active_session_count"] == 1
    assert supervisor.status().get("active_agent_id") is None
    with pytest.raises(BrowserRuntimeError) as excinfo:
        supervisor.open_web(
            WebOpenRequest(url="https://work.example", profile_ref="work"),
            agent_id="agent-b",
            connection_id="conn-b",
        )
    assert excinfo.value.code == "profile_access_denied"

    opened = supervisor.open_web(
        WebOpenRequest(url="https://work.example", profile_ref="work"),
        agent_id="agent-a",
        connection_id="conn-a",
    )
    assert opened.state.session_id == control_runtime.session_id
    supervisor.close()


def test_local_tab_id_cannot_bypass_connection_exclusive_session_lease(monkeypatch, tmp_path: Path) -> None:
    profiles, sessions, storage = _setup(monkeypatch, tmp_path)
    supervisor = BrowserRuntimeSupervisor(
        driver_factory=FakeDriver,
        profile_repository=profiles,
        session_repository=sessions,
        storage_manager=storage,
        initialize_storage=False,
    )
    supervisor.open_web(
        WebOpenRequest(url="https://example.com"),
        agent_id="same-agent",
        connection_id="conn-a",
    )
    supervisor.observe_web(
        WebObserveRequest(mode="page"),
        agent_id="same-agent",
        connection_id="conn-b",
    )

    with pytest.raises(BrowserRuntimeError) as excinfo:
        supervisor.switch_tab_for_connection(
            "tab_1",
            agent_id="same-agent",
            connection_id="conn-b",
        )

    assert excinfo.value.code == "session_busy"
    supervisor.close()


def test_active_profile_grant_rechecks_current_agent_binding_policy(monkeypatch, tmp_path: Path) -> None:
    profiles, sessions, storage = _setup(monkeypatch, tmp_path)
    selected = profiles.get_profile("work")
    profiles.update_profile(
        "work",
        BrowserProfileUpdate(
            expected_version=selected.version,
            bound_agent_ids=["agent-a"],
        ),
    )
    supervisor = BrowserRuntimeSupervisor(
        driver_factory=FakeDriver,
        profile_repository=profiles,
        session_repository=sessions,
        storage_manager=storage,
        initialize_storage=False,
    )
    opened = supervisor.open_web(
        WebOpenRequest(url="https://work.example", profile_ref="work"),
        agent_id="agent-a",
        connection_id="conn-a",
    )
    current = profiles.get_profile("work")
    profiles.update_profile(
        "work",
        BrowserProfileUpdate(
            expected_version=current.version,
            bound_agent_ids=["agent-b"],
        ),
    )

    with pytest.raises(BrowserRuntimeError) as excinfo:
        supervisor.observe_web(
            WebObserveRequest(mode="page"),
            agent_id="agent-a",
            connection_id="conn-a",
        )

    assert opened.state.agent.profile_id == current.profile_id
    assert excinfo.value.code == "profile_access_denied"
    supervisor.close()


def test_supervisor_projects_connection_scoped_session_lease_as_agent_state(monkeypatch, tmp_path: Path) -> None:
    profiles, sessions, storage = _setup(monkeypatch, tmp_path)
    now = [datetime(2040, 1, 1, tzinfo=timezone.utc)]
    leases = AgentSessionLeaseManager(ttl_seconds=90, clock=lambda: now[0])
    supervisor = BrowserRuntimeSupervisor(
        driver_factory=FakeDriver,
        profile_repository=profiles,
        session_repository=sessions,
        storage_manager=storage,
        session_leases=leases,
        initialize_storage=False,
    )
    opened = supervisor.open_web(
        WebOpenRequest(url="https://example.com"),
        agent_id="agent-a",
        connection_id="conn-a",
    )
    expected_expiry = (now[0] + timedelta(seconds=90)).isoformat()

    assert opened.state.agent.active_agent_id == "agent-a"
    assert opened.state.agent.agent_lease_expires_at == expected_expiry
    assert supervisor.status(connection_id="conn-a")["agent_lease_expires_at"] == expected_expiry
    assert supervisor.monitor_snapshot(opened.state.session_id)["agent_lease_expires_at"] == expected_expiry

    now[0] += timedelta(seconds=60)
    observed = supervisor.observe_web(
        WebObserveRequest(mode="page"),
        agent_id="agent-a",
        connection_id="conn-a",
    )
    renewed_expiry = (now[0] + timedelta(seconds=90)).isoformat()
    assert observed.state.agent.agent_lease_expires_at == renewed_expiry
    assert supervisor.status(connection_id="conn-a")["agent_lease_expires_at"] == renewed_expiry
    supervisor.close()


def test_crashed_session_does_not_stop_other_profile_session(monkeypatch, tmp_path: Path) -> None:
    profiles, sessions, storage = _setup(monkeypatch, tmp_path)
    drivers: list[FakeDriver] = []
    supervisor = BrowserRuntimeSupervisor(
        driver_factory=lambda: (drivers.append(FakeDriver()) or drivers[-1]),
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
    drivers[0].host_status = "exited"

    with pytest.raises(BrowserHostClosedError):
        supervisor.observe_web(
            WebObserveRequest(mode="page"),
            agent_id="agent-a",
            connection_id="conn-a",
        )

    assert sessions.get_session(first.state.session_id).lifecycle == "crashed"
    observed = supervisor.observe_web(
        WebObserveRequest(mode="page"),
        agent_id="agent-b",
        connection_id="conn-b",
    )
    assert observed.state.session_id == second.state.session_id
    assert observed.state.url == "https://second.example"

    supervisor.close()


def test_human_control_is_scoped_to_one_session(monkeypatch, tmp_path: Path) -> None:
    profiles, sessions, storage = _setup(monkeypatch, tmp_path)
    supervisor = BrowserRuntimeSupervisor(
        driver_factory=FakeDriver,
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
    first_runtime = supervisor.get_session_runtime(first.state.session_id)
    second_runtime = supervisor.get_session_runtime(second.state.session_id)

    lease = first_runtime.acquire_human_control(
        connection_id="monitor-a",
        reason="manual_identity_confirmation",
        ttl_seconds=60,
    )

    assert first_runtime.human_control_status() is not None
    assert second_runtime.human_control_status() is None
    observed = supervisor.observe_web(
        WebObserveRequest(mode="page"),
        agent_id="agent-b",
        connection_id="conn-b",
    )
    assert observed.state.session_id == second.state.session_id

    first_runtime.release_human_control(
        connection_id="monitor-a",
        lease_id=lease.lease_id,
    )
    supervisor.close()


def test_control_plane_can_close_one_profile_session_for_maintenance(monkeypatch, tmp_path: Path) -> None:
    profiles, sessions, storage = _setup(monkeypatch, tmp_path)
    supervisor = BrowserRuntimeSupervisor(
        driver_factory=FakeDriver,
        profile_repository=profiles,
        session_repository=sessions,
        storage_manager=storage,
        initialize_storage=False,
    )
    personal = supervisor.open_web(
        WebOpenRequest(url="https://personal.example"),
        agent_id="agent-a",
        connection_id="conn-a",
    )
    work = supervisor.open_web(
        WebOpenRequest(url="https://work.example", profile_ref="work"),
        agent_id="agent-b",
        connection_id="conn-b",
    )

    closed_session_id = supervisor.close_profile_session(
        "work",
        reason="profile_bootstrap",
    )

    assert closed_session_id == work.state.session_id
    assert sessions.get_session(work.state.session_id).lifecycle == "closed"
    assert supervisor.status()["active_session_count"] == 1
    observed = supervisor.observe_web(
        WebObserveRequest(mode="page"),
        agent_id="agent-a",
        connection_id="conn-a",
    )
    assert observed.state.session_id == personal.state.session_id

    mutation = storage.acquire_mutation_lease(
        profiles.get_profile("work"),
        mutation_id="cookie-import-check",
        operation="cookie_import",
    )
    mutation.release()
    supervisor.close()
