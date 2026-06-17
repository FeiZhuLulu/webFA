"""REST API: MCP config and status endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from apps.runtime.mcp.config_generator import generate_config

router = APIRouter()


@router.get("/mcp/config")
def get_mcp_config():
    return generate_config()


@router.get("/mcp/status")
def get_mcp_status():
    return {
        "status": "available",
        "transport": "stdio",
        "tools": [
            "webfa.discover",
            "webfa.plan",
            "webfa.preview",
            "webfa.execute",
            "webfa.get_execution",
            "webfa.get_proof",
        ],
    }
