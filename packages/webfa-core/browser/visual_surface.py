from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Literal, Protocol
from uuid import uuid4

from browser.session_events import SessionEventBus

VisualFrameFormat = Literal["jpeg", "webp", "png"]
VisualStreamLifecycle = Literal["starting", "running", "stopped", "failed"]


@dataclass(frozen=True, slots=True)
class VisualStreamConfig:
    format: VisualFrameFormat = "jpeg"
    quality: int = 70
    max_width: int = 1280
    max_height: int = 720
    every_nth_frame: int = 1
    delivery_queue_size: int = 3

    def __post_init__(self) -> None:
        if self.format not in {"jpeg", "webp", "png"}:
            raise ValueError("unsupported visual frame format")
        for name, value in (
            ("quality", self.quality),
            ("max_width", self.max_width),
            ("max_height", self.max_height),
            ("every_nth_frame", self.every_nth_frame),
            ("delivery_queue_size", self.delivery_queue_size),
        ):
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{name} must be an integer")
        if not 0 <= self.quality <= 100:
            raise ValueError("quality must be between 0 and 100")
        if not 1 <= self.max_width <= 8192 or not 1 <= self.max_height <= 8192:
            raise ValueError("visual stream dimensions must be between 1 and 8192")
        if not 1 <= self.every_nth_frame <= 120:
            raise ValueError("every_nth_frame must be between 1 and 120")
        if self.delivery_queue_size < 1 or self.delivery_queue_size > 32:
            raise ValueError("delivery_queue_size must be between 1 and 32")


@dataclass(frozen=True, slots=True)
class VisualSurfaceBinding:
    session_id: str
    tab_id: str
    document_id: str


@dataclass(frozen=True, slots=True)
class HostVisualFrame:
    data: bytes
    format: VisualFrameFormat
    width: int
    height: int
    device_scale_factor: float
    scroll_offset_x: float
    scroll_offset_y: float
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    host_target_id: str | None = None
    host_frame_id: str | None = None


@dataclass(frozen=True, slots=True)
class VisualFrame:
    stream_id: str
    frame_seq: int
    session_id: str
    tab_id: str
    document_id: str
    data: bytes
    format: VisualFrameFormat
    width: int
    height: int
    device_scale_factor: float
    scroll_offset_x: float
    scroll_offset_y: float
    captured_at: datetime
    host_target_id: str | None = None
    host_frame_id: str | None = None


@dataclass(frozen=True, slots=True)
class HostVisualStreamState:
    backend_stream_id: str
    lifecycle: VisualStreamLifecycle
    visible: bool = True
    frames_received: int = 0
    frames_dropped: int = 0
    last_error: str | None = None


@dataclass(frozen=True, slots=True)
class VisualStreamState:
    stream_id: str
    backend_stream_id: str
    lifecycle: VisualStreamLifecycle
    binding: VisualSurfaceBinding
    frames_received: int = 0
    frames_delivered: int = 0
    frames_dropped: int = 0
    last_error: str | None = None


HostFrameSink = Callable[[HostVisualFrame], None]
VisualFrameSink = Callable[[VisualFrame], None]
VisualBindingProvider = Callable[[], VisualSurfaceBinding]


class VisualSurfaceBackend(Protocol):
    def start_screencast(self, config: VisualStreamConfig, frame_sink: HostFrameSink) -> str: ...

    def stop_screencast(self, backend_stream_id: str) -> HostVisualStreamState: ...

    def screencast_status(self, backend_stream_id: str | None = None) -> HostVisualStreamState | None: ...


class VisualSurfaceProvider(Protocol):
    def start_stream(
        self,
        binding_provider: VisualBindingProvider,
        config: VisualStreamConfig,
        frame_sink: VisualFrameSink,
    ) -> str: ...

    def stop_stream(self, stream_id: str) -> VisualStreamState: ...

    def status(self, stream_id: str | None = None) -> VisualStreamState | None: ...

    def close(self) -> None: ...


