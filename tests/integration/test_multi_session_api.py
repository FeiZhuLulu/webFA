from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from apps.runtime.main import create_app
from browser.profile_bootstrap import ProfileBootstrapService
from browser.profile_storage import ProfileStorageManager
from browser.raw_snapshot import RawWebSnapshot
from browser.runtime_supervisor import BrowserRuntimeSupervisor
from schemas.browser import BrowserActionRequest, BrowserTab, BrowserViewport
from storage.db import reset_engine_for_tests


CONTROL_TOKEN = "p12-multi-session-control"
CONTROL_HEADERS = {"X-WebFA-Visualizer-Token": CONTROL_TOKEN}


class FakeDriver:
    def __init__(self) -> None:
        self.url = ""
        self.closed = False

    def open(self, url: str) -> None:
        self.url = url

    def observe_web_raw(self) -> RawWebSnapshot:
        return RawWebSnapshot(
            url=self.url,
            title=self.url or "Session",
            loading=False,
            focused_element_id=None,
            viewport=BrowserViewport(width=1280, height=720),
            tabs=[BrowserTab(id="tab_1", url=self.url, title=self.url or "Session", active=True)],
            visible_text=self.url,
        )

    def observe_raw(self):
        return self.observe_web_raw().to_page_snapshot()

    def act(self, request: BrowserActionRequest) -> None:
        _ = request

    def tabs(self):
        return [BrowserTab(id="tab_1", url=self.url, title=self.url or "Session", active=True)]

    def switch_tab(self, tab_id: str) -> None:
        assert tab_id == "tab_1"

    def close(self) -> None:
        self.closed = True

    def status(self):
        return {"host_status": "running"}


