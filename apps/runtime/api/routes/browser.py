from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from apps.runtime.api.action_log import get_action_log
from browser.agent_lease import AgentLeaseBusyError
from browser.exceptions import BrowserHostClosedError
from browser.runtime import BrowserRuntime
from schemas.browser import BrowserActionRequest, BrowserOpenRequest

router = APIRouter(tags=["browser"])


def get_browser_runtime(request: Request) -> BrowserRuntime:
    runtime = getattr(request.app.state, "browser_runtime", None)
    if runtime is None:
        runtime = BrowserRuntime()
        request.app.state.browser_runtime = runtime
    return runtime


def get_agent_id(request: Request) -> str | None:
    return request.headers.get("X-WebFA-Agent-Id")


def busy_response(exc: AgentLeaseBusyError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "agent_busy",
            "message": str(exc),
            "active_agent_id": exc.active_agent_id,
            "agent_lease_expires_at": exc.expires_at.isoformat(),
        },
    )


def host_closed_response(exc: BrowserHostClosedError) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={"code": "browser_host_closed", "message": str(exc)},
    )


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


@router.post("/browser/open")
def open_url(payload: BrowserOpenRequest, request: Request):
    try:
        result = get_browser_runtime(request).open(payload.url, agent_id=get_agent_id(request)).model_dump()
        _record_browser_action(request, tool="webfa.open_url", message=payload.url)
        return result
    except AgentLeaseBusyError as exc:
        _record_browser_action(request, tool="webfa.open_url", status="error", code="agent_busy", message=str(exc))
        raise busy_response(exc) from exc
    except BrowserHostClosedError as exc:
        _record_browser_action(request, tool="webfa.open_url", status="error", code="browser_host_closed", message=str(exc))
        raise host_closed_response(exc) from exc
    except Exception as exc:
        _record_browser_action(request, tool="webfa.open_url", status="error", message=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/browser/observe")
def observe(request: Request):
    try:
        result = get_browser_runtime(request).observe().model_dump()
        _record_browser_action(request, tool="webfa.observe")
        return result
    except BrowserHostClosedError as exc:
        _record_browser_action(request, tool="webfa.observe", status="error", code="browser_host_closed", message=str(exc))
        raise host_closed_response(exc) from exc
    except Exception as exc:
        _record_browser_action(request, tool="webfa.observe", status="error", message=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/browser/act")
def act(payload: BrowserActionRequest, request: Request):
    try:
        result = get_browser_runtime(request).act(payload, agent_id=get_agent_id(request)).model_dump()
        _record_browser_action(request, tool="webfa.act", message=payload.action)
        return result
    except AgentLeaseBusyError as exc:
        _record_browser_action(request, tool="webfa.act", status="error", code="agent_busy", message=str(exc))
        raise busy_response(exc) from exc
    except BrowserHostClosedError as exc:
        _record_browser_action(request, tool="webfa.act", status="error", code="browser_host_closed", message=str(exc))
        raise host_closed_response(exc) from exc
    except ValueError as exc:
        _record_browser_action(request, tool="webfa.act", status="error", code="stale_element", message=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        _record_browser_action(request, tool="webfa.act", status="error", message=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/browser/tabs")
def tabs(request: Request):
    try:
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
    except BrowserHostClosedError as exc:
        _record_browser_action(request, tool="webfa.get_tabs", status="error", code="browser_host_closed", message=str(exc))
        raise host_closed_response(exc) from exc
    except Exception as exc:
        _record_browser_action(request, tool="webfa.get_tabs", status="error", message=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/browser/tabs/switch")
def switch_tab(payload: dict, request: Request):
    try:
        tab_id = payload.get("tab_id")
        if not isinstance(tab_id, str):
            raise ValueError("tab_id is required")
        result = get_browser_runtime(request).switch_tab(tab_id, agent_id=get_agent_id(request)).model_dump()
        _record_browser_action(request, tool="webfa.switch_tab", message=tab_id)
        return result
    except AgentLeaseBusyError as exc:
        _record_browser_action(request, tool="webfa.switch_tab", status="error", code="agent_busy", message=str(exc))
        raise busy_response(exc) from exc
    except BrowserHostClosedError as exc:
        _record_browser_action(request, tool="webfa.switch_tab", status="error", code="browser_host_closed", message=str(exc))
        raise host_closed_response(exc) from exc
    except ValueError as exc:
        _record_browser_action(request, tool="webfa.switch_tab", status="error", message=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        _record_browser_action(request, tool="webfa.switch_tab", status="error", message=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
