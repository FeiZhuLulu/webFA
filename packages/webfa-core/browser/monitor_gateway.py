from __future__ import annotations

import hashlib
import json
import secrets
import struct
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal
from uuid import uuid4

from browser.session_events import SessionEvent
from browser.visual_surface import VisualFrame, VisualStreamConfig

MonitorPermission = Literal["events", "frames", "takeover"]
MonitorGrantStatus = Literal["issued", "consumed", "closed", "revoked", "expired"]


class MonitorAccessError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class MonitorAccessGrant:
    grant_id: str
    token: str
    session_id: str
    permissions: tuple[MonitorPermission, ...]
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class MonitorAccessState:
    grant_id: str
    session_id: str
    permissions: tuple[MonitorPermission, ...]
    issued_at: datetime
    expires_at: datetime
    status: MonitorGrantStatus
    connection_id: str | None = None


@dataclass(frozen=True, slots=True)
class MonitorConnectionGrant:
    grant_id: str
    connection_id: str
    session_id: str
    permissions: tuple[MonitorPermission, ...]
    expires_at: datetime


class MonitorAccessManager:
    """Issues one-time, session-scoped Monitor bearer capabilities.

    Raw tokens are returned only once and never stored. The manager retains a
    SHA-256 digest so accidental state projection cannot disclose an active
    credential. A token can authenticate exactly one Monitor connection.
    """

    def __init__(
        self,
        *,
        max_active_grants: int = 32,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if max_active_grants < 1:
            raise ValueError("max_active_grants must be positive")
        self._max_active_grants = max_active_grants
        self._max_history = max(64, max_active_grants * 8)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._states: dict[str, MonitorAccessState] = {}
        self._token_index: dict[str, str] = {}
        self._lock = threading.RLock()

    def issue(
        self,
        *,
        session_id: str,
        permissions: tuple[MonitorPermission, ...] = ("events", "frames"),
        ttl_seconds: int = 300,
    ) -> MonitorAccessGrant:
        normalized_session = session_id.strip()
        if not normalized_session:
            raise ValueError("session_id is required")
        normalized_permissions = tuple(dict.fromkeys(permissions))
        if not normalized_permissions or any(item not in {"events", "frames", "takeover"} for item in normalized_permissions):
            raise ValueError("unsupported Monitor permission")
        if "takeover" in normalized_permissions and "frames" not in normalized_permissions:
            raise ValueError("takeover permission requires frames permission")
        if ttl_seconds < 30 or ttl_seconds > 3600:
            raise ValueError("ttl_seconds must be between 30 and 3600")

        with self._lock:
            self._refresh_locked()
            active = [state for state in self._states.values() if state.status in {"issued", "consumed"}]
            if len(active) >= self._max_active_grants:
                raise MonitorAccessError(
                    "monitor_grant_limit_reached",
                    "too many active Monitor grants",
                )
            now = self._now()
            grant_id = f"mgrant_{uuid4().hex}"
            token = secrets.token_urlsafe(32)
            digest = _token_digest(token)
            expires_at = now + timedelta(seconds=ttl_seconds)
            self._states[grant_id] = MonitorAccessState(
                grant_id=grant_id,
                session_id=normalized_session,
                permissions=normalized_permissions,
                issued_at=now,
                expires_at=expires_at,
                status="issued",
            )
            self._token_index[digest] = grant_id
            return MonitorAccessGrant(
                grant_id=grant_id,
                token=token,
                session_id=normalized_session,
                permissions=normalized_permissions,
                issued_at=now,
                expires_at=expires_at,
            )

    def consume(self, token: str) -> MonitorConnectionGrant:
        supplied = token.strip()
        if not supplied:
            raise MonitorAccessError("monitor_token_missing", "Monitor token is required")
        digest = _token_digest(supplied)
        with self._lock:
            self._refresh_locked()
            grant_id = self._token_index.pop(digest, None)
            if grant_id is None:
                raise MonitorAccessError("monitor_token_invalid", "Monitor token is invalid or already consumed")
            state = self._states.get(grant_id)
            if state is None or state.status != "issued":
                raise MonitorAccessError("monitor_token_invalid", "Monitor token is invalid or already consumed")
            connection_id = f"mconn_{uuid4().hex}"
            consumed = replace(state, status="consumed", connection_id=connection_id)
            self._states[grant_id] = consumed
            return MonitorConnectionGrant(
                grant_id=grant_id,
                connection_id=connection_id,
                session_id=state.session_id,
                permissions=state.permissions,
                expires_at=state.expires_at,
            )

    def release(self, connection_id: str) -> MonitorAccessState | None:
        with self._lock:
            self._refresh_locked()
            for grant_id, state in self._states.items():
                if state.connection_id == connection_id and state.status == "consumed":
                    closed = replace(state, status="closed")
                    self._states[grant_id] = closed
                    self._prune_history_locked()
                    return closed
            return None

    def revoke(self, grant_id: str) -> MonitorAccessState:
        with self._lock:
            self._refresh_locked()
            state = self._states.get(grant_id)
            if state is None:
                raise MonitorAccessError("monitor_grant_not_found", "Monitor grant was not found")
            revoked = replace(state, status="revoked")
            self._states[grant_id] = revoked
            for digest, indexed_grant_id in tuple(self._token_index.items()):
                if indexed_grant_id == grant_id:
                    self._token_index.pop(digest, None)
            return revoked

    def get(self, grant_id: str) -> MonitorAccessState:
        with self._lock:
            self._refresh_locked()
            state = self._states.get(grant_id)
            if state is None:
                raise MonitorAccessError("monitor_grant_not_found", "Monitor grant was not found")
            return state

    def list(self) -> list[MonitorAccessState]:
        with self._lock:
            self._refresh_locked()
            return sorted(self._states.values(), key=lambda item: item.issued_at, reverse=True)

    def _refresh_locked(self) -> None:
        now = self._now()
        for grant_id, state in tuple(self._states.items()):
            if state.status in {"issued", "consumed"} and state.expires_at <= now:
                self._states[grant_id] = replace(state, status="expired")
                for digest, indexed_grant_id in tuple(self._token_index.items()):
                    if indexed_grant_id == grant_id:
                        self._token_index.pop(digest, None)
        self._prune_history_locked()

    def _prune_history_locked(self) -> None:
        if len(self._states) <= self._max_history:
            return
        terminal = sorted(
            (
                state
                for state in self._states.values()
                if state.status in {"closed", "revoked", "expired"}
            ),
            key=lambda item: item.issued_at,
        )
        for state in terminal:
            if len(self._states) <= self._max_history:
                break
            self._states.pop(state.grant_id, None)

    def _now(self) -> datetime:
        value = self._clock()
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def serialize_session_event(event: SessionEvent) -> dict[str, object]:
    return {
        "type": "session_event",
        "event": {
            "event_id": event.event_id,
            "sequence": event.sequence,
            "session_id": event.session_id,
            "event_type": event.type,
            "timestamp": event.timestamp.isoformat(),
            "tab_id": event.tab_id,
            "document_id": event.document_id,
            "operation_id": event.operation_id,
            "data": event.data,
        },
    }


def encode_visual_frame_packet(frame: VisualFrame) -> bytes:
    metadata = {
        "version": 1,
        "type": "visual_frame",
        "stream_id": frame.stream_id,
        "frame_seq": frame.frame_seq,
        "session_id": frame.session_id,
        "tab_id": frame.tab_id,
        "document_id": frame.document_id,
        "format": frame.format,
        "width": frame.width,
        "height": frame.height,
        "device_scale_factor": frame.device_scale_factor,
        "scroll_offset_x": frame.scroll_offset_x,
        "scroll_offset_y": frame.scroll_offset_y,
        "captured_at": frame.captured_at.isoformat(),
    }
    header = json.dumps(metadata, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(header) > 64 * 1024:
        raise ValueError("visual frame header is too large")
    if len(frame.data) > 16 * 1024 * 1024:
        raise ValueError("visual frame payload is too large")
    return struct.pack("!I", len(header)) + header + frame.data


def decode_visual_frame_packet(packet: bytes) -> tuple[dict[str, object], bytes]:
    if len(packet) < 4:
        raise ValueError("visual frame packet is truncated")
    header_length = struct.unpack("!I", packet[:4])[0]
    if header_length < 2 or header_length > 64 * 1024:
        raise ValueError("visual frame header length is invalid")
    boundary = 4 + header_length
    if boundary > len(packet):
        raise ValueError("visual frame packet header is truncated")
    metadata = json.loads(packet[4:boundary].decode("utf-8"))
    if not isinstance(metadata, dict) or metadata.get("type") != "visual_frame":
        raise ValueError("visual frame packet metadata is invalid")
    return metadata, packet[boundary:]


def parse_stream_config(value: object) -> VisualStreamConfig:
    if value is None:
        return VisualStreamConfig()
    if not isinstance(value, dict):
        raise ValueError("stream configuration must be an object")
    allowed = {
        "format",
        "quality",
        "max_width",
        "max_height",
        "every_nth_frame",
        "delivery_queue_size",
    }
    unexpected = set(value) - allowed
    if unexpected:
        raise ValueError(f"unsupported stream configuration fields: {sorted(unexpected)}")
    return VisualStreamConfig(**value)


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
