"""REST API: MCP config and status endpoints."""

from __future__ import annotations

import os

from fastapi import APIRouter

from apps.runtime.mcp.config_generator import generate_config

router = APIRouter()


@router.get("/mcp/config")
def get_mcp_config():
    return generate_config()


@router.get("/mcp/status")
def get_mcp_status():
    tools = [
        "webfa.open_url",
        "webfa.observe",
        "webfa.act",
        "webfa.get_tabs",
        "webfa.switch_tab",
    ]
    if os.getenv("WEBFA_ENABLE_LEGACY_TRANSACTION") == "1":
        tools += [
            "webfa.discover",
            "webfa.plan",
            "webfa.preview",
            "webfa.execute",
            "webfa.get_execution",
            "webfa.get_proof",
        ]
    return {
        "status": "available",
        "transport": "stdio",
        "tools": tools,
    }
