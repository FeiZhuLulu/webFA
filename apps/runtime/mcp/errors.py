"""MCP error mapping: converts Runtime HTTP errors to MCP-friendly error dicts."""

from __future__ import annotations

from typing import Any

from apps.runtime.mcp.runtime_client import RuntimeErrorResponse, RuntimeUnavailableError


ERROR_CODE_MAP: dict[int, str] = {
    400: "invalid_request",
    403: "forbidden",
    404: "not_found",
    409: "invalid_state",
    422: "validation_error",
    500: "runtime_error",
}


def map_runtime_error(exc: RuntimeErrorResponse) -> dict[str, Any]:
    code = ERROR_CODE_MAP.get(exc.status_code, "runtime_error")
    detail = exc.body.get("detail", str(exc.body))
    if isinstance(detail, dict) and isinstance(detail.get("code"), str):
        code = detail["code"]

    # Refine code based on detail content (check specific patterns first)
    detail_lower = str(detail).lower()
    if exc.status_code == 403:
        if "expired" in detail_lower:
            code = "approval_expired"
        elif "invalid" in detail_lower and "token" in detail_lower:
            code = "invalid_token"
        elif "token" in detail_lower and "mismatch" in detail_lower:
            code = "invalid_token"
        elif "approval" in detail_lower:
            code = "approval_required"
        elif "token" in detail_lower:
            code = "invalid_token"
    elif exc.status_code == 409:
        if "hash" in str(detail).lower() or "tamper" in str(detail).lower():
            code = "hash_mismatch"

    return {
        "ok": False,
        "error": {
            "code": code,
            "message": detail,
            "runtime_status": exc.status_code,
        },
    }


def map_unavailable_error(exc: RuntimeUnavailableError) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": "runtime_unavailable",
            "message": str(exc),
        },
    }


def error_response(code: str, message: str, details: dict | None = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if details:
        err["details"] = details
    return {"ok": False, "error": err}


def success_response(data: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, **data}
