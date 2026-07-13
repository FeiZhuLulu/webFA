from __future__ import annotations

import asyncio
import json
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from apps.runtime.api.routes.monitor import _ConnectionBridge
from apps.runtime.main import create_app
from browser.human_control import HumanControlLeaseState, HumanInputEvent
from browser.managed_chromium_host import _find_chromium_executable
from browser.monitor_gateway import decode_visual_frame_packet
from browser.session_events import SessionEvent
from browser.visual_surface import VisualFrame, VisualStreamState, VisualSurfaceBinding
from storage.db import reset_engine_for_tests

CONTROL_TOKEN = "monitor-control-test-token"
CONTROL_HEADERS = {"X-WebFA-Visualizer-Token": CONTROL_TOKEN}
ORIGIN_HEADERS = {"origin": "http://127.0.0.1:8788"}
FIXTURE_PAGE = Path(__file__).resolve().parents[1] / "fixtures" / "agent_validation_page.html"
HUMAN_CONTROL_PAGE = Path(__file__).resolve().parents[1] / "fixtures" / "human_control_page.html"


class _FakeMonitorRuntime:
    def __init__(self) -> None:
        self.subscription_callback = None
        self.stopped_streams: list[str] = []
        self.unsubscribed: list[str] = []
        self.human_inputs: list[HumanInputEvent] = []
        self.human_lease: HumanControlLeaseState | None = None
        self.released_connections: list[str] = []

    def monitor_snapshot(self) -> dict:
        return {
            "session_id": "default",
            "profile_id": "default",
            "active_agent_id": "agent-test",
            "agent_lease_expires_at": None,
            "tab_id": "tab_1",
            "document_id": "doc_1",
            "document_revision": 4,
            "url": "https://shop.example/checkout",
            "title": "Checkout",
            "object_count": 12,
            "takeover_required": False,
            "takeover_reason": "authentication" if self.human_lease is not None else None,
            "human_control_active": self.human_lease is not None,
            "human_control_reason": self.human_lease.reason if self.human_lease is not None else None,
            "human_control_expires_at": self.human_lease.expires_at.isoformat() if self.human_lease is not None else None,
        }

    def subscribe_session_events(self, callback, **_kwargs) -> str:
        self.subscription_callback = callback
        callback(
            SessionEvent(
                event_id="sevt_test",
                sequence=9,
                session_id="default",
                type="operation_completed",
                timestamp=datetime.now(timezone.utc),
                tab_id="tab_1",
                document_id="doc_1",
                operation_id="op_test",
                data={"operation": "activate", "executed": True},
            )
        )
        return "sub_test"

    def unsubscribe_session_events(self, subscription_id: str) -> bool:
        self.unsubscribed.append(subscription_id)
        return True

    def start_visual_stream(self, frame_sink, _config) -> str:
        frame_sink(
            VisualFrame(
                stream_id="vstream_test",
                frame_seq=1,
                session_id="default",
                tab_id="tab_1",
                document_id="doc_1",
                data=b"fake-jpeg",
                format="jpeg",
                width=640,
                height=360,
                device_scale_factor=1.0,
                scroll_offset_x=0.0,
                scroll_offset_y=0.0,
                captured_at=datetime.now(timezone.utc),
            )
        )
        return "vstream_test"

    def acquire_human_control(
        self,
        *,
        connection_id: str,
        reason: str | None = None,
        ttl_seconds: int = 300,
    ) -> HumanControlLeaseState:
        now = datetime.now(timezone.utc)
        self.human_lease = HumanControlLeaseState(
            lease_id="hlease_test",
            connection_id=connection_id,
            session_id="default",
            profile_id="default",
            tab_id="tab_1",
            reason=reason or "authentication",
            active_agent_id="agent-test",
            acquired_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
            status="active",
        )
        return self.human_lease

    def send_human_input(
        self,
        *,
        connection_id: str,
        lease_id: str,
        event: HumanInputEvent,
    ) -> None:
        assert self.human_lease is not None
        assert self.human_lease.connection_id == connection_id
        assert self.human_lease.lease_id == lease_id
        self.human_inputs.append(event)

    def sync_human_control_state(self, *, connection_id: str, lease_id: str) -> dict:
        assert self.human_lease is not None
        assert self.human_lease.connection_id == connection_id
        assert self.human_lease.lease_id == lease_id
        return self.monitor_snapshot()

    def release_human_control(
        self,
        *,
        connection_id: str,
        lease_id: str,
        aborted: bool = False,
    ) -> HumanControlLeaseState:
        assert self.human_lease is not None
        assert self.human_lease.connection_id == connection_id
        assert self.human_lease.lease_id == lease_id
        released = replace(
            self.human_lease,
            status="aborted" if aborted else "released",
            released_at=datetime.now(timezone.utc),
        )
        self.human_lease = None
        return released

    def release_human_control_connection(self, connection_id: str) -> HumanControlLeaseState | None:
        self.released_connections.append(connection_id)
        if self.human_lease is None or self.human_lease.connection_id != connection_id:
            return None
        return self.release_human_control(
            connection_id=connection_id,
            lease_id=self.human_lease.lease_id,
            aborted=True,
        )

    def human_control_status(self) -> HumanControlLeaseState | None:
        return self.human_lease

    def stop_visual_stream(self, stream_id: str) -> VisualStreamState:
        self.stopped_streams.append(stream_id)
        return VisualStreamState(
            stream_id=stream_id,
            backend_stream_id="backend_test",
            lifecycle="stopped",
            binding=VisualSurfaceBinding(
                session_id="default",
                tab_id="tab_1",
                document_id="doc_1",
            ),
        )

    def close(self) -> None:
        return None


