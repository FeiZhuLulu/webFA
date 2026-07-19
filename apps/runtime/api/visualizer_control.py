from __future__ import annotations

import os
import secrets
from typing import Annotated

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

VISUALIZER_CONTROL_HEADER = "X-WebFA-Visualizer-Token"
VISUALIZER_CONTROL_ENV = "WEBFA_VISUALIZER_CONTROL_TOKEN"
VISUALIZER_CONTROL_SECURITY_SCHEME = "VisualizerControlToken"

_visualizer_control_header = APIKeyHeader(
    name=VISUALIZER_CONTROL_HEADER,
    scheme_name=VISUALIZER_CONTROL_SECURITY_SCHEME,
    description=(
        "Process-local capability for the trusted human control plane. "
        "It is not an Agent Runtime credential."
    ),
    auto_error=False,
)


def require_visualizer_control(
    supplied: Annotated[str | None, Security(_visualizer_control_header)],
) -> None:
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
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "visualizer_control_forbidden",
                "message": "A valid Visualizer control token is required",
            },
        )
