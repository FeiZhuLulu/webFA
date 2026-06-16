from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Allow `python -m uvicorn apps.runtime.main:app` from the repo root before editable install.
APP_ROOT = Path(__file__).resolve().parents[2]
for candidate in [APP_ROOT, APP_ROOT / "packages", APP_ROOT / "packages" / "webfa-core"]:
    value = str(candidate)
    if value not in sys.path:
        sys.path.insert(0, value)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.runtime.api.routes.health import router as health_router
from apps.runtime.api.routes.providers import router as providers_router
from apps.runtime.api.routes.transactions import router as transactions_router
from registry.transaction_registry import build_default_registry
from storage.db import init_db, upsert_transactions
from storage.file_store import ensure_webfa_data_dir


@asynccontextmanager
async def lifespan(app: FastAPI):
    paths = ensure_webfa_data_dir()
    db_path = init_db()
    resources_root = Path(os.getenv("WEBFA_RESOURCES_ROOT", Path(__file__).resolve().parents[2] / "resources"))
    registry = build_default_registry(resources_root)
    upsert_transactions(registry.as_json())

    app.state.webfa_paths = paths
    app.state.webfa_db_path = db_path
    app.state.transaction_registry = registry
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="WebFA Runtime", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:8788", "http://localhost:8788"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    app.include_router(providers_router, prefix="/v1")
    app.include_router(transactions_router, prefix="/v1")
    return app


app = create_app()
