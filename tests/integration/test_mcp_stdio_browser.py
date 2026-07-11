from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from apps.runtime.main import create_app
from apps.runtime.process import runtime_http_options
from browser.managed_chromium_host import _find_chromium_executable
from storage.db import reset_engine_for_tests


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PAGE = Path(__file__).resolve().parents[1] / "fixtures" / "agent_validation_page.html"
DIALOG_PAGE = Path(__file__).resolve().parents[1] / "fixtures" / "dialog_confirm_page.html"
EXPECTED_BROWSER_TOOLS = {
    "webfa.open_url",
    "webfa.observe",
    "webfa.act",
    "webfa.get_tabs",
    "webfa.switch_tab",
}
FORBIDDEN_DEFAULT_TOOLS = {
    "webfa.plan",
    "webfa.preview",
    "webfa.execute",
    "webfa.get_proof",
    "github.create_repo",
    "hf.upload_model",
    "raw_playwright",
    "raw_cdp",
    "raw_selector",
}


def test_mcp_stdio_browser_observe_act_observe(monkeypatch, tmp_path: Path):
    pytest.importorskip("websockets.sync.client")
    try:
        _find_chromium_executable()
    except RuntimeError as exc:
        pytest.skip(str(exc))
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    monkeypatch.delenv("WEBFA_BROWSER_DRIVER", raising=False)
    monkeypatch.delenv("WEBFA_ENABLE_LEGACY_TRANSACTION", raising=False)
    reset_engine_for_tests()

    _run_runtime_with_mcp_flow(tmp_path)


def test_mcp_stdio_dialog_required_and_dismiss(monkeypatch, tmp_path: Path):
    pytest.importorskip("websockets.sync.client")
    try:
        _find_chromium_executable()
    except RuntimeError as exc:
        pytest.skip(str(exc))

    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    monkeypatch.delenv("WEBFA_BROWSER_DRIVER", raising=False)
    monkeypatch.delenv("WEBFA_ENABLE_LEGACY_TRANSACTION", raising=False)
    reset_engine_for_tests()

    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, name="webfa-test-runtime", daemon=True)
    thread.start()
    try:
        _wait_for_runtime(port)
        asyncio.run(_run_mcp_dialog_flow(port, tmp_path))
    finally:
        server.should_exit = True
        thread.join(timeout=20)


def test_mcp_stdio_private_url_blocked(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_PRIVATE_URL_POLICY", "block")
    monkeypatch.delenv("WEBFA_ENABLE_LEGACY_TRANSACTION", raising=False)
    reset_engine_for_tests()

    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, name="webfa-test-runtime", daemon=True)
    thread.start()
    try:
        _wait_for_runtime(port)
        asyncio.run(_run_mcp_blocked_url_flow(port, tmp_path))
    finally:
        server.should_exit = True
        thread.join(timeout=20)


def test_mcp_stdio_managed_chromium_observe_act_observe(monkeypatch, tmp_path: Path):
    pytest.importorskip("websockets.sync.client")
    try:
        _find_chromium_executable()
    except RuntimeError as exc:
        pytest.skip(str(exc))

    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_DRIVER", "managed-chromium")
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    monkeypatch.delenv("WEBFA_ENABLE_LEGACY_TRANSACTION", raising=False)
    reset_engine_for_tests()

    _run_runtime_with_mcp_flow(tmp_path)


def _run_runtime_with_mcp_flow(tmp_path: Path) -> None:
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(),
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
    )
    thread = threading.Thread(target=server.run, name="webfa-test-runtime", daemon=True)
    thread.start()

    try:
        _wait_for_runtime(port)
        asyncio.run(_run_mcp_browser_flow(port, tmp_path))
    finally:
        server.should_exit = True
        thread.join(timeout=20)


