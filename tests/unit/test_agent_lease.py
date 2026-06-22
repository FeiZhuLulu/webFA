from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from browser.agent_lease import AgentLease, AgentLeaseBusyError, DEFAULT_AGENT_ID, normalize_agent_id


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 6, 23, 0, 0, tzinfo=timezone.utc)

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)

    def __call__(self) -> datetime:
        return self.now


def test_agent_lease_first_call_binds_agent():
    clock = Clock()
    lease = AgentLease(ttl_seconds=60, now=clock)

    snapshot = lease.acquire("opencode")

    assert snapshot.active_agent_id == "opencode"
    assert snapshot.expires_at == clock.now + timedelta(seconds=60)


def test_agent_lease_same_agent_renews_expiry():
    clock = Clock()
    lease = AgentLease(ttl_seconds=60, now=clock)

    first = lease.acquire("opencode")
    clock.advance(20)
    second = lease.acquire("opencode")

    assert second.active_agent_id == "opencode"
    assert second.expires_at == first.expires_at + timedelta(seconds=20)


def test_agent_lease_blocks_different_agent_before_expiry():
    clock = Clock()
    lease = AgentLease(ttl_seconds=60, now=clock)
    lease.acquire("opencode")

    with pytest.raises(AgentLeaseBusyError) as error:
        lease.acquire("kimi-code")

    assert error.value.active_agent_id == "opencode"


def test_agent_lease_allows_takeover_after_expiry():
    clock = Clock()
    lease = AgentLease(ttl_seconds=60, now=clock)
    lease.acquire("opencode")
    clock.advance(61)

    snapshot = lease.acquire("kimi-code")

    assert snapshot.active_agent_id == "kimi-code"


def test_agent_lease_uses_anonymous_default():
    assert normalize_agent_id(None) == DEFAULT_AGENT_ID
    assert normalize_agent_id("  ") == DEFAULT_AGENT_ID

    lease = AgentLease(ttl_seconds=60, now=Clock())
    snapshot = lease.acquire(None)
    assert snapshot.active_agent_id == DEFAULT_AGENT_ID