def _wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return bool(predicate())


def _require_managed_chromium() -> None:
    pytest.importorskip("websockets.sync.client")
    try:
        _find_chromium_executable()
    except RuntimeError as exc:
        pytest.skip(str(exc))


def _create_test_app(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_VISUALIZER_CONTROL_TOKEN", CONTROL_TOKEN)
    app = create_app()
    runtime = _FakeMonitorRuntime()
    app.state.browser_runtime = runtime
    return app, runtime


def test_monitor_control_messages_are_not_displaced_by_event_backlog() -> None:
    async def scenario() -> None:
        bridge = _ConnectionBridge(asyncio.get_running_loop(), lambda: {})
        for index in range(300):
            bridge._put_event({"type": "session_event", "index": index})
        bridge.send_control({"type": "human_control_state", "active": True})

        first = await asyncio.wait_for(bridge.next_message(), timeout=1)
        bridge.close()

        assert first == {"type": "human_control_state", "active": True}

    asyncio.run(scenario())


def test_monitor_grant_requires_control_token(monkeypatch, tmp_path) -> None:
    app, _runtime = _create_test_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        denied = client.post("/v1/visualizer/monitor-grants", json={"session_id": "default"})
        allowed = client.post(
            "/v1/visualizer/monitor-grants",
            headers=CONTROL_HEADERS,
            json={"session_id": "default"},
        )

    assert denied.status_code == 403
    assert allowed.status_code == 200
    grant = allowed.json()["grant"]
    assert grant["token"]
    listed = grant.copy()
    assert "token" in listed


def test_monitor_websocket_rejects_untrusted_origin(monkeypatch, tmp_path) -> None:
    app, _runtime = _create_test_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/v1/monitor/ws",
                headers={"origin": "https://evil.example"},
            ):
                pass


