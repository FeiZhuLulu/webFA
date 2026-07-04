from __future__ import annotations

from fastapi import Request


def get_auth_surface_session(request: Request) -> dict[str, object]:
    session = getattr(request.app.state, "visualizer_auth_surface", None)
    if not isinstance(session, dict):
        session = {"active": False, "url": None}
        request.app.state.visualizer_auth_surface = session
    return session


def set_auth_surface_session(request: Request, *, active: bool, url: str | None = None) -> dict[str, object]:
    session = {"active": active, "url": url}
    request.app.state.visualizer_auth_surface = session
    return session