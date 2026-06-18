from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from browser.runtime import BrowserRuntime
from schemas.browser import BrowserActionRequest, BrowserOpenRequest

router = APIRouter(tags=["browser"])


def get_browser_runtime(request: Request) -> BrowserRuntime:
    runtime = getattr(request.app.state, "browser_runtime", None)
    if runtime is None:
        runtime = BrowserRuntime()
        request.app.state.browser_runtime = runtime
    return runtime


@router.post("/browser/open")
def open_url(payload: BrowserOpenRequest, request: Request):
    try:
        return get_browser_runtime(request).open(payload.url).model_dump()
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
        return get_browser_runtime(request).act(payload).model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/browser/tabs")
def tabs(request: Request):
    try:
        return {"tabs": [tab.model_dump() for tab in get_browser_runtime(request).tabs()]}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/browser/tabs/switch")
def switch_tab(payload: dict, request: Request):
    try:
        tab_id = payload.get("tab_id")
        if not isinstance(tab_id, str):
            raise ValueError("tab_id is required")
        return get_browser_runtime(request).switch_tab(tab_id).model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
