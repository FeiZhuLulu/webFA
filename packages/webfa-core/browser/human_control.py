from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal
from uuid import uuid4

HumanControlStatus = Literal["active", "released", "expired", "aborted"]
HumanInputType = Literal[
    "mouse_move",
    "mouse_down",
    "mouse_up",
    "wheel",
    "key_down",
    "key_up",
    "insert_text",
]
HumanMouseButton = Literal["none", "left", "middle", "right", "back", "forward"]
HumanModifier = Literal["alt", "control", "meta", "shift"]


class HumanControlError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class HumanInputEvent:
    type: HumanInputType
    x: float | None = None
    y: float | None = None
    button: HumanMouseButton = "none"
    buttons: int = 0
    delta_x: float = 0.0
    delta_y: float = 0.0
    click_count: int = 1
    key: str | None = field(default=None, repr=False)
    code: str | None = None
    text: str | None = field(default=None, repr=False)
    modifiers: tuple[HumanModifier, ...] = ()
    auto_repeat: bool = False


@dataclass(frozen=True, slots=True)
class HumanControlLeaseState:
    lease_id: str
    connection_id: str
    session_id: str
    profile_id: str
    tab_id: str
    reason: str
    active_agent_id: str | None
    acquired_at: datetime
    expires_at: datetime
    status: HumanControlStatus
    released_at: datetime | None = None