async def _run_mcp_browser_flow(port: int, tmp_path: Path) -> None:
    env = os.environ.copy()
    env["WEBFA_RUNTIME_URL"] = f"http://127.0.0.1:{port}"
    env["WEBFA_HOME"] = str(tmp_path / "WebFA")
    env["WEBFA_BROWSER_HEADLESS"] = "1"
    env.pop("WEBFA_ENABLE_LEGACY_TRANSACTION", None)

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "apps.runtime.mcp.server"],
        cwd=ROOT,
        env=env,
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            assert names == EXPECTED_BROWSER_TOOLS
            assert FORBIDDEN_DEFAULT_TOOLS.isdisjoint(names)
            descriptions = {tool.name: tool.description or "" for tool in tools.tools}
            assert "constructed URLs" in descriptions["webfa.open_url"]
            assert "WebState" in descriptions["webfa.observe"]
            assert "semantic operation" in descriptions["webfa.act"]
            schemas = {tool.name: tool.inputSchema for tool in tools.tools}
            observe_properties = schemas["webfa.observe"]["properties"]
            act_properties = schemas["webfa.act"]["properties"]
            assert {"mode", "target", "query", "range", "since_revision", "detail", "limit"}.issubset(observe_properties)
            assert "operation" in act_properties
            assert "action" not in act_properties
            operation_enum = set(act_properties["operation"]["enum"])
            assert {"set_value", "submit", "activate", "dismiss"}.issubset(operation_enum)
            assert operation_enum.isdisjoint({"click", "double_click", "type", "press", "focus", "select"})

            opened = _tool_json(await session.call_tool("webfa.open_url", {"url": FIXTURE_PAGE.as_uri()}))
            state = opened["state"]
            assert state["title"] == "WebFA Agent Validation"
            assert state["url"].endswith("agent_validation_page.html")
            assert state["document_id"]
            assert state["document_revision"] >= 1
            assert "cookie" not in str(state).lower()
            assert "localstorage" not in str(state).lower()

            field = _find_web_object(state, roles={"textbox", "searchbox"}, name="Your name")
            form = _find_web_object(state, roles={"form"})
            assert "set_value" in field["capabilities"]
            assert "submit" in form["capabilities"]

            typed = _tool_json(
                await session.call_tool(
                    "webfa.act",
                    {
                        "operation": "set_value",
                        "target": field["id"],
                        "arguments": {"value": "Fei"},
                        "expected_object_version": field["version"],
                    },
                )
            )
            assert typed["operation"] == "set_value"
            assert typed["current_object_version"] >= field["version"]

            submitted = _tool_json(
                await session.call_tool(
                    "webfa.act",
                    {"operation": "submit", "target": form["id"]},
                )
            )
            assert submitted["operation"] == "submit"

            observed = _tool_json(
                await session.call_tool(
                    "webfa.observe",
                    {
                        "mode": "query",
                        "query": {"text_contains": "Hello Fei"},
                        "detail": "full",
                    },
                )
            )
            assert any("Hello Fei" in (item.get("text") or item.get("name") or "") for item in observed["state"]["objects"])


async def _run_mcp_dialog_flow(port: int, tmp_path: Path) -> None:
    env = os.environ.copy()
    env["WEBFA_RUNTIME_URL"] = f"http://127.0.0.1:{port}"
    env["WEBFA_HOME"] = str(tmp_path / "WebFA")
    env["WEBFA_BROWSER_HEADLESS"] = "1"
    env.pop("WEBFA_ENABLE_LEGACY_TRANSACTION", None)

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "apps.runtime.mcp.server"],
        cwd=ROOT,
        env=env,
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            opened = _tool_json(await session.call_tool("webfa.open_url", {"url": DIALOG_PAGE.as_uri()}))
            button = _find_web_object(opened["state"], roles={"button"})
            blocked = await session.call_tool(
                "webfa.act",
                {"operation": "activate", "target": button["id"]},
            )
            payload = _tool_error_json(blocked)
            assert payload["error"]["code"] == "dialog_required"
            assert payload["error"].get("recover_hint")

            dialog_state = _tool_json(
                await session.call_tool(
                    "webfa.observe",
                    {"mode": "query", "query": {"role": "dialog"}, "detail": "full"},
                )
            )["state"]
            dialog = _find_web_object(dialog_state, roles={"dialog"})
            dismissed = _tool_json(
                await session.call_tool(
                    "webfa.act",
                    {"operation": "dismiss", "target": dialog["id"]},
                )
            )
            assert dismissed["state"]["dialogs"] == []
            observed = _tool_json(
                await session.call_tool(
                    "webfa.observe",
                    {"mode": "query", "query": {"text_contains": "dismissed"}, "detail": "full"},
                )
            )
            assert any("dismissed" in (item.get("text") or "").lower() for item in observed["state"]["objects"])


async def _run_mcp_blocked_url_flow(port: int, tmp_path: Path) -> None:
    env = os.environ.copy()
    env["WEBFA_RUNTIME_URL"] = f"http://127.0.0.1:{port}"
    env["WEBFA_HOME"] = str(tmp_path / "WebFA")
    env["WEBFA_PRIVATE_URL_POLICY"] = "block"
    env.pop("WEBFA_ENABLE_LEGACY_TRANSACTION", None)

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "apps.runtime.mcp.server"],
        cwd=ROOT,
        env=env,
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            blocked = await session.call_tool("webfa.open_url", {"url": "http://127.0.0.1:8787/"})
            payload = _tool_error_json(blocked)
            assert payload["error"]["code"] == "private_url_blocked"
            assert payload["error"].get("recover_hint")


def _tool_json(result: Any) -> dict[str, Any]:
    assert not getattr(result, "isError", False)
    assert result.content
    payload = json.loads(result.content[0].text)
    assert payload.get("ok") is not False
    return payload


def _tool_error_json(result: Any) -> dict[str, Any]:
    assert result.content
    payload = json.loads(result.content[0].text)
    assert payload.get("ok") is False
    assert "error" in payload
    return payload


def _find_web_object(
    state: dict[str, Any],
    *,
    roles: set[str],
    name: str | None = None,
) -> dict[str, Any]:
    for item in state["objects"]:
        if item.get("role") not in roles:
            continue
        if name is not None and item.get("name") != name:
            continue
        return item
    raise AssertionError(f"WebObject not found: roles={roles}, name={name}")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_runtime(port: int) -> None:
    deadline = time.time() + 20
    url = f"http://127.0.0.1:{port}/health"
    while time.time() < deadline:
        try:
            response = httpx.get(url, timeout=1, **runtime_http_options(url))
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise TimeoutError(f"Runtime did not start at {url}")
