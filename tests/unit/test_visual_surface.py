from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from browser.session_events import SessionEventBus
from browser.visual_surface import (
    BoundVisualSurfaceProvider,
    HostVisualFrame,
    HostVisualStreamState,
    VisualStreamConfig,
    VisualSurfaceBinding,
)


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
