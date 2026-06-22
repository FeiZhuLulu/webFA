"""Unit tests for MCP error mapping."""

from apps.runtime.mcp.errors import (
    RuntimeErrorResponse,
    RuntimeUnavailableError,
    error_response,
    map_runtime_error,
    map_unavailable_error,
    success_response,
)


def test_map_403_approval_required():
    exc = RuntimeErrorResponse(403, {"detail": "No approved approval found"})
    result = map_runtime_error(exc)
    assert result["ok"] is False
    assert result["error"]["code"] == "approval_required"
    assert result["error"]["runtime_status"] == 403


def test_map_403_invalid_token():
    exc = RuntimeErrorResponse(403, {"detail": "Invalid approval token"})
    result = map_runtime_error(exc)
    assert result["error"]["code"] == "invalid_token"


def test_map_403_expired():
    exc = RuntimeErrorResponse(403, {"detail": "Approval has expired"})
    result = map_runtime_error(exc)
    assert result["error"]["code"] == "approval_expired"


def test_map_409_hash_mismatch():
    exc = RuntimeErrorResponse(409, {"detail": "Plan has been tampered with (plan_hash mismatch)"})
    result = map_runtime_error(exc)
    assert result["error"]["code"] == "hash_mismatch"


def test_map_409_agent_busy():
    exc = RuntimeErrorResponse(
        409,
        {
            "detail": {
                "code": "agent_busy",
                "message": "WebFA is currently controlled by agent 'opencode'",
                "active_agent_id": "opencode",
            }
        },
    )
    result = map_runtime_error(exc)
    assert result["error"]["code"] == "agent_busy"
    assert result["error"]["message"]["active_agent_id"] == "opencode"


def test_map_404():
    exc = RuntimeErrorResponse(404, {"detail": "Plan not found"})
    result = map_runtime_error(exc)
    assert result["error"]["code"] == "not_found"


def test_map_400():
    exc = RuntimeErrorResponse(400, {"detail": "Unknown transaction"})
    result = map_runtime_error(exc)
    assert result["error"]["code"] == "invalid_request"


def test_map_unavailable():
    exc = RuntimeUnavailableError("Runtime unreachable at http://127.0.0.1:8787")
    result = map_unavailable_error(exc)
    assert result["ok"] is False
    assert result["error"]["code"] == "runtime_unavailable"


def test_success_response():
    result = success_response({"plan_id": "plan_1", "status": "pending_preview"})
    assert result["ok"] is True
    assert result["plan_id"] == "plan_1"


def test_error_response():
    result = error_response("approval_required", "Need approval")
    assert result["ok"] is False
    assert result["error"]["code"] == "approval_required"
