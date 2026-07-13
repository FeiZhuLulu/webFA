from __future__ import annotations

import time
from datetime import datetime, timezone

from browser.visual_surface import (
    BoundVisualSurfaceProvider,
    HostVisualFrame,
    HostVisualStreamState,
    VisualStreamConfig,
    VisualSurfaceBinding,
)


class FakeVisualBackend:
    def __init__(self) -> None:
        self.start_calls = 0
        self.stop_calls = 0
        self.sink = None
        self.backend_stream_id = "backend-1"

    def start_screencast(self, config, frame_sink):
        self.start_calls += 1
        self.sink = frame_sink
        return self.backend_stream_id

    def stop_screencast(self, backend_stream_id):
        assert backend_stream_id == self.backend_stream_id
        self.stop_calls += 1
        return HostVisualStreamState(
            backend_stream_id=backend_stream_id,
            lifecycle="stopped",
        )

    def screencast_status(self, backend_stream_id=None):
        return HostVisualStreamState(
            backend_stream_id=backend_stream_id or self.backend_stream_id,
            lifecycle="running",
        )

    def emit(self) -> None:
        assert self.sink is not None
        self.sink(
            HostVisualFrame(
                data=b"frame",
                format="jpeg",
                width=100,
                height=50,
                device_scale_factor=1.0,
                scroll_offset_x=0.0,
                scroll_offset_y=0.0,
                captured_at=datetime.now(timezone.utc),
            )
        )


def test_visual_stream_hub_fans_out_one_backend_stream_to_multiple_consumers() -> None:
    backend = FakeVisualBackend()
    provider = BoundVisualSurfaceProvider(backend)
    binding = lambda: VisualSurfaceBinding(
        session_id="session-a",
        tab_id="tab-a",
        document_id="document-a",
    )
    first = []
    second = []
    config = VisualStreamConfig(quality=60, max_width=800, max_height=600)

    stream_a = provider.start_stream(binding, config, first.append)
    stream_b = provider.start_stream(binding, config, second.append)

    assert backend.start_calls == 1
    assert provider.consumer_count() == 2

    backend.emit()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and (not first or not second):
        time.sleep(0.01)

    assert len(first) == 1
    assert len(second) == 1
    assert first[0].session_id == "session-a"
    assert second[0].document_id == "document-a"

    provider.stop_stream(stream_a)
    assert backend.stop_calls == 0
    assert provider.consumer_count() == 1

    provider.stop_stream(stream_b)
    assert backend.stop_calls == 1
    assert provider.consumer_count() == 0
