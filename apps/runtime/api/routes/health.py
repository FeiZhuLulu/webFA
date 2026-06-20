from __future__ import annotations

import os

from fastapi import APIRouter, Request

from browser.config import resolve_browser_runtime_config
from browser.managed_chromium_host import chromium_executable_status
from storage.db import get_database_path
from storage.file_store import ensure_webfa_data_dir

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request) -> dict:
    paths = getattr(request.app.state, "webfa_paths", None) or ensure_webfa_data_dir()
    host = os.getenv("WEBFA_API_HOST", "127.0.0.1")
    port = int(os.getenv("WEBFA_API_PORT", "8787"))
    db_path = getattr(request.app.state, "webfa_db_path", None) or get_database_path()
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
            "session_id": "default",
            "profile_id": "default",
            "host_status": "not_started",
            "executable_found": executable_found,
            "executable_name": executable_name,
            "last_error": None,
        }
    return {
        "status": "ok",
        "runtime": "running",
        "api": {"host": host, "port": port, "url": f"http://{host}:{port}"},
        "storage": {
            "data_dir": str(paths["data_dir"]),
            "db_path": str(db_path),
            "logs_dir": str(paths["logs"]),
        },
        "mcp": {"status": "available", "transport": "stdio"},
        "browser": browser,
    }
