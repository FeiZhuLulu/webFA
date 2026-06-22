from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from browser.agent_lease import AgentLeaseBusyError
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


@router.post("/browser/open")
def open_url(payload: BrowserOpenRequest, request: Request):
    try:
        return get_browser_runtime(request).open(payload.url, agent_id=get_agent_id(request)).model_dump()
    except AgentLeaseBusyError as exc:
        raise busy_response(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/browser/observe")
def observe(request: Request):
    try:
        return get_browser_runtime(request).observe().model_dump()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/browser/act")
def act(payload: BrowserActionRequest, request: Request):
    try:
        return get_browser_runtime(request).act(payload, agent_id=get_agent_id(request)).model_dump()
    except AgentLeaseBusyError as exc:
        raise busy_response(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/browser/tabs")
def tabs(request: Request):
    try:
        runtime = get_browser_runtime(request)
        status = runtime.status()
        return {
            "tabs": [tab.model_dump() for tab in runtime.tabs()],
            "agent": {
                "active_agent_id": status.get("active_agent_id"),
                "agent_lease_expires_at": status.get("agent_lease_expires_at"),
                "profile_shared": status.get("profile_shared", True),
                "profile_id": status.get("profile_id", "default"),
            },
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/browser/tabs/switch")
def switch_tab(payload: dict, request: Request):
    try:
        tab_id = payload.get("tab_id")
        if not isinstance(tab_id, str):
            raise ValueError("tab_id is required")
        return get_browser_runtime(request).switch_tab(tab_id, agent_id=get_agent_id(request)).model_dump()
    except AgentLeaseBusyError as exc:
        raise busy_response(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