def test_multi_profile_five_tool_routing_and_monitor_session_binding(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "WebFA"
    monkeypatch.setenv("WEBFA_HOME", str(home))
    monkeypatch.setenv("WEBFA_VISUALIZER_CONTROL_TOKEN", CONTROL_TOKEN)
    reset_engine_for_tests()

    app = create_app()
    with TestClient(app) as client:
        created = client.post(
            "/v1/profiles",
            headers=CONTROL_HEADERS,
            json={
                "agent_alias": "work",
                "display_name": "Work",
                "owner": "shared",
            },
        )
        assert created.status_code == 201, created.text
        work_profile_id = created.json()["profile_id"]

        drivers: list[FakeDriver] = []
        supervisor = BrowserRuntimeSupervisor(
            driver_factory=lambda: (drivers.append(FakeDriver()) or drivers[-1]),
            profile_repository=app.state.profile_repository,
            storage_manager=ProfileStorageManager(home),
            initialize_storage=False,
        )
        app.state.browser_runtime_supervisor = supervisor
        app.state.browser_runtime = supervisor

        headers = {
            "X-WebFA-Agent-Id": "agent-a",
            "X-WebFA-Connection-Id": "connection-a",
        }
        personal = client.post(
            "/v1/browser/web/open",
            headers=headers,
            json={"url": "https://personal.example"},
        )
        assert personal.status_code == 200, personal.text
        personal_session = personal.json()["state"]["session_id"]

        work = client.post(
            "/v1/browser/web/open",
            headers=headers,
            json={"url": "https://work.example", "profile_ref": "work"},
        )
        assert work.status_code == 200, work.text
        work_session = work.json()["state"]["session_id"]
        assert work_session != personal_session
        assert work.json()["state"]["agent"]["profile_id"] == work_profile_id

        tabs = client.get("/v1/browser/tabs", headers=headers)
        assert tabs.status_code == 200, tabs.text
        tab_items = tabs.json()["tabs"]
        assert len(tab_items) == 2
        assert {item["profile_ref"] for item in tab_items} == {"default", "work"}
        assert all(item["id"].startswith("tabr_") for item in tab_items)

        personal_tab = next(item for item in tab_items if item["profile_ref"] == "default")
        switched = client.post(
            "/v1/browser/web/tabs/switch",
            headers=headers,
            json={"tab_id": personal_tab["id"]},
        )
        assert switched.status_code == 200, switched.text
        assert switched.json()["session_id"] == personal_session

        competing = client.post(
            "/v1/browser/web/open",
            headers={
                "X-WebFA-Agent-Id": "agent-b",
                "X-WebFA-Connection-Id": "connection-b",
            },
            json={"url": "https://other.example", "profile_ref": "work"},
        )
        assert competing.status_code == 409
        assert competing.json()["detail"]["code"] == "session_busy"

        sessions = client.get("/v1/visualizer/sessions", headers=CONTROL_HEADERS)
        assert sessions.status_code == 200, sessions.text
        session_items = sessions.json()["sessions"]
        assert {item["session_id"] for item in session_items} == {personal_session, work_session}

        grant = client.post(
            "/v1/visualizer/monitor-grants",
            headers=CONTROL_HEADERS,
            json={"session_id": work_session, "permissions": ["events"]},
        )
        assert grant.status_code == 200, grant.text
        grant_payload = grant.json()["grant"]
        assert grant_payload["session_id"] == work_session
        assert grant_payload["profile_id"] == work_profile_id
        assert grant_payload["runtime_generation"].startswith("generation_")


def test_close_poll_and_cookie_import_does_not_recreate_profile_session(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "WebFA"
    monkeypatch.setenv("WEBFA_HOME", str(home))
    monkeypatch.setenv("WEBFA_VISUALIZER_CONTROL_TOKEN", CONTROL_TOKEN)
    reset_engine_for_tests()
    app = create_app()

    class FakeMaintenanceHost:
        def __init__(self, profile, storage, mutation_id):
            _ = profile, storage, mutation_id

        def import_cookies(self, cookies):
            return len(cookies)

        def close(self):
            return None

    with TestClient(app) as client:
        storage = ProfileStorageManager(home)
        supervisor = BrowserRuntimeSupervisor(
            driver_factory=FakeDriver,
            profile_repository=app.state.profile_repository,
            storage_manager=storage,
            initialize_storage=False,
        )
        app.state.browser_runtime_supervisor = supervisor
        app.state.browser_runtime = supervisor
        app.state.profile_storage_manager = storage
        app.state.profile_bootstrap_service = ProfileBootstrapService(
            repository=app.state.profile_repository,
            storage=storage,
            host_factory=FakeMaintenanceHost,
        )

        opened = client.post(
            "/v1/browser/web/open",
            headers={
                "X-WebFA-Agent-Id": "agent-a",
                "X-WebFA-Connection-Id": "connection-a",
            },
            json={"url": "https://example.com"},
        )
        assert opened.status_code == 200, opened.text
        assert supervisor.status()["active_session_count"] == 1

        profile = app.state.profile_repository.get_profile("default")
        closed = client.post(
            "/v1/profiles/default/session/close",
            headers=CONTROL_HEADERS,
        )
        assert closed.status_code == 200, closed.text
        assert closed.json()["status"] == "session_closed"
        assert supervisor.status()["active_session_count"] == 0

        polled = client.get("/v1/visualizer/state", headers=CONTROL_HEADERS)
        assert polled.status_code == 200, polled.text
        assert polled.json()["browser_state"] is None
        assert supervisor.status()["active_session_count"] == 0

        content = json.dumps(
            [
                {
                    "name": "sid",
                    "value": "control-flow-secret",
                    "url": "https://example.com/",
                    "path": "/",
                    "secure": True,
                    "expirationDate": time.time() + 3600,
                }
            ]
        ).encode("utf-8")
        previewed = client.post(
            f"/v1/profiles/default/bootstrap/cookies/preview?expected_version={profile.version}",
            headers={**CONTROL_HEADERS, "Content-Type": "application/octet-stream"},
            content=content,
        )
        assert previewed.status_code == 200, previewed.text
        imported = client.post(
            "/v1/profiles/default/bootstrap/cookies/import",
            headers=CONTROL_HEADERS,
            json={
                "preview_token": previewed.json()["preview_token"],
                "expected_version": profile.version,
            },
        )
        assert imported.status_code == 200, imported.text
        assert imported.json()["status"] == "cookies_imported"
        assert supervisor.status()["active_session_count"] == 0
