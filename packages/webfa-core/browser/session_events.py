from __future__ import annotations

import copy
import queue
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Literal
from uuid import uuid4

SessionEventType = Literal[
    "session_started",
    "session_closed",
    "navigation_started",
    "navigation_committed",
    "navigation_failed",
    "loading_changed",
    "document_changed",
    "tab_created",
    "tab_switched",
    "tab_closed",
    "operation_started",
    "operation_completed",
    "operation_failed",
    "safety_decision_changed",
    "takeover_required",
    "takeover_started",
    "takeover_finished",
    "visual_stream_started",
    "visual_stream_stopped",
    "frame_available",
    "browser_crashed",
]

SessionEventData = dict[str, Any]
SessionEventCallback = Callable[["SessionEvent"], None]

_SENSITIVE_KEYS = {
    "password",
    "passwd",
    "cookie",
    "cookies",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "otp",
    "one_time_code",
    "two_factor_code",
    "secret",
    "cvv",
    "cvc",
    "card_number",
    "payment_password",
    "wallet_token",
    "file_path",
    "local_path",
    "raw_html",
    "html",
    "dom",
}


@dataclass(frozen=True, slots=True)
class SessionEvent:
    event_id: str
    sequence: int
    session_id: str
    type: SessionEventType
    timestamp: datetime
    tab_id: str | None = None
    document_id: str | None = None
    operation_id: str | None = None
    data: SessionEventData = field(default_factory=dict)


class _Subscriber:
    def __init__(
        self,
        callback: SessionEventCallback,
        *,
        initial: list[SessionEvent],
        queue_size: int,
        name: str,
        session_id: str | None = None,
    ) -> None:
        self.callback = callback
        self.session_id = session_id
        self.queue: queue.Queue[SessionEvent | None] = queue.Queue(maxsize=max(8, queue_size))
        self.thread = threading.Thread(target=self._run, name=name, daemon=True)
        for event in initial[-self.queue.maxsize :]:
            self.queue.put_nowait(event)
        self.thread.start()

    def enqueue(self, event: SessionEvent) -> None:
        if self.session_id is not None and event.session_id != self.session_id:
            return
        try:
            self.queue.put_nowait(event)
            return
        except queue.Full:
            pass
        try:
            self.queue.get_nowait()
        except queue.Empty:
            pass
        try:
            self.queue.put_nowait(event)
        except queue.Full:
            pass

    def close(self) -> None:
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
            self.thread.join(timeout=2)

    def _run(self) -> None:
        while True:
            item = self.queue.get()
            if item is None:
                return
            try:
                self.callback(item)
            except Exception:
                # A Monitor subscriber must never break Runtime execution.
                continue


class SessionEventBus:
    """Thread-safe ordered event journal with bounded replay and live subscribers."""

    def __init__(self, *, max_events: int = 1000, subscriber_queue_size: int = 256) -> None:
        if max_events < 1:
            raise ValueError("max_events must be positive")
        if subscriber_queue_size < 8:
            raise ValueError("subscriber_queue_size must be at least 8")
        self._events: deque[SessionEvent] = deque(maxlen=max_events)
        self._subscribers: dict[str, _Subscriber] = {}
        self._subscriber_queue_size = subscriber_queue_size
        self._sequence = 0
        self._closed = False
        self._lock = threading.RLock()

    def publish(
        self,
        event_type: SessionEventType,
        *,
        session_id: str,
        tab_id: str | None = None,
        document_id: str | None = None,
        operation_id: str | None = None,
        data: SessionEventData | None = None,
    ) -> SessionEvent:
        safe_data = _copy_and_validate_data(data or {})
        with self._lock:
            if self._closed:
                raise RuntimeError("session event bus is closed")
            self._sequence += 1
            event = SessionEvent(
                event_id=f"sevt_{uuid4().hex}",
                sequence=self._sequence,
                session_id=session_id,
                type=event_type,
                timestamp=datetime.now(timezone.utc),
                tab_id=tab_id,
                document_id=document_id,
                operation_id=operation_id,
                data=safe_data,
            )
            self._events.append(event)
            subscribers = tuple(self._subscribers.values())
        for subscriber in subscribers:
            subscriber.enqueue(event)
        return event

    def replay(
        self,
        *,
        after_sequence: int = 0,
        session_id: str | None = None,
        limit: int = 200,
    ) -> list[SessionEvent]:
        if after_sequence < 0:
            raise ValueError("after_sequence cannot be negative")
        if limit < 1:
            raise ValueError("limit must be positive")
        with self._lock:
            items = [
                event
                for event in self._events
                if event.sequence > after_sequence
                and (session_id is None or event.session_id == session_id)
            ]
        return items[: min(limit, 1000)]

    def subscribe(
        self,
        callback: SessionEventCallback,
        *,
        replay_after_sequence: int | None = None,
        session_id: str | None = None,
    ) -> str:
        if not callable(callback):
            raise TypeError("callback must be callable")
        with self._lock:
            if self._closed:
                raise RuntimeError("session event bus is closed")
            initial = []
            if replay_after_sequence is not None:
                initial = [
                    event
                    for event in self._events
                    if event.sequence > replay_after_sequence
                    and (session_id is None or event.session_id == session_id)
                ]
            subscription_id = f"sub_{uuid4().hex}"
            subscriber = _Subscriber(
                callback,
                initial=initial,
                queue_size=self._subscriber_queue_size,
                name=f"webfa-session-events-{subscription_id[-8:]}",
                session_id=session_id,
            )
            self._subscribers[subscription_id] = subscriber
            return subscription_id

    def unsubscribe(self, subscription_id: str) -> bool:
        with self._lock:
            subscriber = self._subscribers.pop(subscription_id, None)
        if subscriber is None:
            return False
        subscriber.close()
        return True

    @property
    def latest_sequence(self) -> int:
        with self._lock:
            return self._sequence

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            subscribers = tuple(self._subscribers.values())
            self._subscribers.clear()
        for subscriber in subscribers:
            subscriber.close()


def _copy_and_validate_data(value: SessionEventData) -> SessionEventData:
    _validate_value(value, path="data")
    return copy.deepcopy(value)


def _validate_value(value: Any, *, path: str) -> None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return
    if isinstance(value, bytes):
        raise ValueError(f"{path} must not contain binary frame data")
    if isinstance(value, list) or isinstance(value, tuple):
        for index, item in enumerate(value):
            _validate_value(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key).lower()
            if key_text in _SENSITIVE_KEYS:
                raise ValueError(f"{path}.{key} is not allowed in session event data")
            _validate_value(item, path=f"{path}.{key}")
        return
    raise ValueError(f"{path} contains unsupported value type {type(value).__name__}")
