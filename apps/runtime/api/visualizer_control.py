from __future__ import annotations

import os
import secrets

from fastapi import HTTPException, Request

VISUALIZER_CONTROL_HEADER = "X-WebFA-Visualizer-Token"
VISUALIZER_CONTROL_ENV = "WEBFA_VISUALIZER_CONTROL_TOKEN"


def require_visualizer_control(request: Request) -> None:
    expected = os.getenv(VISUALIZER_CONTROL_ENV, "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "visualizer_control_unavailable",
                "message": (
                    "Visualizer control mutations are disabled because "
                    f"{VISUALIZER_CONTROL_ENV} is not configured"
                ),
            },
        )
    supplied = request.headers.get(VISUALIZER_CONTROL_HEADER, "")
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "visualizer_control_forbidden",
                "message": "A valid Visualizer control token is required",
            },
        )
