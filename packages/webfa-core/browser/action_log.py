from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import re
from threading import Lock
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SENSITIVE_MESSAGE_KEYS = {
    "access_token",
    "auth",
    "authorization",
    "card_number",
    "client_secret",
    "code",
    "credential",
    "cvc",
    "cvv",
    "otp",
    "password",
    "secret",
    "session",
    "token",
    "verification_code",
}


@dataclass(frozen=True)
class ActionLogRecord:
    timestamp: str
    tool: str
    status: str
    code: str | None
    message: str
    agent_id: str | None


class ActionLog:
    """In-memory ring buffer of recent browser tool calls for the Visualizer."""

    def __init__(self, max_entries: int = 100) -> None:
        self._entries: deque[ActionLogRecord] = deque(maxlen=max_entries)
        self._lock = Lock()

    def record(
        self,
        *,
        tool: str,
        status: str = "ok",
        code: str | None = None,
        message: str = "",
        agent_id: str | None = None,
    ) -> ActionLogRecord:
        entry = ActionLogRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            tool=tool,
            status=status,
            code=code,
            message=redact_action_message(message),
            agent_id=agent_id,
        )
        with self._lock:
            self._entries.append(entry)
        return entry

    def recent(self, limit: int = 50) -> list[dict[str, str | None]]:
        with self._lock:
            items = list(self._entries)[-limit:]
        return [
            {
                "timestamp": item.timestamp,
                "tool": item.tool,
                "status": item.status,
                "code": item.code,
                "message": item.message,
                "agent_id": item.agent_id,
            }
            for item in items
        ]


def redact_action_message(message: str) -> str:
    if not message:
        return message
    try:
        parts = urlsplit(message)
    except ValueError:
        return _redact_sensitive_words(message)
    if parts.scheme and parts.netloc:
        query = []
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            if _is_sensitive_key(key):
                query.append((key, "[REDACTED]"))
            else:
                query.append((key, value))
        redacted_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, safe="[]"), parts.fragment))
        return _redact_sensitive_words(redacted_url)
    return _redact_sensitive_words(message)


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in SENSITIVE_MESSAGE_KEYS)


def _redact_sensitive_words(message: str) -> str:
    keys = "|".join(re.escape(marker) for marker in sorted(SENSITIVE_MESSAGE_KEYS, key=len, reverse=True))
    redacted = re.sub(rf"(?i)\b({keys})=([^\s&]+)", r"\1=[REDACTED]", message)
    return re.sub(rf"(?i)\b({keys}):([^\s,;]+)", r"\1:[REDACTED]", redacted)
