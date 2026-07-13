from __future__ import annotations

from pathlib import Path

import pytest

from browser.driver import RawPageSnapshot
from browser.exceptions import BrowserHostClosedError
from browser.profile_repository import BrowserSessionRepository, ProfileRepository
from browser.profile_storage import ProfileStorageManager
from browser.runtime_supervisor import BrowserRuntimeSupervisor
from schemas.browser import BrowserActionRequest, BrowserTab, BrowserViewport
from storage.db import init_db, reset_engine_for_tests


class FakeDriver:
    def __init__(self) -> None:
        self.url = ""
        self.host_status = "running"
        self.closed = False

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

    def act(self, request: BrowserActionRequest) -> None:
        _ = request

    def tabs(self) -> list[BrowserTab]:
        return [BrowserTab(id="tab_1", url=self.url, title="Session Page", active=True)]

    def switch_tab(self, tab_id: str) -> None:
        _ = tab_id

    def close(self) -> None:
        self.closed = True

    def status(self) -> dict:
        return {"host_status": self.host_status}


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
    drivers[-1].host_status = "exited"

    with pytest.raises(BrowserHostClosedError):
        first.observe()

    crashed = sessions.get_session(first_session_id)
    assert crashed.lifecycle == "crashed"
    assert crashed.health == "failed"

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