def test_invalid_monitor_stream_config_does_not_consume_one_time_token(monkeypatch, tmp_path) -> None:
    app, _runtime = _create_test_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        grant = client.post(
            "/v1/visualizer/monitor-grants",
            headers=CONTROL_HEADERS,
            json={"session_id": "default", "permissions": ["events"]},
        ).json()["grant"]

        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/v1/monitor/ws", headers=ORIGIN_HEADERS) as invalid:
                invalid.send_json({
                    "type": "authenticate",
                    "token": grant["token"],
                    "stream": {"format": "gif"},
                })
                invalid.receive_json()

        with client.websocket_connect("/v1/monitor/ws", headers=ORIGIN_HEADERS) as valid:
            valid.send_json({"type": "authenticate", "token": grant["token"]})
            assert valid.receive_json()["type"] == "monitor_ready"


def test_monitor_websocket_multiplexes_events_and_binary_frames(monkeypatch, tmp_path) -> None:
    app, runtime = _create_test_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        grant = client.post(
            "/v1/visualizer/monitor-grants",
            headers=CONTROL_HEADERS,
            json={"session_id": "default", "permissions": ["events", "frames"]},
        ).json()["grant"]
        with client.websocket_connect("/v1/monitor/ws", headers=ORIGIN_HEADERS) as websocket:
            websocket.send_json({
                "type": "authenticate",
                "token": grant["token"],
                "after_sequence": 0,
                "stream": {"format": "jpeg", "quality": 70},
            })
            ready = websocket.receive_json()
            assert ready["type"] == "monitor_ready"
            assert ready["session_id"] == "default"
            assert ready["snapshot"]["active_agent_id"] == "agent-test"

            event_payload = None
            frame_payload = None
            for _ in range(4):
                message = websocket.receive()
                if message.get("text"):
                    parsed = json.loads(message["text"])
                    if parsed.get("type") == "session_event":
                        event_payload = parsed
                if message.get("bytes"):
                    frame_payload = message["bytes"]
                if event_payload is not None and frame_payload is not None:
                    break

            assert event_payload["event"]["event_type"] == "operation_completed"
            metadata, image = decode_visual_frame_packet(frame_payload)
            assert metadata["document_id"] == "doc_1"
            assert image == b"fake-jpeg"

    assert _wait_until(
        lambda: runtime.unsubscribed == ["sub_test"]
        and runtime.stopped_streams == ["vstream_test"]
    )


def test_active_monitor_connection_is_closed_when_grant_is_revoked(monkeypatch, tmp_path) -> None:
    app, _runtime = _create_test_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        grant = client.post(
            "/v1/visualizer/monitor-grants",
            headers=CONTROL_HEADERS,
            json={"session_id": "default", "permissions": ["events"]},
        ).json()["grant"]
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/v1/monitor/ws", headers=ORIGIN_HEADERS) as websocket:
                websocket.send_json({"type": "authenticate", "token": grant["token"]})
                assert websocket.receive_json()["type"] == "monitor_ready"
                event = websocket.receive_json()
                assert event["type"] == "session_event"
                revoked = client.delete(
                    f"/v1/visualizer/monitor-grants/{grant['grant_id']}",
                    headers=CONTROL_HEADERS,
                )
                assert revoked.status_code == 200
                for _ in range(5):
                    websocket.receive_json()


def test_monitor_human_control_requires_takeover_permission(monkeypatch, tmp_path) -> None:
    app, _runtime = _create_test_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        grant = client.post(
            "/v1/visualizer/monitor-grants",
            headers=CONTROL_HEADERS,
            json={"session_id": "default", "permissions": ["events"]},
        ).json()["grant"]
        with pytest.raises(WebSocketDisconnect) as disconnected:
            with client.websocket_connect("/v1/monitor/ws", headers=ORIGIN_HEADERS) as websocket:
                websocket.send_json({"type": "authenticate", "token": grant["token"]})
                assert websocket.receive_json()["type"] == "monitor_ready"
                websocket.send_json({"type": "human_control_acquire"})
                for _ in range(4):
                    websocket.receive_json()
        assert disconnected.value.code == 4403


