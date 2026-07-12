from __future__ import annotations

import threading
import time

import pytest
from datetime import datetime, timezone

from browser.session_events import SessionEventBus
from browser.visual_surface import (
    BoundVisualSurfaceProvider,
    HostVisualFrame,
    HostVisualStreamState,
    VisualStreamConfig,
    VisualSurfaceBinding,
)


def test_visual_stream_config_rejects_unsafe_values() -> None:
    with pytest.raises(ValueError):
        VisualStreamConfig(max_width=100_000)
    with pytest.raises(ValueError):
        VisualStreamConfig(max_height=0)
    with pytest.raises(ValueError):
        VisualStreamConfig(every_nth_frame=121)
    with pytest.raises(ValueError):
        VisualStreamConfig(quality=True)  # type: ignore[arg-type]


class FakeVisualBackend:
    def __init__(self) -> None:
        self.sink = None
        self.stream_id = "backend-1"
        self.stopped = False

    def start_screencast(self, config, frame_sink):
        self.sink = frame_sink
        return self.stream_id

    def stop_screencast(self, backend_stream_id):
        assert backend_stream_id == self.stream_id
        self.stopped = True
        return HostVisualStreamState(backend_stream_id=self.stream_id, lifecycle="stopped")

    def screencast_status(self, backend_stream_id=None):
        return HostVisualStreamState(
            backend_stream_id=self.stream_id,
            lifecycle="stopped" if self.stopped else "running",
        )

    def emit(self, data: bytes = b"jpeg-frame") -> None:
        assert self.sink is not None
        self.sink(
            HostVisualFrame(
                data=data,
                format="jpeg",
                width=800,
                height=450,
                device_scale_factor=1.0,
                scroll_offset_x=0,
                scroll_offset_y=10,
                captured_at=datetime.now(timezone.utc),
                host_target_id="target-1",
            )
        )


def test_visual_surface_provider_stamps_current_binding_and_emits_metadata_event() -> None:
    backend = FakeVisualBackend()
    bus = SessionEventBus()
    binding = [VisualSurfaceBinding("session-1", "tab-1", "doc-1")]
    received = []
    delivered = threading.Event()

    provider = BoundVisualSurfaceProvider(backend, event_bus=bus)
    stream_id = provider.start_stream(
        lambda: binding[0],
        VisualStreamConfig(delivery_queue_size=2),
        lambda frame: (received.append(frame), delivered.set()),
    )

    binding[0] = VisualSurfaceBinding("session-1", "tab-1", "doc-2")
    backend.emit()

    assert delivered.wait(timeout=2)
    assert received[0].stream_id == stream_id
    assert received[0].document_id == "doc-2"
    assert received[0].data == b"jpeg-frame"
    events = bus.replay(session_id="session-1")
    frame_event = next(event for event in events if event.type == "frame_available")
    assert frame_event.document_id == "doc-2"
    assert "data" not in frame_event.data

    state = provider.stop_stream(stream_id)
    assert state.lifecycle == "stopped"
    assert state.frames_received == 1
    assert state.frames_delivered == 1
    assert backend.stopped is True
    provider.close()
    bus.close()


def test_visual_surface_provider_preserves_binding_captured_with_delayed_frame() -> None:
    backend = FakeVisualBackend()
    binding = [VisualSurfaceBinding("session-1", "tab-1", "doc-old")]
    received = []
    first_entered = threading.Event()
    release_first = threading.Event()
    second_delivered = threading.Event()

    def slow_first_sink(frame) -> None:
        received.append(frame)
        if len(received) == 1:
            first_entered.set()
            release_first.wait(timeout=2)
        else:
            second_delivered.set()

    provider = BoundVisualSurfaceProvider(backend)
    stream_id = provider.start_stream(
        lambda: binding[0],
        VisualStreamConfig(delivery_queue_size=3),
        slow_first_sink,
    )

    backend.emit(b"frame-1")
    assert first_entered.wait(timeout=1)
    backend.emit(b"frame-2")
    binding[0] = VisualSurfaceBinding("session-1", "tab-1", "doc-new")
    release_first.set()

    assert second_delivered.wait(timeout=2)
    assert received[1].data == b"frame-2"
    assert received[1].document_id == "doc-old"

    provider.stop_stream(stream_id)
    provider.close()


def test_visual_surface_provider_throttles_frame_journal_events(monkeypatch) -> None:
    now = [100.0]
    monkeypatch.setattr("browser.visual_surface.time.monotonic", lambda: now[0])
    backend = FakeVisualBackend()
    bus = SessionEventBus()
    delivered = threading.Event()
    second_document_delivered = threading.Event()
    count = [0]
    binding = [VisualSurfaceBinding("session-1", "tab-1", "doc-1")]

    def sink(_frame) -> None:
        count[0] += 1
        if count[0] == 5:
            delivered.set()
        if count[0] == 6:
            second_document_delivered.set()

    provider = BoundVisualSurfaceProvider(backend, event_bus=bus)
    stream_id = provider.start_stream(
        lambda: binding[0],
        VisualStreamConfig(delivery_queue_size=8),
        sink,
    )
    for index in range(5):
        backend.emit(f"frame-{index}".encode())

    assert delivered.wait(timeout=2)
    frame_events = [
        event
        for event in bus.replay(session_id="session-1", limit=100)
        if event.type == "frame_available"
    ]
    assert len(frame_events) == 1
    assert frame_events[0].data["frame_seq"] == 1

    binding[0] = VisualSurfaceBinding("session-1", "tab-1", "doc-2")
    backend.emit(b"frame-new-document")
    assert second_document_delivered.wait(timeout=2)
    frame_events = [
        event
        for event in bus.replay(session_id="session-1", limit=100)
        if event.type == "frame_available"
    ]
    assert len(frame_events) == 2
    assert frame_events[-1].document_id == "doc-2"

    provider.stop_stream(stream_id)
    provider.close()
    bus.close()


def test_visual_surface_provider_does_not_block_backend_on_slow_sink() -> None:
    backend = FakeVisualBackend()
    release = threading.Event()
    entered = threading.Event()

    def slow_sink(frame) -> None:
        entered.set()
        release.wait(timeout=2)

    provider = BoundVisualSurfaceProvider(backend)
    stream_id = provider.start_stream(
        lambda: VisualSurfaceBinding("session-1", "tab-1", "doc-1"),
        VisualStreamConfig(delivery_queue_size=1),
        slow_sink,
    )

    started = time.monotonic()
    backend.emit(b"frame-1")
    assert entered.wait(timeout=1)
    for index in range(10):
        backend.emit(f"frame-{index + 2}".encode())
    elapsed = time.monotonic() - started

    assert elapsed < 0.25
    release.set()
    time.sleep(0.1)
    state = provider.stop_stream(stream_id)
    assert state.frames_received == 11
    assert state.frames_dropped > 0
    provider.close()
