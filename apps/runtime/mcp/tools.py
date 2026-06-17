"""MCP tool definitions for WebFA."""

from __future__ import annotations

import os
from typing import Any

from apps.runtime.mcp.errors import (
    RuntimeErrorResponse,
    RuntimeUnavailableError,
    error_response,
    map_runtime_error,
    map_unavailable_error,
    success_response,
)
from apps.runtime.mcp.runtime_client import WebFARuntimeClient

_client: WebFARuntimeClient | None = None


def get_client() -> WebFARuntimeClient:
    global _client
    if _client is None:
        _client = WebFARuntimeClient()
    return _client


CONSOLE_URL = os.getenv("WEBFA_CONSOLE_URL", "http://127.0.0.1:8788")


def tool_discover(intent: str | None = None, provider: str | None = None) -> dict[str, Any]:
    """Discover available providers and transactions."""
    client = get_client()
    try:
        providers_resp = client.list_providers()
        transactions_resp = client.list_transactions()

        providers = []
        for p in providers_resp.get("providers", []):
            providers.append({
                "id": p["id"],
                "name": p.get("name", p["id"]),
                "status": p["status"],
                "mode": "mock" if p["id"] == "mock" else "real-disabled",
            })

        transactions = []
        for t in transactions_resp.get("transactions", []):
            if provider and t.get("provider") != provider:
                continue
            transactions.append({
                "id": t["id"],
                "provider": t["provider"],
                "name": t.get("name", t["id"]),
                "risk": t.get("risk", "unknown"),
                "requires_approval": t.get("approval_level") in ("required", "user"),
                "enabled": t.get("enabled", True),
            })

        return success_response({"providers": providers, "transactions": transactions})
    except RuntimeUnavailableError as e:
        return map_unavailable_error(e)
    except RuntimeErrorResponse as e:
        return map_runtime_error(e)


def tool_plan(transaction_id: str, input: dict[str, Any]) -> dict[str, Any]:
    """Create a transaction plan."""
    client = get_client()
    try:
        result = client.create_plan({"transaction_id": transaction_id, "input": input})
        return success_response({
            "plan_id": result["id"],
            "workspace_id": result["workspace_id"],
            "transaction_id": result["transaction_id"],
            "status": result["status"],
            "risk": result["risk"],
            "requires_preview": True,
            "requires_approval": result["risk"] in ("medium", "high", "critical"),
            "next": {
                "tool": "webfa.preview",
                "arguments": {"plan_id": result["id"]},
            },
        })
    except RuntimeUnavailableError as e:
        return map_unavailable_error(e)
    except RuntimeErrorResponse as e:
        return map_runtime_error(e)


def tool_preview(plan_id: str) -> dict[str, Any]:
    """Preview a plan: generate diff, policy check, create approval."""
    client = get_client()
    try:
        result = client.preview_plan(plan_id)
        return success_response({
            "plan_id": result["plan_id"],
            "status": result["status"],
            "risk": result["risk"],
            "approval_required": result["approval_required"],
            "approval_id": result.get("approval_id"),
            "approval_url": f"{CONSOLE_URL}/approvals/{result.get('approval_id', '')}",
            "diff_hash": result.get("diff_hash"),
            "policy": result.get("policy"),
            "preview": result.get("preview"),
            "next": {
                "human_action": "Open approval_url and approve in WebFA Desktop Console.",
                "after_approval_tool": "webfa.execute",
            },
        })
    except RuntimeUnavailableError as e:
        return map_unavailable_error(e)
    except RuntimeErrorResponse as e:
        return map_runtime_error(e)


def tool_execute(plan_id: str, approval_token: str, idempotency_key: str | None = None) -> dict[str, Any]:
    """Execute an approved plan."""
    client = get_client()
    try:
        payload: dict[str, Any] = {
            "plan_id": plan_id,
            "approval_token": approval_token,
        }
        if idempotency_key:
            payload["idempotency_key"] = idempotency_key

        result = client.execute(payload)
        return success_response({
            "execution_id": result["id"],
            "plan_id": result["plan_id"],
            "status": result["status"],
            "proof_id": result.get("proof_id"),
            "verification": result.get("result", {}).get("verification"),
        })
    except RuntimeUnavailableError as e:
        return map_unavailable_error(e)
    except RuntimeErrorResponse as e:
        return map_runtime_error(e)


def tool_get_execution(execution_id: str) -> dict[str, Any]:
    """Get execution status and details."""
    client = get_client()
    try:
        result = client.get_execution(execution_id)
        return success_response({
            "execution_id": result["id"],
            "plan_id": result["plan_id"],
            "status": result["status"],
            "steps": [
                {"name": s["step_name"], "status": s["status"]}
                for s in result.get("steps", [])
            ],
            "proof_id": result.get("proof_id"),
            "result": result.get("result"),
        })
    except RuntimeUnavailableError as e:
        return map_unavailable_error(e)
    except RuntimeErrorResponse as e:
        return map_runtime_error(e)


def tool_get_proof(proof_id: str) -> dict[str, Any]:
    """Get proof bundle."""
    client = get_client()
    try:
        result = client.get_proof(proof_id)
        proof_data = result.get("proof", {})
        return success_response({
            "proof_id": result["id"],
            "execution_id": result["execution_id"],
            "provider": result["provider"],
            "resource_url": result.get("url"),
            "hash": result.get("hash"),
            "verification": proof_data.get("verification"),
        })
    except RuntimeUnavailableError as e:
        return map_unavailable_error(e)
    except RuntimeErrorResponse as e:
        return map_runtime_error(e)