def test_monitor_human_control_forwards_input_without_echo_and_releases(monkeypatch, tmp_path) -> None:
    app, runtime = _create_test_app(monkeypatch, tmp_path)
    received_text: list[str] = []
    with TestClient(app) as client:
        grant = client.post(
            "/v1/visualizer/monitor-grants",
            headers=CONTROL_HEADERS,
            json={
                "session_id": "default",
                "permissions": ["events", "frames", "takeover"],
            },
        ).json()["grant"]
        with client.websocket_connect("/v1/monitor/ws", headers=ORIGIN_HEADERS) as websocket:
            websocket.send_json({"type": "authenticate", "token": grant["token"]})
            ready = websocket.receive_json()
            assert ready["type"] == "monitor_ready"
            connection_id = ready["connection_id"]
            websocket.send_json({
                "type": "human_control_acquire",
                "reason": "authentication",
            })
            lease_id = None
            for _ in range(10):
                message = websocket.receive()
                if message.get("text"):
                    received_text.append(message["text"])
                    payload = json.loads(message["text"])
                    if payload.get("type") == "human_control_state" and payload.get("active"):
                        lease_id = payload["lease_id"]
                        break
            assert lease_id == "hlease_test"

            websocket.send_json({
                "type": "human_input",
                "lease_id": lease_id,
                "event": {"type": "insert_text", "text": "super-secret-value"},
            })
            websocket.send_json({
                "type": "human_control_release",
                "lease_id": lease_id,
            })
            released = None
            for _ in range(12):
                message = websocket.receive()
                if message.get("text"):
                    received_text.append(message["text"])
                    payload = json.loads(message["text"])
                    if payload.get("type") == "human_control_state" and payload.get("active") is False:
                        released = payload
                        break
            assert released is not None
            assert runtime.human_inputs[0].text == "super-secret-value"
            assert "super-secret-value" not in "".join(received_text)

        assert connection_id in runtime.released_connections
        assert runtime.human_lease is None


def test_monitor_reports_human_control_becoming_inactive(monkeypatch, tmp_path) -> None:
    app, runtime = _create_test_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        grant = client.post(
            "/v1/visualizer/monitor-grants",
            headers=CONTROL_HEADERS,
            json={
                "session_id": "default",
                "permissions": ["events", "frames", "takeover"],
            },
        ).json()["grant"]
        with client.websocket_connect("/v1/monitor/ws", headers=ORIGIN_HEADERS) as websocket:
            websocket.send_json({"type": "authenticate", "token": grant["token"]})
            assert websocket.receive_json()["type"] == "monitor_ready"
            websocket.send_json({
                "type": "human_control_acquire",
                "reason": "authentication",
            })
            lease_id = None
            for _ in range(12):
                message = websocket.receive()
                if message.get("text"):
                    payload = json.loads(message["text"])
                    if payload.get("type") == "human_control_state" and payload.get("active"):
                        lease_id = payload["lease_id"]
                        break
            assert lease_id == "hlease_test"

            runtime.human_lease = None
            inactive = None
            for _ in range(20):
                message = websocket.receive()
                if message.get("text"):
                    payload = json.loads(message["text"])
                    if payload.get("type") == "human_control_state" and payload.get("active") is False:
                        inactive = payload
                        break
            assert inactive is not None
            assert inactive["lease_id"] == lease_id
            assert inactive["status"] == "inactive"


