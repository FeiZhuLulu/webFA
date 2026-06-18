from __future__ import annotations

import os

from fastapi import APIRouter, Request

from storage.db import get_database_path
from storage.file_store import ensure_webfa_data_dir

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request) -> dict:
    paths = getattr(request.app.state, "webfa_paths", None) or ensure_webfa_data_dir()
    host = os.getenv("WEBFA_API_HOST", "127.0.0.1")
    port = int(os.getenv("WEBFA_API_PORT", "8787"))
    db_path = getattr(request.app.state, "webfa_db_path", None) or get_database_path()
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
    }
