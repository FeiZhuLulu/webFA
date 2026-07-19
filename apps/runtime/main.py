from __future__ import annotations

import os
import sys
import threading
from contextlib import asynccontextmanager
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

# Allow `python -m uvicorn apps.runtime.main:app` from the repo root before editable install.
APP_ROOT = Path(__file__).resolve().parents[2]
for candidate in [APP_ROOT, APP_ROOT / "packages", APP_ROOT / "packages" / "webfa-core"]:
    value = str(candidate)
    if value not in sys.path:
        sys.path.insert(0, value)

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from apps.runtime.api.routes.approvals import router as approvals_router
from apps.runtime.api.routes.audits import router as audits_router
from apps.runtime.api.routes.browser import router as browser_router
from apps.runtime.api.routes.executions import router as executions_router
from apps.runtime.api.routes.github import router as github_router
from apps.runtime.api.routes.health import router as health_router
from apps.runtime.api.routes.mcp_config import router as mcp_config_router
from apps.runtime.api.routes.monitor import control_router as monitor_control_router
from apps.runtime.api.routes.monitor import monitor_router
from apps.runtime.api.routes.plans import router as plans_router
from apps.runtime.api.routes.proofs import router as proofs_router
from apps.runtime.api.routes.provider_connections import router as provider_connections_router
from apps.runtime.api.routes.profiles import router as profiles_router
from apps.runtime.api.routes.providers import router as providers_router
from apps.runtime.api.routes.transactions import router as transactions_router
from apps.runtime.api.routes.visualizer import router as visualizer_router
from apps.runtime.api.routes.workspaces import router as workspaces_router
from apps.runtime.version import __version__
from browser.profile_repository import ProfileRepository
from registry.transaction_registry import build_default_registry, default_resources_root
from storage.db import init_db, upsert_transactions
from storage.file_store import ensure_webfa_data_dir


def _console_allowed_origins() -> list[str]:
    strict = os.getenv("WEBFA_STRICT_CONSOLE_ORIGINS") == "1"
    origins = [] if strict else ["http://127.0.0.1:8788", "http://localhost:8788"]
    for value in os.getenv("WEBFA_CONSOLE_ALLOWED_ORIGINS", "").split(","):
        origin = value.strip()
        if not origin or origin in origins:
            continue
        parsed = urlsplit(origin)
        if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("WEBFA_CONSOLE_ALLOWED_ORIGINS accepts loopback HTTP origins only")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("WEBFA_CONSOLE_ALLOWED_ORIGINS accepts origins without paths only")
        if parsed.hostname != "localhost":
            try:
                is_loopback = ip_address(parsed.hostname).is_loopback
            except ValueError:
                is_loopback = False
            if not is_loopback:
                raise ValueError("WEBFA_CONSOLE_ALLOWED_ORIGINS accepts loopback HTTP origins only")
        origins.append(origin.rstrip("/"))
    if strict and not origins:
        raise ValueError(
            "WEBFA_STRICT_CONSOLE_ORIGINS=1 requires at least one explicit "
            "loopback origin in WEBFA_CONSOLE_ALLOWED_ORIGINS"
        )
    return origins


@asynccontextmanager
async def lifespan(app: FastAPI):
    paths = ensure_webfa_data_dir()
    db_path = init_db()
    resources_override = os.getenv("WEBFA_RESOURCES_ROOT")
    resources_root = Path(resources_override).expanduser() if resources_override else default_resources_root()
    registry = build_default_registry(resources_root)
    upsert_transactions(registry.as_json())

    app.state.webfa_paths = paths
    app.state.webfa_db_path = db_path
    app.state.transaction_registry = registry
    profile_repository = ProfileRepository()
    profile_repository.ensure_default_profile()
    app.state.profile_repository = profile_repository
    try:
        yield
    finally:
        _close_runtime_services(app)


def _close_runtime_services(app: FastAPI) -> None:
    failures: list[Exception] = []
    closed_service_ids: set[int] = set()
    for attribute in (
        "profile_bootstrap_service",
        "profile_bundle_service",
        "browser_runtime",
        "browser_runtime_supervisor",
    ):
        service = getattr(app.state, attribute, None)
        # Revoke the published reference before closing. This makes shutdown
        # idempotent and prevents a re-entered embedded App from handing out a
        # service that has already released its BrowserHost or worker resources.
        setattr(app.state, attribute, None)
        if service is None or id(service) in closed_service_ids:
            continue
        closed_service_ids.add(id(service))
        try:
            service.close()
        except Exception as exc:
            failures.append(exc)
    # Capabilities and UI projections are bound to the stopped Runtime
    # generation. Never preserve bearer grants, action history, or rendered
    # previews when an embedded App instance is entered again.
    for attribute in (
        "monitor_access_manager",
        "visualizer_action_log",
        "visualizer_preview_cache",
        "visualizer_auth_surface",
    ):
        setattr(app.state, attribute, None)
    if failures:
        raise ExceptionGroup("WebFA runtime shutdown failed", failures)


def create_app() -> FastAPI:
    app = FastAPI(title="WebFA Runtime", version=__version__, lifespan=lifespan)
    # All lazily published Runtime/Profile services share one re-entrant lock.
    # Profile service construction resolves nested repository/storage services.
    app.state.runtime_service_init_lock = threading.RLock()

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        # FastAPI's default Pydantic response can include the rejected input.
        # WebFA control requests may contain credentials or local resource data,
        # so validation diagnostics expose only structural error metadata.
        safe_errors = []
        for error in exc.errors():
            safe_errors.append(
                {
                    "type": error.get("type", "request_validation_error"),
                    "loc": error.get("loc", ()),
                    "msg": "request field validation failed",
                }
            )
        return JSONResponse(status_code=422, content={"detail": safe_errors})
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_console_allowed_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(approvals_router, prefix="/v1")
    app.include_router(audits_router, prefix="/v1")
    app.include_router(browser_router, prefix="/v1")
    app.include_router(executions_router, prefix="/v1")
    app.include_router(github_router, prefix="/v1")
    app.include_router(health_router)
    app.include_router(mcp_config_router, prefix="/v1")
    app.include_router(monitor_control_router, prefix="/v1")
    app.include_router(monitor_router, prefix="/v1")
    app.include_router(plans_router, prefix="/v1")
    app.include_router(proofs_router, prefix="/v1")
    app.include_router(provider_connections_router, prefix="/v1")
    app.include_router(profiles_router, prefix="/v1")
    app.include_router(providers_router, prefix="/v1")
    app.include_router(transactions_router, prefix="/v1")
    app.include_router(visualizer_router, prefix="/v1")
    app.include_router(workspaces_router, prefix="/v1")
    return app


app = create_app()