def test_real_managed_chromium_human_control_pauses_agent_and_uses_same_page(monkeypatch, tmp_path) -> None:
    _require_managed_chromium()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_VISUALIZER_CONTROL_TOKEN", CONTROL_TOKEN)
    monkeypatch.setenv("WEBFA_BROWSER_DRIVER", "managed-chromium")
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    monkeypatch.setenv("WEBFA_PRIVATE_URL_POLICY", "allow")
    reset_engine_for_tests()

    app = create_app()
    agent_headers = {"X-WebFA-Agent-Id": "human-control-agent"}
    with TestClient(app) as client:
        opened = client.post(
            "/v1/browser/web/open",
            headers=agent_headers,
            json={"url": HUMAN_CONTROL_PAGE.as_uri()},
        )
        assert opened.status_code == 200, opened.text
        opened_state = opened.json()["state"]
        document_id = opened_state["document_id"]
        password = next(
            item
            for item in opened_state["objects"]
            if item.get("capabilities") == ["request_human_takeover"]
        )
        takeover_requested = client.post(
            "/v1/browser/web/act",
            headers=agent_headers,
            json={
                "target": password["id"],
                "operation": "request_human_takeover",
                "arguments": {},
            },
        )
        assert takeover_requested.status_code == 200, takeover_requested.text
        assert takeover_requested.json()["state"]["takeover"]["required"] is True

        grant = client.post(
            "/v1/visualizer/monitor-grants",
            headers=CONTROL_HEADERS,
            json={
                "session_id": "default",
                "permissions": ["events", "frames", "takeover"],
            },
        ).json()["grant"]

        with client.websocket_connect("/v1/monitor/ws", headers=ORIGIN_HEADERS) as websocket:
            websocket.send_json({
                "type": "authenticate",
                "token": grant["token"],
                "stream": {"format": "jpeg", "quality": 60, "max_width": 800, "max_height": 600},
            })
            ready = websocket.receive_json()
            assert ready["snapshot"]["document_id"] == document_id
            assert ready["snapshot"]["takeover_required"] is True
            assert ready["visual_error"] is None
            frame_seen = False
            for _ in range(30):
                message = websocket.receive()
                if message.get("bytes"):
                    frame_seen = True
                    break
            assert frame_seen, "takeover must retain the same BrowserHost visual surface"

            websocket.send_json({
                "type": "human_control_acquire",
                "reason": "authentication",
            })
            lease_id = None
            for _ in range(20):
                message = websocket.receive()
                if message.get("text"):
                    payload = json.loads(message["text"])
                    if payload.get("type") == "human_control_state" and payload.get("active"):
                        lease_id = payload["lease_id"]
                        break
            assert lease_id

            blocked = client.post(
                "/v1/browser/web/open",
                headers=agent_headers,
                json={"url": HUMAN_CONTROL_PAGE.as_uri()},
            )
            assert blocked.status_code == 409, blocked.text
            assert blocked.json()["detail"]["code"] == "human_control_active"
            restart_blocked = client.post(
                "/v1/visualizer/restart-host",
                headers=CONTROL_HEADERS,
            )
            assert restart_blocked.status_code == 409, restart_blocked.text
            assert restart_blocked.json()["detail"]["code"] == "human_control_active"

            websocket.send_json({
                "type": "human_input",
                "lease_id": lease_id,
                "event": {"type": "insert_text", "text": "human-secret"},
            })
            websocket.send_json({
                "type": "human_input",
                "lease_id": lease_id,
                "event": {"type": "key_down", "key": "Enter", "code": "Enter"},
            })
            websocket.send_json({
                "type": "human_input",
                "lease_id": lease_id,
                "event": {"type": "key_up", "key": "Enter", "code": "Enter"},
            })
            websocket.send_json({"type": "ping"})
            for _ in range(20):
                message = websocket.receive()
                if message.get("text") and json.loads(message["text"]).get("type") == "pong":
                    break

            takeover_observe = client.post(
                "/v1/browser/web/observe",
                headers=agent_headers,
                json={"mode": "page", "detail": "summary", "limit": 20},
            )
            assert takeover_observe.status_code == 200, takeover_observe.text
            assert takeover_observe.json()["document_id"] == "human_takeover"
            assert takeover_observe.json()["takeover"]["required"] is True
            assert "human-secret" not in takeover_observe.text

            websocket.send_json({
                "type": "human_control_release",
                "lease_id": lease_id,
            })
            for _ in range(20):
                message = websocket.receive()
                if message.get("text"):
                    payload = json.loads(message["text"])
                    if payload.get("type") == "human_control_state" and payload.get("active") is False:
                        break

        result = client.post(
            "/v1/browser/web/observe",
            headers=agent_headers,
            json={
                "mode": "query",
                "query": {"text_contains": "Confirmed"},
                "detail": "full",
                "limit": 20,
            },
        )
        assert result.status_code == 200, result.text
        assert result.json()["objects"]
        assert result.json()["document_id"] == document_id

        runtime = app.state.browser_runtime
        serialized_events = str(
            [event.data for event in runtime.replay_session_events(session_id="default", limit=200)]
        )
        assert "human-secret" not in serialized_events
        visualizer = client.get("/v1/visualizer/state", headers=CONTROL_HEADERS)
        assert visualizer.status_code == 200, visualizer.text
        assert "human-secret" not in visualizer.text


