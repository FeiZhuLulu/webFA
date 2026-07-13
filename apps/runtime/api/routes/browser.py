from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request

from apps.runtime.api.action_log import get_action_log
from browser.agent_lease import AgentLeaseBusyError
from browser.exceptions import BrowserHostClosedError
from browser.runtime import BrowserRuntime
from browser.runtime_supervisor import BrowserRuntimeSupervisor
from browser.runtime_errors import BrowserRuntimeError, browser_host_closed, from_value_error
from browser.semantic_operations import WebOperationError
from schemas.browser import BrowserActionRequest, BrowserOpenRequest
from schemas.web import WebObserveRequest, WebOpenRequest, WebOperationRequest

router = APIRouter(tags=["browser"])


def _require_unsafe_legacy_browser_api() -> None:
    enabled = os.getenv("WEBFA_ENABLE_UNSAFE_LEGACY_BROWSER_API", "").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        raise HTTPException(
            status_code=410,
            detail={
                "code": "legacy_browser_api_disabled",
                "message": (
                    "Legacy BrowserState/BrowserAction endpoints are disabled because they bypass "
                    "the P11 semantic safety contract. Use /v1/browser/web/* instead."
                ),
            },
        )


def get_browser_runtime(request: Request) -> BrowserRuntime | BrowserRuntimeSupervisor:
    runtime = getattr(request.app.state, "browser_runtime", None)
    if runtime is not None:
        return runtime
    supervisor = getattr(request.app.state, "browser_runtime_supervisor", None)
    if supervisor is None:
        supervisor = BrowserRuntimeSupervisor(
            profile_repository=getattr(request.app.state, "profile_repository", None),
        )
        request.app.state.browser_runtime_supervisor = supervisor
    request.app.state.browser_runtime = supervisor
    return supervisor


def get_agent_id(request: Request) -> str | None:
    return request.headers.get("X-WebFA-Agent-Id")


def runtime_error_response(exc: BrowserRuntimeError) -> HTTPException:
    return HTTPException(status_code=exc.http_status, detail=exc.to_detail())


def busy_response(exc: AgentLeaseBusyError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "agent_busy",
            "message": str(exc),
            "recover_hint": "Wait for the active agent lease to expire or coordinate with the active agent",
            "active_agent_id": exc.active_agent_id,
            "agent_lease_expires_at": exc.expires_at.isoformat(),
        },
    )


def host_closed_response(exc: BrowserHostClosedError) -> HTTPException:
    return runtime_error_response(browser_host_closed(str(exc)))


def _record_browser_action(
    request: Request,
    *,
    tool: str,
    status: str = "ok",
    code: str | None = None,
    message: str = "",
) -> None:
    get_action_log(request).record(
        tool=tool,
        status=status,
        code=code,
        message=message,
        agent_id=get_agent_id(request),
    )


def _record_runtime_error(request: Request, *, tool: str, exc: BrowserRuntimeError) -> None:
    _record_browser_action(
        request,
        tool=tool,
        status="error",
        code=exc.code,
        message=exc.message,
    )


def _handle_browser_errors(request: Request, tool: str, action):
    try:
        return action()
    except AgentLeaseBusyError as exc:
        _record_browser_action(request, tool=tool, status="error", code="agent_busy", message=str(exc))
        raise busy_response(exc) from exc
    except BrowserHostClosedError as exc:
        _record_browser_action(request, tool=tool, status="error", code="browser_host_closed", message=str(exc))
        raise host_closed_response(exc) from exc
    except WebOperationError as exc:
        status_code = 404 if exc.code == "object_not_found" else 409 if exc.code in {
            "object_version_conflict",
            "document_revision_conflict",
            "operation_temporarily_unavailable",
        } else 400
        _record_browser_action(request, tool=tool, status="error", code=exc.code, message=str(exc))
        raise HTTPException(
            status_code=status_code,
            detail={
                "code": exc.code,
                "message": str(exc),
                "target": exc.target,
                "operation": exc.operation,
                "recover_hint": exc.recover_hint,
            },
        ) from exc
    except BrowserRuntimeError as exc:
        _record_runtime_error(request, tool=tool, exc=exc)
        raise runtime_error_response(exc) from exc
    except ValueError as exc:
        mapped = from_value_error(exc)
        if mapped is not None:
            _record_runtime_error(request, tool=tool, exc=mapped)
            raise runtime_error_response(mapped) from exc
        _record_browser_action(request, tool=tool, status="error", message=str(exc))
        raise HTTPException(status_code=400, detail={"code": "invalid_request", "message": str(exc)}) from exc
    except Exception as exc:
        _record_browser_action(request, tool=tool, status="error", message=str(exc))
        raise HTTPException(
            status_code=500,
            detail={"code": "runtime_error", "message": str(exc)},
        ) from exc


