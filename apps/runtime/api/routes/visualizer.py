from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from apps.runtime.api.action_log import get_action_log
from apps.runtime.api.auth_surface_session import get_auth_surface_session, set_auth_surface_session
from apps.runtime.api.preview_cache import get_cached_preview, store_preview_cache
from apps.runtime.api.routes.browser import get_browser_runtime
from browser.config import resolve_browser_runtime_config
from browser.exceptions import BrowserHostClosedError
from schemas.visualizer import VisualizerState

router = APIRouter(tags=["visualizer"])


class AuthSurfaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str | None = None


def _record_action(
    request: Request,
    *,
    tool: str,
    status: str = "ok",
    code: str | None = None,
    message: str = "",
    agent_id: str | None = None,
) -> None:
    get_action_log(request).record(
        tool=tool,
        status=status,
        code=code,
        message=message,
        agent_id=agent_id,
    )


def _auth_surface_payload(request: Request, browser_state_url: str | None = None) -> dict[str, object]:
    session = get_auth_surface_session(request)
    config = resolve_browser_runtime_config()
    active = bool(session.get("active"))
    url = session.get("url") if active else None
    if active and not url and browser_state_url:
        url = browser_state_url
    return {
        "active": active,
        "url": url,
        "mode": "legacy" if config.auth_surface_mode == "legacy" else "electron",
    }


def build_visualizer_state(request: Request) -> VisualizerState:
    runtime = get_browser_runtime(request)
    errors: list[dict[str, str]] = []
    browser_state = None
    preview_data_url: str | None = None
    preview_captured_at: str | None = None

    try:
        browser_state = runtime.observe()
    except BrowserHostClosedError as exc:
        errors.append({"code": "browser_host_closed", "message": str(exc)})
    except Exception as exc:
        errors.append({"code": "observe_failed", "message": str(exc)})

    browser_status = runtime.status()
    auth_session = get_auth_surface_session(request)
    if auth_session.get("active") and browser_state is not None and browser_state.auth.takeover != "auth_surface":
        browser_state.auth.takeover = "auth_surface"
        browser_state.auth.user_action_required = True

    cached_preview = get_cached_preview(request)
    if auth_session.get("active"):
        preview_data_url = None
        preview_captured_at = None
    elif cached_preview is not None:
        preview_data_url = cached_preview.data_url
        preview_captured_at = cached_preview.captured_at
    elif browser_status.get("host_status") == "running":
        try:
            screenshot = runtime.capture_preview()
            if screenshot:
                preview_data_url = f"data:image/png;base64,{screenshot}"
                preview_captured_at = datetime.now(timezone.utc).isoformat()
            store_preview_cache(request, preview_data_url, preview_captured_at)
        except Exception:
            store_preview_cache(request, None, None)

    page = {
        "url": "",
        "title": "",
        "status": "idle",
        "auth": {},
    }
    if browser_state is not None:
        page = {
            "url": browser_state.url,
            "title": browser_state.title,
            "status": browser_state.page_status,
            "auth": browser_state.auth.model_dump(),
        }

    return VisualizerState.model_validate(
        {
            "runtime": {
                "online": True,
                "driver": browser_status.get("selected_driver", "managed-chromium"),
                "headless": bool(browser_status.get("headless")),
                "host_status": browser_status.get("host_status", "not_started"),
                "visible_window": bool(browser_status.get("visible_window")),
            },
            "agent": {
                "active_agent_id": browser_status.get("active_agent_id"),
                "lease_expires_at": browser_status.get("agent_lease_expires_at"),
            },
            "profile": {
                "profile_id": browser_status.get("profile_id", "default"),
                "shared": bool(browser_status.get("profile_shared", True)),
            },
            "page": page,
            "browser_state": browser_state.model_dump() if browser_state is not None else None,
            "preview": {
                "format": "png",
                "data_url": preview_data_url,
                "captured_at": preview_captured_at,
            },
            "auth_surface": _auth_surface_payload(request, browser_state.url if browser_state else None),
            "recent_actions": get_action_log(request).recent(),
            "errors": errors,
        }
    )


def _payload_with_state(request: Request, state) -> dict:
    store_preview_cache(request, None, None)
    payload = build_visualizer_state(request).model_dump()
    payload["browser_state"] = state.model_dump()
    payload["auth_surface"] = _auth_surface_payload(request, state.url)
    return payload


@router.get("/visualizer/state")
def visualizer_state(request: Request) -> dict:
    return build_visualizer_state(request).model_dump()


@router.post("/visualizer/open-auth-surface")
def open_auth_surface(request: Request, payload: AuthSurfaceRequest | None = None) -> dict:
    runtime = get_browser_runtime(request)
    body = payload or AuthSurfaceRequest()
    try:
        state = runtime.open_auth_surface(body.url)
        target_url = state.url or body.url
        set_auth_surface_session(request, active=True, url=target_url)
        _record_action(
            request,
            tool="visualizer.open_auth_surface",
            message=target_url or "auth surface opened in WebFA UI",
        )
        result = _payload_with_state(request, state)
        result["auth_surface"] = {"active": True, "url": target_url, "mode": "electron"}
        return result
    except BrowserHostClosedError as exc:
        _record_action(
            request,
            tool="visualizer.open_auth_surface",
            status="error",
            code="browser_host_closed",
            message=str(exc),
        )
        raise HTTPException(status_code=503, detail={"code": "browser_host_closed", "message": str(exc)}) from exc
    except Exception as exc:
        _record_action(request, tool="visualizer.open_auth_surface", status="error", message=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/visualizer/open-host")
def open_host(request: Request, payload: AuthSurfaceRequest | None = None) -> dict:
    """Compatibility wrapper: open-host now means open-auth-surface, not external Chromium."""
    return open_auth_surface(request, payload)


@router.post("/visualizer/close-auth-surface")
def close_auth_surface(request: Request, payload: AuthSurfaceRequest | None = None) -> dict:
    runtime = get_browser_runtime(request)
    body = payload or AuthSurfaceRequest()
    try:
        state = runtime.close_auth_surface(body.url)
        set_auth_surface_session(request, active=False, url=None)
        store_preview_cache(request, None, None)
        _record_action(
            request,
            tool="visualizer.close_auth_surface",
            message=state.url or body.url or "auth surface closed",
        )
        return _payload_with_state(request, state)
    except BrowserHostClosedError as exc:
        _record_action(request, tool="visualizer.close_auth_surface", status="error", code="browser_host_closed", message=str(exc))
        raise HTTPException(status_code=503, detail={"code": "browser_host_closed", "message": str(exc)}) from exc
    except Exception as exc:
        _record_action(request, tool="visualizer.close_auth_surface", status="error", message=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/visualizer/restart-host")
def restart_host(request: Request) -> dict:
    runtime = get_browser_runtime(request)
    try:
        state = runtime.restart_host()
        set_auth_surface_session(request, active=False, url=None)
        store_preview_cache(request, None, None)
        _record_action(request, tool="visualizer.restart_host", message="host restarted with current url")
        return _payload_with_state(request, state)
    except BrowserHostClosedError as exc:
        _record_action(request, tool="visualizer.restart_host", status="error", code="browser_host_closed", message=str(exc))
        raise HTTPException(status_code=503, detail={"code": "browser_host_closed", "message": str(exc)}) from exc
    except Exception as exc:
        _record_action(request, tool="visualizer.restart_host", status="error", message=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
