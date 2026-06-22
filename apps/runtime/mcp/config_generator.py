"""MCP config generator: produces client configuration for different platforms."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def generate_config(
    runtime_url: str | None = None,
    platform: str | None = None,
    cwd: str | None = None,
    installed: bool = True,
    agent_id: str = "webfa-agent",
    client: str = "mcpServers",
) -> dict[str, Any]:
    """Generate MCP client config for the current platform."""
    url = runtime_url or os.getenv("WEBFA_RUNTIME_URL", "http://127.0.0.1:8787")

    if platform is None:
        platform = sys.platform

    env: dict[str, str] = {"WEBFA_RUNTIME_URL": url, "WEBFA_AGENT_ID": agent_id}

    if installed:
        command = "webfa-mcp"
        args = []
    else:
        command = sys.executable
        args = ["-m", "apps.runtime.mcp.server"]

    entry: dict[str, Any] = {
        "command": command,
        "args": args,
        "env": env,
    }

    if cwd:
        entry["cwd"] = cwd

    if client == "opencode":
        command = [entry["command"], *entry["args"]]
        opencode_entry: dict[str, Any] = {
            "type": "local",
            "enabled": True,
            "command": command,
            "environment": env,
        }
        if cwd:
            opencode_entry["cwd"] = cwd
        return {"mcp": {"webfa": opencode_entry}}

    return {"mcpServers": {"webfa": entry}}


def generate_config_json(**kwargs: Any) -> str:
    """Generate MCP client config as JSON string."""
    return json.dumps(generate_config(**kwargs), indent=2, ensure_ascii=False)