@router.post("/browser/web/open")
def open_web_url(payload: WebOpenRequest, request: Request):
    def action():
        result = get_browser_runtime(request).open_web(
            payload,
            agent_id=get_agent_id(request),
        )
        _record_browser_action(request, tool="webfa.open_url", message=payload.url)
        return result.model_dump()

    return _handle_browser_errors(request, "webfa.open_url", action)


@router.post("/browser/web/observe")
def observe_web(payload: WebObserveRequest | None, request: Request):
    def action():
        result = get_browser_runtime(request).observe_web(payload or WebObserveRequest())
        _record_browser_action(request, tool="webfa.observe", message=(payload.mode if payload else "page"))
        return result.state.model_dump()

    return _handle_browser_errors(request, "webfa.observe", action)


@router.post("/browser/web/act")
def act_web(payload: WebOperationRequest, request: Request):
    def action():
        result = get_browser_runtime(request).act_web(payload, agent_id=get_agent_id(request)).model_dump()
        _record_browser_action(request, tool="webfa.act", message=payload.operation)
        return result

    return _handle_browser_errors(request, "webfa.act", action)


@router.post("/browser/web/tabs/switch")
def switch_web_tab(payload: dict, request: Request):
    def action():
        tab_id = payload.get("tab_id")
        if not isinstance(tab_id, str):
            raise ValueError("tab_id is required")
        runtime = get_browser_runtime(request)
        runtime.switch_tab(tab_id, agent_id=get_agent_id(request))
        state = runtime.observe_web(WebObserveRequest(mode="page")).state
        _record_browser_action(request, tool="webfa.switch_tab", message=tab_id)
        return state.model_dump()

    return _handle_browser_errors(request, "webfa.switch_tab", action)


# Legacy BrowserState/BrowserAction compatibility endpoints. Default MCP does not use these.
@router.post("/browser/open", include_in_schema=False)
@router.post("/browser/legacy/open")
def open_url(payload: BrowserOpenRequest, request: Request):
    _require_unsafe_legacy_browser_api()

    def action():
        result = get_browser_runtime(request).open(payload.url, agent_id=get_agent_id(request)).model_dump()
        _record_browser_action(request, tool="webfa.open_url", message=payload.url)
        return result

    return _handle_browser_errors(request, "webfa.open_url", action)


@router.get("/browser/observe", include_in_schema=False)
@router.get("/browser/legacy/observe")
def observe(request: Request):
    _require_unsafe_legacy_browser_api()

    def action():
        result = get_browser_runtime(request).observe().model_dump()
        _record_browser_action(request, tool="webfa.observe")
        return result

    return _handle_browser_errors(request, "webfa.observe", action)


@router.post("/browser/act", include_in_schema=False)
@router.post("/browser/legacy/act")
def act(payload: BrowserActionRequest, request: Request):
    _require_unsafe_legacy_browser_api()

    def action():
        result = get_browser_runtime(request).act(payload, agent_id=get_agent_id(request)).model_dump()
        _record_browser_action(request, tool="webfa.act", message=payload.action)
        return result

    return _handle_browser_errors(request, "webfa.act", action)


@router.get("/browser/tabs")
def tabs(request: Request):
    def action():
        runtime = get_browser_runtime(request)
        status = runtime.status()
        result = {
            "tabs": [tab.model_dump() for tab in runtime.tabs()],
            "agent": {
                "active_agent_id": status.get("active_agent_id"),
                "agent_lease_expires_at": status.get("agent_lease_expires_at"),
                "profile_shared": status.get("profile_shared", True),
                "profile_id": status.get("profile_id", "default"),
            },
        }
        _record_browser_action(request, tool="webfa.get_tabs")
        return result

    return _handle_browser_errors(request, "webfa.get_tabs", action)


@router.post("/browser/tabs/switch", include_in_schema=False)
@router.post("/browser/legacy/tabs/switch")
def switch_tab(payload: dict, request: Request):
    _require_unsafe_legacy_browser_api()

    def action():
        tab_id = payload.get("tab_id")
        if not isinstance(tab_id, str):
            raise ValueError("tab_id is required")
        result = get_browser_runtime(request).switch_tab(tab_id, agent_id=get_agent_id(request)).model_dump()
        _record_browser_action(request, tool="webfa.switch_tab", message=tab_id)
        return result

    return _handle_browser_errors(request, "webfa.switch_tab", action)