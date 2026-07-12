from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BrowserRuntimeError(Exception):
    code: str
    message: str
    recover_hint: str | None = None
    http_status: int = 400

    def to_detail(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "message": self.message,
            "recover_hint": self.recover_hint,
        }


def private_url_blocked(url: str, *, policy: str) -> BrowserRuntimeError:
    return BrowserRuntimeError(
        code="private_url_blocked",
        message=f"Navigation blocked for URL: {url}",
        recover_hint=(
            "Open a public URL or set WEBFA_PRIVATE_URL_POLICY=allow for trusted local testing"
        ),
        http_status=403,
    )


def sensitive_url_blocked(url: str) -> BrowserRuntimeError:
    return BrowserRuntimeError(
        code="sensitive_url_blocked",
        message=f"Navigation blocked due to sensitive URL content: {url}",
        recover_hint="Remove sensitive query parameters or use a safer URL",
        http_status=403,
    )


def navigation_blocked(url: str) -> BrowserRuntimeError:
    return BrowserRuntimeError(
        code="navigation_blocked",
        message=f"Navigation ended on a blocked URL: {url}",
        recover_hint="Open a public URL or adjust WEBFA_PRIVATE_URL_POLICY for trusted local testing",
        http_status=403,
    )


def stale_element() -> BrowserRuntimeError:
    return BrowserRuntimeError(
        code="stale_element",
        message="Element id is stale; call observe again",
        recover_hint="Call webfa.observe to refresh element ids before acting",
        http_status=400,
    )


def auth_surface_active() -> BrowserRuntimeError:
    return BrowserRuntimeError(
        code="auth_surface_active",
        message="Human takeover is active; complete the takeover before agent actions",
        recover_hint="Finish or release the WebFA HumanControlLease, then call webfa.observe",
        http_status=409,
    )


def human_control_active() -> BrowserRuntimeError:
    return BrowserRuntimeError(
        code="human_control_active",
        message="A local user currently holds the HumanControlLease for this Session",
        recover_hint="Wait for the user to release control, then call webfa.observe before acting",
        http_status=409,
    )


def auth_surface_retired() -> BrowserRuntimeError:
    return BrowserRuntimeError(
        code="legacy_auth_surface_disabled",
        message="The duplicate-page AuthSurface is retired",
        recover_hint="Open the Session Monitor and use HumanControlLease on the existing BrowserHost page",
        http_status=410,
    )


def browser_host_closed(message: str | None = None) -> BrowserRuntimeError:
    return BrowserRuntimeError(
        code="browser_host_closed",
        message=message or "Browser host has exited; use open_url to restart",
        recover_hint="Call webfa.open_url with the current or target URL to restart the host",
        http_status=503,
    )


def dialog_required() -> BrowserRuntimeError:
    return BrowserRuntimeError(
        code="dialog_required",
        message="A JavaScript dialog is blocking page actions",
        recover_hint="Inspect state.dialogs and call accept_dialog or dismiss_dialog with the dialog id",
        http_status=409,
    )


def dialog_not_found(dialog_id: str | None = None) -> BrowserRuntimeError:
    target = dialog_id or "dialog"
    return BrowserRuntimeError(
        code="dialog_not_found",
        message=f"Dialog not found: {target}",
        recover_hint="Call webfa.observe to refresh dialog ids",
        http_status=400,
    )


def frame_unsupported(frame_id: str | None = None) -> BrowserRuntimeError:
    target = frame_id or "frame"
    return BrowserRuntimeError(
        code="frame_unsupported",
        message=f"Frame action is not supported: {target}",
        recover_hint="Act on main-frame elements or same-origin iframe elements exposed in BrowserState",
        http_status=400,
    )


def action_timeout(action: str) -> BrowserRuntimeError:
    return BrowserRuntimeError(
        code="action_timeout",
        message=f"Action timed out: {action}",
        recover_hint="Retry after observe, or use a shorter wait target",
        http_status=408,
    )


def from_value_error(exc: ValueError) -> BrowserRuntimeError | None:
    message = str(exc).lower()
    if "stale" in message and "observe" in message:
        return stale_element()
    if "auth surface is active" in message:
        return auth_surface_active()
    if "password fields require user auth takeover" in message:
        return BrowserRuntimeError(
            code="auth_surface_active",
            message=str(exc),
            recover_hint="Complete login in the WebFA auth takeover area, then call webfa.observe",
            http_status=409,
        )
    return None