def test_real_managed_chromium_monitor_gateway_streams_same_runtime_page(monkeypatch, tmp_path) -> None:
    _require_managed_chromium()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_VISUALIZER_CONTROL_TOKEN", CONTROL_TOKEN)
    monkeypatch.setenv("WEBFA_BROWSER_DRIVER", "managed-chromium")
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    monkeypatch.setenv("WEBFA_PRIVATE_URL_POLICY", "allow")
    reset_engine_for_tests()

    app = create_app()
    agent_headers = {"X-WebFA-Agent-Id": "monitor-real-agent"}
    with TestClient(app) as client:
        opened = client.post(
            "/v1/browser/web/open",
            headers=agent_headers,
            json={"url": f"{FIXTURE_PAGE.as_uri()}?token=must-not-leak"},
        )
        assert opened.status_code == 200, opened.text
        document_id = opened.json()["state"]["document_id"]
        grant = client.post(
            "/v1/visualizer/monitor-grants",
            headers=CONTROL_HEADERS,
            json={"session_id": "default", "permissions": ["events", "frames"]},
        ).json()["grant"]

        frame_packet = None
        with client.websocket_connect("/v1/monitor/ws", headers=ORIGIN_HEADERS) as websocket:
            websocket.send_json({
                "type": "authenticate",
                "token": grant["token"],
                "stream": {"format": "jpeg", "quality": 60, "max_width": 800, "max_height": 600},
            })
            ready = websocket.receive_json()
            assert ready["type"] == "monitor_ready"
            assert ready["snapshot"]["document_id"] == document_id
            assert "token=" not in ready["snapshot"]["url"]
            for _ in range(30):
                message = websocket.receive()
                if message.get("bytes"):
                    frame_packet = message["bytes"]
                    break

        assert frame_packet is not None
        metadata, image = decode_visual_frame_packet(frame_packet)
        assert metadata["session_id"] == grant["session_id"]
        assert metadata["document_id"] == document_id
        assert image.startswith(b"\xff\xd8")

        observed = client.post(
            "/v1/browser/web/observe",
            headers=agent_headers,
            json={"mode": "page", "detail": "summary", "limit": 20},
        )
        assert observed.status_code == 200, observed.text
        assert observed.json()["document_id"] == document_id


def test_monitor_token_cannot_be_reused(monkeypatch, tmp_path) -> None:
    app, _runtime = _create_test_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        grant = client.post(
            "/v1/visualizer/monitor-grants",
            headers=CONTROL_HEADERS,
            json={"session_id": "default", "permissions": ["events"]},
        ).json()["grant"]
        with client.websocket_connect("/v1/monitor/ws", headers=ORIGIN_HEADERS) as websocket:
            websocket.send_json({"type": "authenticate", "token": grant["token"]})
            assert websocket.receive_json()["type"] == "monitor_ready"

        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/v1/monitor/ws", headers=ORIGIN_HEADERS) as reused:
                reused.send_json({"type": "authenticate", "token": grant["token"]})
                reused.receive_json()
