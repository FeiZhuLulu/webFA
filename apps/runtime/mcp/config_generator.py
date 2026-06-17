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
) -> dict[str, Any]:
    """Generate MCP client config for the current platform."""
    url = runtime_url or os.getenv("WEBFA_RUNTIME_URL", "http://127.0.0.1:8787")

    if platform is None:
        platform = sys.platform

    env: dict[str, str] = {"WEBFA_RUNTIME_URL": url}

    if platform == "win32":
        command = sys.executable
        args = ["-m", "apps.runtime.mcp.server"]
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

    return {
        "mcpServers": {
            "webfa": entry,
        }
    }


def generate_config_json(**kwargs: Any) -> str:
    """Generate MCP client config as JSON string."""
    return json.dumps(generate_config(**kwargs), indent=2, ensure_ascii=False)
