from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from apps.runtime.main import create_app
from browser.managed_chromium_host import _find_chromium_executable
from browser.monitor_gateway import decode_visual_frame_packet
from browser.session_events import SessionEvent
from browser.visual_surface import VisualFrame, VisualStreamState, VisualSurfaceBinding
from storage.db import reset_engine_for_tests

CONTROL_TOKEN = "monitor-control-test-token"
CONTROL_HEADERS = {"X-WebFA-Visualizer-Token": CONTROL_TOKEN}
ORIGIN_HEADERS = {"origin": "http://127.0.0.1:8788"}
FIXTURE_PAGE = Path(__file__).resolve().parents[1] / "fixtures" / "agent_validation_page.html"


class _FakeMonitorRuntime:
    def __init__(self) -> None:
        self.subscription_callback = None
        self.stopped_streams: list[str] = []
        self.unsubscribed: list[str] = []

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
            "takeover_reason": None,
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

    assert runtime.unsubscribed == ["sub_test"]
    assert runtime.stopped_streams == ["vstream_test"]


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
        assert metadata["session_id"] == "default"
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
