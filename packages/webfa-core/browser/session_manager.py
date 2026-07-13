from __future__ import annotations

import threading
from dataclasses import dataclass

from browser.profile_storage import ProfileProcessLock
from browser.runtime import BrowserSessionRuntime
from schemas.profile import BrowserProfile


@dataclass
class ActiveBrowserSession:
    session_id: str
    profile: BrowserProfile
    runtime_generation: str
    runtime: BrowserSessionRuntime
    process_lock: ProfileProcessLock


class SessionManager:
    """In-memory index of active SessionRuntime instances.

    Durable Session metadata remains in BrowserSessionRepository. This manager
    owns only live Runtime objects and the one-active-Session-per-Profile rule.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, ActiveBrowserSession] = {}
        self._profile_sessions: dict[str, str] = {}
        self._default_session_id: str | None = None
        self._lock = threading.RLock()

    @property
    def default_session_id(self) -> str | None:
        with self._lock:
            return self._default_session_id

    def get(self, session_id: str | None) -> ActiveBrowserSession | None:
        if not session_id:
            return None
        with self._lock:
            return self._sessions.get(session_id)

    def get_by_profile(self, profile_id: str) -> ActiveBrowserSession | None:
        with self._lock:
            session_id = self._profile_sessions.get(profile_id)
            return self._sessions.get(session_id) if session_id is not None else None

    def add(self, entry: ActiveBrowserSession) -> None:
        with self._lock:
            existing = self._profile_sessions.get(entry.profile.profile_id)
            if existing is not None and existing != entry.session_id:
                raise RuntimeError("Browser Profile already has an active Session")
            self._sessions[entry.session_id] = entry
            self._profile_sessions[entry.profile.profile_id] = entry.session_id
            if self._default_session_id is None:
                self._default_session_id = entry.session_id

    def remove(self, session_id: str) -> ActiveBrowserSession | None:
        with self._lock:
            entry = self._sessions.pop(session_id, None)
            if entry is None:
                return None
            if self._profile_sessions.get(entry.profile.profile_id) == session_id:
                self._profile_sessions.pop(entry.profile.profile_id, None)
            if self._default_session_id == session_id:
                self._default_session_id = next(iter(self._sessions), None)
            return entry

    def values(self) -> list[ActiveBrowserSession]:
        with self._lock:
            return list(self._sessions.values())

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)