class _StreamDelivery:
    def __init__(
        self,
        *,
        stream_id: str,
        backend_stream_id: str,
        binding_provider: VisualBindingProvider,
        frame_sink: VisualFrameSink,
        queue_size: int,
        event_bus: SessionEventBus | None,
    ) -> None:
        self.stream_id = stream_id
        self.backend_stream_id = backend_stream_id
        self.binding_provider = binding_provider
        self.frame_sink = frame_sink
        self.event_bus = event_bus
        self.queue: queue.Queue[tuple[HostVisualFrame, VisualSurfaceBinding] | None] = queue.Queue(maxsize=queue_size)
        self.lock = threading.RLock()
        self.lifecycle: VisualStreamLifecycle = "starting"
        self.frames_received = 0
        self.frames_delivered = 0
        self.frames_dropped = 0
        self.frame_seq = 0
        self.last_error: str | None = None
        self.last_frame_event_at = 0.0
        self.last_frame_event_binding: VisualSurfaceBinding | None = None
        self.thread = threading.Thread(
            target=self._run,
            name=f"webfa-visual-delivery-{stream_id[-8:]}",
            daemon=True,
        )
        self.thread.start()

    def accept(self, frame: HostVisualFrame) -> None:
        binding = self.binding_provider()
        queued = (frame, binding)
        with self.lock:
            self.frames_received += 1
        try:
            self.queue.put_nowait(queued)
            return
        except queue.Full:
            pass
        try:
            self.queue.get_nowait()
        except queue.Empty:
            pass
        with self.lock:
            self.frames_dropped += 1
        try:
            self.queue.put_nowait(queued)
        except queue.Full:
            with self.lock:
                self.frames_dropped += 1

    def stop(self) -> None:
        with self.lock:
            if self.lifecycle != "failed":
                self.lifecycle = "stopped"
        try:
            self.queue.put_nowait(None)
        except queue.Full:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.queue.put_nowait(None)
            except queue.Full:
                return
        if threading.current_thread() is not self.thread:
            self.thread.join(timeout=3)

    def state(self) -> VisualStreamState:
        with self.lock:
            binding = self.binding_provider()
            return VisualStreamState(
                stream_id=self.stream_id,
                backend_stream_id=self.backend_stream_id,
                lifecycle=self.lifecycle,
                binding=binding,
                frames_received=self.frames_received,
                frames_delivered=self.frames_delivered,
                frames_dropped=self.frames_dropped,
                last_error=self.last_error,
            )

    def _run(self) -> None:
        with self.lock:
            self.lifecycle = "running"
        while True:
            item = self.queue.get()
            if item is None:
                return
            host_frame, binding = item
            try:
                with self.lock:
                    self.frame_seq += 1
                    frame_seq = self.frame_seq
                frame = VisualFrame(
                    stream_id=self.stream_id,
                    frame_seq=frame_seq,
                    session_id=binding.session_id,
                    tab_id=binding.tab_id,
                    document_id=binding.document_id,
                    data=host_frame.data,
                    format=host_frame.format,
                    width=host_frame.width,
                    height=host_frame.height,
                    device_scale_factor=host_frame.device_scale_factor,
                    scroll_offset_x=host_frame.scroll_offset_x,
                    scroll_offset_y=host_frame.scroll_offset_y,
                    captured_at=host_frame.captured_at,
                    host_target_id=host_frame.host_target_id,
                    host_frame_id=host_frame.host_frame_id,
                )
                self.frame_sink(frame)
                with self.lock:
                    self.frames_delivered += 1
                now = time.monotonic()
                if self.event_bus is not None and (
                    frame_seq == 1
                    or binding != self.last_frame_event_binding
                    or now - self.last_frame_event_at >= 1.0
                ):
                    self.last_frame_event_at = now
                    self.last_frame_event_binding = binding
                    self.event_bus.publish(
                        "frame_available",
                        session_id=binding.session_id,
                        tab_id=binding.tab_id,
                        document_id=binding.document_id,
                        data={
                            "stream_id": self.stream_id,
                            "frame_seq": frame_seq,
                            "format": host_frame.format,
                            "width": host_frame.width,
                            "height": host_frame.height,
                            "device_scale_factor": host_frame.device_scale_factor,
                        },
                    )
            except Exception as exc:
                with self.lock:
                    self.last_error = str(exc)
                # A slow or failing Monitor sink must not stop the host screencast.
                continue


class BoundVisualSurfaceProvider:
    """Runtime-owned provider that binds host frames to Session/Tab/Document identity."""

    def __init__(self, backend: VisualSurfaceBackend, *, event_bus: SessionEventBus | None = None) -> None:
        self._backend = backend
        self._event_bus = event_bus
        self._streams: dict[str, _StreamDelivery] = {}
        self._lock = threading.RLock()
        self._closed = False

    def start_stream(
        self,
        binding_provider: VisualBindingProvider,
        config: VisualStreamConfig,
        frame_sink: VisualFrameSink,
    ) -> str:
        with self._lock:
            if self._closed:
                raise RuntimeError("visual surface provider is closed")
            if self._streams:
                raise RuntimeError("only one visual stream is supported per BrowserHost in this phase")
            stream_id = f"vstream_{uuid4().hex}"
            delivery = _StreamDelivery(
                stream_id=stream_id,
                backend_stream_id="starting",
                binding_provider=binding_provider,
                frame_sink=frame_sink,
                queue_size=config.delivery_queue_size,
                event_bus=self._event_bus,
            )
            try:
                backend_stream_id = self._backend.start_screencast(config, delivery.accept)
            except Exception:
                delivery.stop()
                raise
            delivery.backend_stream_id = backend_stream_id
            self._streams[stream_id] = delivery
            binding = binding_provider()
        if self._event_bus is not None:
            self._event_bus.publish(
                "visual_stream_started",
                session_id=binding.session_id,
                tab_id=binding.tab_id,
                document_id=binding.document_id,
                data={
                    "stream_id": stream_id,
                    "format": config.format,
                    "max_width": config.max_width,
                    "max_height": config.max_height,
                },
            )
        return stream_id

    def stop_stream(self, stream_id: str) -> VisualStreamState:
        with self._lock:
            delivery = self._streams.pop(stream_id, None)
            if delivery is None:
                raise KeyError(f"visual stream not found: {stream_id}")
        try:
            self._backend.stop_screencast(delivery.backend_stream_id)
        finally:
            delivery.stop()
        state = delivery.state()
        if self._event_bus is not None:
            binding = state.binding
            self._event_bus.publish(
                "visual_stream_stopped",
                session_id=binding.session_id,
                tab_id=binding.tab_id,
                document_id=binding.document_id,
                data={
                    "stream_id": stream_id,
                    "frames_received": state.frames_received,
                    "frames_delivered": state.frames_delivered,
                    "frames_dropped": state.frames_dropped,
                },
            )
        return state

    def status(self, stream_id: str | None = None) -> VisualStreamState | None:
        with self._lock:
            if stream_id is None:
                if not self._streams:
                    return None
                delivery = next(iter(self._streams.values()))
            else:
                delivery = self._streams.get(stream_id)
            return delivery.state() if delivery is not None else None

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            stream_ids = tuple(self._streams)
        for stream_id in stream_ids:
            try:
                self.stop_stream(stream_id)
            except Exception:
                continue
