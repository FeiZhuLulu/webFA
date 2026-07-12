from datetime import datetime, timedelta, timezone

import pytest

from browser.human_control import (
    HumanControlError,
    HumanControlLeaseManager,
    parse_human_input_event,
)


def test_human_control_lease_is_exclusive_and_connection_scoped() -> None:
    now = [datetime(2026, 7, 12, tzinfo=timezone.utc)]
    manager = HumanControlLeaseManager(clock=lambda: now[0], default_ttl_seconds=120)

    lease = manager.acquire(
        connection_id="conn-a",
        session_id="default",
        profile_id="default",
        tab_id="tab_1",
        reason="authentication",
        active_agent_id="agent-a",
    )

    assert lease.status == "active"
    assert manager.require_active(
        lease_id=lease.lease_id,
        connection_id="conn-a",
        session_id="default",
    ) == lease
    assert manager.acquire(
        connection_id="conn-a",
        session_id="default",
        profile_id="default",
        tab_id="tab_1",
        reason="authentication",
        active_agent_id=None,
    ) == lease

    with pytest.raises(HumanControlError) as scoped:
        manager.acquire(
            connection_id="conn-a",
            session_id="default",
            profile_id="default",
            tab_id="tab_2",
            reason="authentication",
            active_agent_id="agent-a",
        )
    assert scoped.value.code == "human_control_scope_mismatch"

    with pytest.raises(HumanControlError) as busy:
        manager.acquire(
            connection_id="conn-b",
            session_id="default",
            profile_id="default",
            tab_id="tab_1",
            reason="captcha",
            active_agent_id="agent-b",
        )
    assert busy.value.code == "human_control_busy"

    with pytest.raises(HumanControlError) as mismatch:
        manager.require_active(
            lease_id=lease.lease_id,
            connection_id="conn-b",
            session_id="default",
        )
    assert mismatch.value.code == "human_control_scope_mismatch"

    released = manager.release(
        lease_id=lease.lease_id,
        connection_id="conn-a",
    )
    assert released.status == "released"
    assert manager.active() is None


def test_human_control_lease_expires_and_disconnect_aborts() -> None:
    now = [datetime(2026, 7, 12, tzinfo=timezone.utc)]
    manager = HumanControlLeaseManager(clock=lambda: now[0], default_ttl_seconds=30)
    lease = manager.acquire(
        connection_id="conn-a",
        session_id="default",
        profile_id="default",
        tab_id="tab_1",
        reason="authentication",
        active_agent_id="agent-a",
    )
    now[0] += timedelta(seconds=31)
    assert manager.active() is None
    assert manager.history()[0].status == "expired"
    cleanup = manager.pop_expired_cleanup()
    assert cleanup is not None
    assert cleanup.lease_id == lease.lease_id
    assert cleanup.status == "expired"
    assert manager.pop_expired_cleanup() is None

    lease2 = manager.acquire(
        connection_id="conn-b",
        session_id="default",
        profile_id="default",
        tab_id="tab_1",
        reason="captcha",
        active_agent_id="agent-a",
    )
    aborted = manager.release_connection("conn-b")
    assert aborted is not None
    assert aborted.lease_id == lease2.lease_id
    assert aborted.status == "aborted"


def test_human_input_parser_accepts_scoped_events_and_hides_text_repr() -> None:
    mouse = parse_human_input_event(
        {
            "type": "mouse_down",
            "x": 120.5,
            "y": 80,
            "button": "left",
            "buttons": 1,
            "click_count": 1,
            "modifiers": ["shift"],
        }
    )
    assert mouse.x == 120.5
    assert mouse.modifiers == ("shift",)

    text = parse_human_input_event({"type": "insert_text", "text": "secret-value"})
    assert text.text == "secret-value"
    assert "secret-value" not in repr(text)

    with pytest.raises(ValueError):
        parse_human_input_event({"type": "insert_text", "text": ""})
    with pytest.raises(ValueError):
        parse_human_input_event({"type": "mouse_move", "x": 1})
    with pytest.raises(ValueError):
        parse_human_input_event({"type": "key_down", "key": "A", "unknown": True})
    with pytest.raises(ValueError):
        parse_human_input_event({"type": "key_down", "key": "A", "auto_repeat": "false"})
    with pytest.raises(ValueError):
        parse_human_input_event({"type": "mouse_move", "x": float("nan"), "y": 1})
    with pytest.raises(ValueError):
        parse_human_input_event({"type": "wheel", "x": 1, "y": 1, "delta_y": float("inf")})
