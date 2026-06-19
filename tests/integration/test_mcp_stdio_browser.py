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
from browser.managed_chromium_host import _find_chromium_executable
from storage.db import reset_engine_for_tests


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PAGE = Path(__file__).resolve().parents[1] / "fixtures" / "agent_validation_page.html"
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
    pytest.importorskip("playwright.sync_api")
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    monkeypatch.delenv("WEBFA_BROWSER_DRIVER", raising=False)
    monkeypatch.delenv("WEBFA_ENABLE_LEGACY_TRANSACTION", raising=False)
    reset_engine_for_tests()

    _run_runtime_with_mcp_flow(tmp_path)


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
            assert "url_parts" in descriptions["webfa.observe"]
            assert "prefer webfa.open_url" in descriptions["webfa.act"]

            opened = _tool_json(await session.call_tool("webfa.open_url", {"url": FIXTURE_PAGE.as_uri()}))
            state = opened["state"]
            assert state["title"] == "WebFA Agent Validation"
            assert state["url_parts"]["scheme"] == "file"
            assert state["url_parts"]["path"].endswith("agent_validation_page.html")
            assert "WebFA Agent Validation" in state["visible_text"]
            assert "cookie" not in str(state).lower()
            assert "localstorage" not in str(state).lower()

            name_el = _find_element(state, placeholder="Your name")
            button_el = _find_element(state, role="button")

            typed = _tool_json(await session.call_tool(
                "webfa.act",
                {"action": "type", "target": name_el["id"], "payload": {"text": "Fei"}},
            ))
            typed_el = _find_element(typed["state"], placeholder="Your name")
            assert typed_el["value"] == "Fei"

            clicked = _tool_json(await session.call_tool(
                "webfa.act",
                {"action": "click", "target": button_el["id"]},
            ))
            assert "Hello Fei" in clicked["state"]["visible_text"]

            observed = _tool_json(await session.call_tool("webfa.observe"))
            assert "Hello Fei" in observed["state"]["visible_text"]


def _tool_json(result: Any) -> dict[str, Any]:
    assert not getattr(result, "isError", False)
    assert result.content
    return json.loads(result.content[0].text)


def _find_element(state: dict[str, Any], **criteria: str) -> dict[str, Any]:
    for element in state["interactive_elements"]:
        if all(element.get(key) == value for key, value in criteria.items()):
            return element
    raise AssertionError(f"Element not found: {criteria}")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_runtime(port: int) -> None:
    deadline = time.time() + 20
    url = f"http://127.0.0.1:{port}/health"
    while time.time() < deadline:
        try:
            response = httpx.get(url, timeout=1)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise TimeoutError(f"Runtime did not start at {url}")