class HumanControlLeaseManager:
    """Single-session exclusive human-control lease.

    The lease does not carry input data. It only binds one authenticated Monitor
    connection to the current Session and tab for a bounded interval.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        default_ttl_seconds: int = 300,
    ) -> None:
        if default_ttl_seconds < 30 or default_ttl_seconds > 1800:
            raise ValueError("default_ttl_seconds must be between 30 and 1800")
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._default_ttl = default_ttl_seconds
        self._active: HumanControlLeaseState | None = None
        self._history: list[HumanControlLeaseState] = []
        self._expired_cleanup: list[HumanControlLeaseState] = []
        self._lock = threading.RLock()

    def acquire(
        self,
        *,
        connection_id: str,
        session_id: str,
        profile_id: str,
        tab_id: str,
        reason: str,
        active_agent_id: str | None,
        ttl_seconds: int | None = None,
    ) -> HumanControlLeaseState:
        ttl = self._default_ttl if ttl_seconds is None else ttl_seconds
        if ttl < 30 or ttl > 1800:
            raise ValueError("ttl_seconds must be between 30 and 1800")
        if not connection_id.strip() or not session_id.strip() or not tab_id.strip():
            raise ValueError("connection_id, session_id, and tab_id are required")
        normalized_reason = reason.strip() or "manual_identity_confirmation"
        with self._lock:
            self._refresh_locked()
            if self._active is not None:
                if self._active.connection_id == connection_id:
                    requested_scope = (
                        session_id,
                        profile_id,
                        tab_id,
                        normalized_reason,
                    )
                    active_scope = (
                        self._active.session_id,
                        self._active.profile_id,
                        self._active.tab_id,
                        self._active.reason,
                    )
                    if requested_scope != active_scope:
                        raise HumanControlError(
                            "human_control_scope_mismatch",
                            "existing HumanControlLease is bound to a different Session, Profile, tab, or reason",
                        )
                    return self._active
                raise HumanControlError(
                    "human_control_busy",
                    "another Monitor connection currently holds the HumanControlLease",
                )
            now = self._now()
            state = HumanControlLeaseState(
                lease_id=f"hlease_{uuid4().hex}",
                connection_id=connection_id,
                session_id=session_id,
                profile_id=profile_id,
                tab_id=tab_id,
                reason=normalized_reason,
                active_agent_id=active_agent_id,
                acquired_at=now,
                expires_at=now + timedelta(seconds=ttl),
                status="active",
            )
            self._active = state
            return state

    def require_active(
        self,
        *,
        lease_id: str,
        connection_id: str,
        session_id: str,
    ) -> HumanControlLeaseState:
        with self._lock:
            self._refresh_locked()
            state = self._active
            if state is None:
                raise HumanControlError("human_control_inactive", "HumanControlLease is not active")
            if state.lease_id != lease_id or state.connection_id != connection_id:
                raise HumanControlError(
                    "human_control_scope_mismatch",
                    "HumanControlLease is bound to another Monitor connection",
                )
            if state.session_id != session_id:
                raise HumanControlError(
                    "human_control_session_mismatch",
                    "HumanControlLease is bound to another Session",
                )
            return state

    def release(
        self,
        *,
        lease_id: str,
        connection_id: str,
        status: Literal["released", "aborted"] = "released",
    ) -> HumanControlLeaseState:
        with self._lock:
            self._refresh_locked()
            state = self._active
            if state is None:
                raise HumanControlError("human_control_inactive", "HumanControlLease is not active")
            if state.lease_id != lease_id or state.connection_id != connection_id:
                raise HumanControlError(
                    "human_control_scope_mismatch",
                    "HumanControlLease is bound to another Monitor connection",
                )
            terminal = replace(
                state,
                status=status,
                released_at=self._now(),
            )
            self._active = None
            self._remember_locked(terminal)
            return terminal

    def release_connection(self, connection_id: str) -> HumanControlLeaseState | None:
        with self._lock:
            self._refresh_locked()
            state = self._active
            if state is None or state.connection_id != connection_id:
                return None
            terminal = replace(
                state,
                status="aborted",
                released_at=self._now(),
            )
            self._active = None
            self._remember_locked(terminal)
            return terminal

    def active(self) -> HumanControlLeaseState | None:
        with self._lock:
            self._refresh_locked()
            return self._active

    def pop_expired_cleanup(self) -> HumanControlLeaseState | None:
        with self._lock:
            self._refresh_locked()
            if not self._expired_cleanup:
                return None
            return self._expired_cleanup.pop(0)

    def history(self) -> list[HumanControlLeaseState]:
        with self._lock:
            self._refresh_locked()
            return list(reversed(self._history))

    def _refresh_locked(self) -> None:
        state = self._active
        if state is None or state.expires_at > self._now():
            return
        expired = replace(
            state,
            status="expired",
            released_at=self._now(),
        )
        self._active = None
        self._remember_locked(expired)
        self._expired_cleanup.append(expired)
        if len(self._expired_cleanup) > 64:
            del self._expired_cleanup[:-64]

    def _remember_locked(self, state: HumanControlLeaseState) -> None:
        self._history.append(state)
        if len(self._history) > 64:
            del self._history[:-64]

    def _now(self) -> datetime:
        value = self._clock()
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def parse_human_input_event(value: object) -> HumanInputEvent:
    if not isinstance(value, dict):
        raise ValueError("human input event must be an object")
    allowed = {
        "type",
        "x",
        "y",
        "button",
        "buttons",
        "delta_x",
        "delta_y",
        "click_count",
        "key",
        "code",
        "text",
        "modifiers",
        "auto_repeat",
    }
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"unsupported human input fields: {', '.join(sorted(unknown))}")
    event_type = value.get("type")
    supported = {
        "mouse_move",
        "mouse_down",
        "mouse_up",
        "wheel",
        "key_down",
        "key_up",
        "insert_text",
    }
    if event_type not in supported:
        raise ValueError("unsupported human input type")

    button = value.get("button", "none")
    if button not in {"none", "left", "middle", "right", "back", "forward"}:
        raise ValueError("unsupported mouse button")
    modifiers_value = value.get("modifiers", [])
    if not isinstance(modifiers_value, list):
        raise ValueError("modifiers must be an array")
    modifiers = tuple(dict.fromkeys(str(item).lower() for item in modifiers_value))
    if any(item not in {"alt", "control", "meta", "shift"} for item in modifiers):
        raise ValueError("unsupported keyboard modifier")

    def optional_number(name: str) -> float | None:
        item = value.get(name)
        if item is None:
            return None
        if not isinstance(item, (int, float)) or isinstance(item, bool):
            raise ValueError(f"{name} must be numeric")
        number = float(item)
        if not math.isfinite(number):
            raise ValueError(f"{name} must be finite")
        if number < 0 or number > 100000:
            raise ValueError(f"{name} is outside the supported range")
        return number

    text = value.get("text")
    if text is not None:
        if not isinstance(text, str):
            raise ValueError("text must be a string")
        if len(text) > 4096:
            raise ValueError("text is too long")
    key = value.get("key")
    code = value.get("code")
    for name, item in (("key", key), ("code", code)):
        if item is not None and (not isinstance(item, str) or len(item) > 128):
            raise ValueError(f"{name} must be a short string")

    buttons = value.get("buttons", 0)
    click_count = value.get("click_count", 1)
    if not isinstance(buttons, int) or isinstance(buttons, bool) or buttons < 0 or buttons > 31:
        raise ValueError("buttons must be an integer between 0 and 31")
    if not isinstance(click_count, int) or isinstance(click_count, bool) or click_count < 0 or click_count > 3:
        raise ValueError("click_count must be between 0 and 3")

    delta_x = value.get("delta_x", 0.0)
    delta_y = value.get("delta_y", 0.0)
    for name, item in (("delta_x", delta_x), ("delta_y", delta_y)):
        if not isinstance(item, (int, float)) or isinstance(item, bool):
            raise ValueError(f"{name} must be numeric")
        number = float(item)
        if not math.isfinite(number):
            raise ValueError(f"{name} must be finite")
        if abs(number) > 100000:
            raise ValueError(f"{name} is outside the supported range")

    event = HumanInputEvent(
        type=event_type,
        x=optional_number("x"),
        y=optional_number("y"),
        button=button,
        buttons=buttons,
        delta_x=float(delta_x),
        delta_y=float(delta_y),
        click_count=click_count,
        key=key,
        code=code,
        text=text,
        modifiers=modifiers,  # type: ignore[arg-type]
        auto_repeat=_strict_bool(value.get("auto_repeat", False), "auto_repeat"),
    )
    if event.type in {"mouse_move", "mouse_down", "mouse_up", "wheel"}:
        if event.x is None or event.y is None:
            raise ValueError("mouse and wheel input require x and y")
    if event.type in {"key_down", "key_up"} and not event.key:
        raise ValueError("keyboard input requires key")
    if event.type == "insert_text" and not event.text:
        raise ValueError("insert_text requires non-empty text")
    return event


def _strict_bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value
