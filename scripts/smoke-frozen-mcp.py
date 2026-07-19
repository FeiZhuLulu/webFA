from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


EXPECTED_TOOLS = {
    "webfa.open_url",
    "webfa.observe",
    "webfa.act",
    "webfa.get_tabs",
    "webfa.switch_tab",
}


async def run_flow(
    mcp_config: dict[str, Any],
    working_directory: Path,
    ready_file: Path | None = None,
    release_file: Path | None = None,
) -> dict[str, Any]:
    fixture = working_directory / "frozen-mcp-flow.html"
    fixture.write_text(
        """<!doctype html>
<html><head><meta charset="utf-8"><title>WebFA Frozen MCP Smoke</title></head>
<body><main><h1>WebFA Frozen MCP Smoke</h1>
<form onsubmit="event.preventDefault(); result.textContent = 'Hello ' + nameInput.value;">
<label for="nameInput">Your name</label><input id="nameInput" name="name" placeholder="Your name">
<button type="submit">Submit</button></form><p id="result">Waiting</p></main></body></html>
""",
        encoding="utf-8",
    )
    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper()
        not in {
            "PYTHONHOME",
            "PYTHONPATH",
            "WEBFA_ENABLE_LEGACY_TRANSACTION",
            "WEBFA_RUNTIME_INSTANCE_ID",
        }
    }
    command = mcp_config.get("command")
    command_args = mcp_config.get("args")
    config_env = mcp_config.get("env")
    if not isinstance(command, str) or not command:
        raise AssertionError("Advertised MCP command is invalid")
    if not isinstance(command_args, list) or not all(isinstance(item, str) for item in command_args):
        raise AssertionError("Advertised MCP arguments are invalid")
    if not isinstance(config_env, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in config_env.items()
    ):
        raise AssertionError("Advertised MCP environment is invalid")
    env.update(config_env)
    params = StdioServerParameters(
        command=command,
        args=command_args,
        cwd=working_directory,
        env=env,
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool_names = {tool.name for tool in tools.tools}
            if tool_names != EXPECTED_TOOLS:
                raise AssertionError(f"Frozen MCP tools changed: {sorted(tool_names)}")

            opened = _tool_json(
                await session.call_tool("webfa.open_url", {"url": fixture.as_uri()})
            )
            if opened["state"]["title"] != "WebFA Frozen MCP Smoke":
                raise AssertionError(f"Frozen MCP opened the wrong document: {opened}")
            observed_before = _tool_json(
                await session.call_tool(
                    "webfa.observe",
                    {"mode": "page", "detail": "full", "limit": 50},
                )
            )
            initial = observed_before["state"]
            field = _find(initial, roles={"textbox", "searchbox"}, name="Your name")
            form = _find(initial, roles={"form"})

            acted = _tool_json(
                await session.call_tool(
                    "webfa.act",
                    {
                        "operation": "set_value",
                        "target": field["id"],
                        "arguments": {"value": "Release"},
                        "expected_object_version": field["version"],
                    },
                )
            )
            if acted.get("operation") != "set_value":
                raise AssertionError(f"Unexpected frozen MCP act result: {acted}")
            _tool_json(
                await session.call_tool(
                    "webfa.act",
                    {"operation": "submit", "target": form["id"]},
                )
            )
            observed = _tool_json(
                await session.call_tool(
                    "webfa.observe",
                    {
                        "mode": "query",
                        "query": {"text_contains": "Hello Release"},
                        "detail": "full",
                    },
                )
            )
            if not any(
                "Hello Release" in (item.get("text") or item.get("name") or "")
                for item in observed["state"]["objects"]
            ):
                raise AssertionError("Frozen MCP observe did not verify the semantic action")
            result = {
                "status": "pass",
                "tools": sorted(tool_names),
                "document_id": initial["document_id"],
                "flow": ["initialize", "tools/list", "open", "observe", "act", "observe"],
            }
            if ready_file is not None:
                if release_file is None:
                    raise AssertionError("A release file is required when MCP hold mode is enabled")
                with ready_file.open("x", encoding="utf-8") as handle:
                    json.dump(result, handle, ensure_ascii=False)
                    handle.write("\n")
                for _ in range(2_400):
                    if release_file.exists():
                        break
                    await asyncio.sleep(0.05)
                else:
                    raise TimeoutError("Timed out waiting to release the frozen MCP session")
            return result


def _tool_json(result: Any) -> dict[str, Any]:
    if result.isError:
        raise AssertionError(f"Frozen MCP tool returned an error: {result}")
    if not result.content:
        raise AssertionError("Frozen MCP tool returned no content")
    payload = json.loads(result.content[0].text)
    if payload.get("ok") is not True:
        raise AssertionError(f"Frozen MCP tool failed: {payload}")
    return payload


def _find(state: dict[str, Any], *, roles: set[str], name: str | None = None) -> dict[str, Any]:
    for item in state["objects"]:
        if item.get("role") not in roles:
            continue
        if name is not None and item.get("name") != name:
            continue
        return item
    raise AssertionError(f"Frozen MCP WebObject not found: roles={roles}, name={name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mcp_config", type=Path)
    parser.add_argument("working_directory", type=Path)
    parser.add_argument("--ready-file", type=Path)
    parser.add_argument("--release-file", type=Path)
    args = parser.parse_args()
    if (args.ready_file is None) != (args.release_file is None):
        parser.error("--ready-file and --release-file must be provided together")
    mcp_config = json.loads(args.mcp_config.read_text(encoding="utf-8"))
    result = asyncio.run(
        asyncio.wait_for(
            run_flow(
                mcp_config,
                args.working_directory.resolve(),
                args.ready_file.resolve() if args.ready_file else None,
                args.release_file.resolve() if args.release_file else None,
            ),
            timeout=150 if args.ready_file else 90,
        )
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
