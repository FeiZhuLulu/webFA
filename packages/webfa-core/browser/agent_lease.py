from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable


DEFAULT_AGENT_ID = "anonymous-mcp"
DEFAULT_LEASE_TTL_SECONDS = 600


class AgentLeaseBusyError(RuntimeError):
    def __init__(self, active_agent_id: str, expires_at: datetime) -> None:
        self.active_agent_id = active_agent_id
        self.expires_at = expires_at
        super().__init__(
            f"WebFA is currently controlled by agent '{active_agent_id}' until {expires_at.isoformat()}"
        )


@dataclass(frozen=True)
class AgentLeaseSnapshot:
    active_agent_id: str | None
    expires_at: datetime | None
    profile_shared: bool = True
    profile_id: str = "default"

    def as_dict(self) -> dict:
        return {
            "active_agent_id": self.active_agent_id,
            "agent_lease_expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "profile_shared": self.profile_shared,
            "profile_id": self.profile_id,
        }


class AgentLease:
    def __init__(
        self,
        ttl_seconds: int | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl_seconds is None:
            raw = os.getenv("WEBFA_AGENT_LEASE_TTL_SECONDS")
            ttl_seconds = int(raw) if raw else DEFAULT_LEASE_TTL_SECONDS
        self._ttl = timedelta(seconds=max(1, ttl_seconds))
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._active_agent_id: str | None = None
        self._expires_at: datetime | None = None
        self._lock = threading.Lock()

    def acquire(self, agent_id: str | None) -> AgentLeaseSnapshot:
        normalized = normalize_agent_id(agent_id)
        with self._lock:
            self._clear_if_expired()
            if self._active_agent_id is not None and self._active_agent_id != normalized:
                assert self._expires_at is not None
                raise AgentLeaseBusyError(self._active_agent_id, self._expires_at)
            self._active_agent_id = normalized
            self._expires_at = self._now() + self._ttl
            return AgentLeaseSnapshot(active_agent_id=self._active_agent_id, expires_at=self._expires_at)

    def snapshot(self) -> AgentLeaseSnapshot:
        with self._lock:
            self._clear_if_expired()
            return AgentLeaseSnapshot(active_agent_id=self._active_agent_id, expires_at=self._expires_at)

    def _clear_if_expired(self) -> None:
        if self._expires_at is not None and self._expires_at <= self._now():
            self._active_agent_id = None
            self._expires_at = None


def normalize_agent_id(agent_id: str | None) -> str:
    value = (agent_id or "").strip()
    return value or DEFAULT_AGENT_ID
