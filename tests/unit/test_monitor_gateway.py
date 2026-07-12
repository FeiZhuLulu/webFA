from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from browser.monitor_gateway import (
    MonitorAccessError,
    MonitorAccessManager,
    decode_visual_frame_packet,
    encode_visual_frame_packet,
    serialize_session_event,
)
from browser.session_events import SessionEvent
from browser.visual_surface import VisualFrame


def test_monitor_token_is_one_time_and_session_scoped() -> None:
    manager = MonitorAccessManager()
    issued = manager.issue(session_id="session-a", permissions=("events", "frames"), ttl_seconds=60)

    consumed = manager.consume(issued.token)

    assert consumed.session_id == "session-a"
    assert consumed.permissions == ("events", "frames")
    assert manager.get(issued.grant_id).status == "consumed"
    released = manager.release(consumed.connection_id)
    assert released is not None
    assert released.status == "closed"
    with pytest.raises(MonitorAccessError) as exc_info:
        manager.consume(issued.token)
    assert exc_info.value.code == "monitor_token_invalid"


def test_monitor_token_expires_and_raw_token_is_not_listed() -> None:
    now = [datetime(2026, 7, 12, 3, 0, tzinfo=timezone.utc)]
    manager = MonitorAccessManager(clock=lambda: now[0])
    issued = manager.issue(session_id="default", ttl_seconds=30)

    states = manager.list()
    assert len(states) == 1
    assert not hasattr(states[0], "token")

    now[0] += timedelta(seconds=31)
    assert manager.get(issued.grant_id).status == "expired"
    with pytest.raises(MonitorAccessError):
        manager.consume(issued.token)


def test_visual_frame_packet_round_trip() -> None:
    frame = VisualFrame(
        stream_id="vstream_1",
        frame_seq=7,
        session_id="default",
        tab_id="tab_1",
        document_id="doc_1",
        data=b"jpeg-bytes",
        format="jpeg",
        width=1280,
        height=720,
        device_scale_factor=1.0,
        scroll_offset_x=0.0,
        scroll_offset_y=12.0,
        captured_at=datetime(2026, 7, 12, 3, 1, tzinfo=timezone.utc),
    )

    metadata, image = decode_visual_frame_packet(encode_visual_frame_packet(frame))

    assert metadata["type"] == "visual_frame"
    assert metadata["frame_seq"] == 7
    assert metadata["document_id"] == "doc_1"
    assert image == b"jpeg-bytes"


def test_session_event_serialization_contains_no_binary_payload() -> None:
    event = SessionEvent(
        event_id="sevt_1",
        sequence=3,
        session_id="default",
        type="operation_completed",
        timestamp=datetime(2026, 7, 12, 3, 2, tzinfo=timezone.utc),
        tab_id="tab_1",
        document_id="doc_1",
        operation_id="op_1",
        data={"operation": "activate", "executed": True},
    )

    payload = serialize_session_event(event)

    assert payload["type"] == "session_event"
    assert payload["event"]["event_type"] == "operation_completed"
    assert b"" not in payload.values()
