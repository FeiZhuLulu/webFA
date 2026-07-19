from __future__ import annotations

import os

from fastapi import APIRouter, Request

from apps.runtime.identity import runtime_identity
from browser.config import resolve_browser_runtime_config
from browser.managed_chromium_host import chromium_executable_status

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request) -> dict:
    host = os.getenv("WEBFA_API_HOST", "127.0.0.1")
    port = int(os.getenv("WEBFA_API_PORT", "8787"))
    runtime = getattr(request.app.state, "browser_runtime", None)
    if runtime is not None:
        browser = runtime.status()
    else:
        config = resolve_browser_runtime_config()
        executable_found = None
        executable_name = None
        if config.driver_name == "managed-chromium":
            executable_found, executable_name = chromium_executable_status()
        browser = {
            "selected_driver": config.driver_name,
            "headless": config.headless,
            "auth_takeover": config.auth_takeover,
            "visible_window": False,
            "session_id": "default",
            "profile_id": "default",
            "profile_shared": True,
            "active_agent_id": None,
            "agent_lease_expires_at": None,
            "host_status": "not_started",
            "executable_found": executable_found,
            "executable_name": executable_name,
            "last_error": None,
        }
    return {
        **runtime_identity(),
        "status": "ok",
        "runtime": "running",
        "api": {"host": host, "port": port, "url": f"http://{host}:{port}"},
        # Health is intentionally unauthenticated on loopback so process owners
        # can establish product/version/instance identity. It must not disclose
        # absolute application-data paths; the local `webfa paths` command is the
        # explicit diagnostics surface for those values.
        "storage": {"status": "ready", "persistent": True},
        "mcp": {"status": "available", "transport": "stdio"},
        "browser": browser,
    }
