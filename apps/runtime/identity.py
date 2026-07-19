"""Ephemeral Runtime process identity used for local ownership handshakes.

The instance identifier is intentionally not an authorization secret and is not
durable state.  It changes when a new Runtime process starts and has no P13
trace/resume semantics.
"""

from __future__ import annotations

import os
import re
from typing import Final
from uuid import uuid4

from apps.runtime.version import __version__

PRODUCT_ID: Final = "webfa"
RELEASE_VERSION: Final = __version__
RUNTIME_PROTOCOL_VERSION: Final = 1
RUNTIME_INSTANCE_ID_ENV: Final = "WEBFA_RUNTIME_INSTANCE_ID"
_INSTANCE_ID_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{15,127}")


def _resolve_runtime_instance_id(configured: str | None) -> str:
    if configured is None:
        return f"runtime_{uuid4().hex}"
    if _INSTANCE_ID_PATTERN.fullmatch(configured) is None:
        raise ValueError(
            f"{RUNTIME_INSTANCE_ID_ENV} must be 16-128 characters using only "
            "ASCII letters, digits, dot, underscore, or hyphen, and must start "
            "with a letter or digit"
        )
    return configured


RUNTIME_INSTANCE_ID: Final = _resolve_runtime_instance_id(
    os.getenv(RUNTIME_INSTANCE_ID_ENV)
)


def runtime_identity() -> dict[str, str | int]:
    """Return the non-sensitive, process-stable Runtime handshake identity."""

    return {
        "product": PRODUCT_ID,
        "release_version": RELEASE_VERSION,
        "protocol_version": RUNTIME_PROTOCOL_VERSION,
        "instance_id": RUNTIME_INSTANCE_ID,
    }
