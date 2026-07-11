from __future__ import annotations

import threading
import time

import pytest

from browser.session_events import SessionEventBus


def test_session_event_bus_orders_replays_and_filters_by_session() -> None:
    bus = SessionEventBus(max_events=10)
    first = bus.publish("session_started", session_id="session-a")
    second = bus.publish(
        "navigation_started",
        session_id="session-a",
        data={"origin": "https://example.com"},
    )
    bus.publish("session_started", session_id="session-b")

    replay = bus.replay(after_sequence=first.sequence, session_id="session-a")

    assert [event.sequence for event in replay] == [second.sequence]
    assert replay[0].data == {"origin": "https://example.com"}
    bus.close()


def test_session_event_bus_live_subscriber_isolated_from_callback_failure() -> None:
    bus = SessionEventBus(max_events=10)
    received = []
    delivered = threading.Event()

    def broken_callback(event) -> None:
        received.append(event.sequence)
        delivered.set()
        raise RuntimeError("monitor disconnected")

    subscription_id = bus.subscribe(broken_callback)
    started = time.monotonic()
    event = bus.publish("session_started", session_id="default")
    elapsed = time.monotonic() - started

    assert elapsed < 0.2
    assert delivered.wait(timeout=2)
    assert received == [event.sequence]
    assert bus.unsubscribe(subscription_id) is True
    assert bus.unsubscribe(subscription_id) is False
    bus.close()


def test_session_event_bus_rejects_binary_and_sensitive_payloads() -> None:
    bus = SessionEventBus()

    with pytest.raises(ValueError, match="binary frame data"):
        bus.publish("frame_available", session_id="default", data={"frame": b"jpeg"})

    with pytest.raises(ValueError, match="not allowed"):
        bus.publish("operation_completed", session_id="default", data={"access_token": "secret"})

    bus.close()
