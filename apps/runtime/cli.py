from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

from apps.runtime.login import resolve_login_target, run_login_window
from apps.runtime.mcp.config_generator import DEFAULT_EXTERNAL_AGENT_ID, generate_config
from apps.runtime.mcp.runtime_client import WebFARuntimeClient
from apps.runtime.process import ensure_runtime, get_runtime_url, runtime_health, runtime_http_options, wait_for_runtime
from apps.runtime.version import __version__
from storage.file_store import ensure_webfa_data_dir


def main_runtime(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="webfa-runtime", description="Start the WebFA local runtime.")
    parser.add_argument("command", nargs="?", default="start", choices=["start", "status"])
    parser.add_argument("--host", default=os.getenv("WEBFA_API_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("WEBFA_API_PORT", "8787")))
    args = parser.parse_args(argv)

    return _run_runtime(args.command, args.host, args.port)


def _run_runtime(command: str, host: str, port: int) -> int:
    runtime_url = f"http://{host}:{port}"
    if command == "status":
        health = runtime_health(runtime_url)
        if health is None:
            print(json.dumps({"status": "unreachable", "runtime_url": runtime_url}, indent=2))
            return 1
        print(json.dumps(health, indent=2, ensure_ascii=False))
        return 0

    os.environ.setdefault("WEBFA_BROWSER_DRIVER", "managed-chromium")
    os.environ["WEBFA_API_HOST"] = host
    os.environ["WEBFA_API_PORT"] = str(port)
    os.environ["WEBFA_RUNTIME_URL"] = runtime_url
    import uvicorn

    uvicorn.run("apps.runtime.main:app", host=host, port=port, log_level="info")
    return 0


def main_mcp(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="webfa-mcp", description="Run the WebFA MCP stdio server.")
    parser.add_argument("--runtime-url", default=None)
    parser.add_argument("--no-auto-start", action="store_true")
    args = parser.parse_args(argv)

    return _run_mcp(args.runtime_url, no_auto_start=args.no_auto_start)


def _run_mcp(runtime_url_arg: str | None, *, no_auto_start: bool) -> int:
    runtime_url = get_runtime_url(runtime_url_arg)
    os.environ["WEBFA_RUNTIME_URL"] = runtime_url
    runtime_process = ensure_runtime(runtime_url, auto_start=not no_auto_start)

    try:
        from apps.runtime.mcp.server import main

        main()
        return 0
    finally:
        runtime_process.close()


def main_webfa(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="webfa",
        description="WebFA internet Runtime helper for independent external Agents.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status", help="Print Runtime health.")
    status_parser.add_argument("--runtime-url", default=None)

    config_parser = subparsers.add_parser("mcp-config", help="Print MCP client config JSON.")
    config_parser.add_argument("--runtime-url", default=None)
    config_parser.add_argument("--source-mode", action="store_true", help="Use python -m apps.runtime.mcp.server style config.")
    config_parser.add_argument("--cwd", default=None)
    config_parser.add_argument(
        "--agent-id",
        default=DEFAULT_EXTERNAL_AGENT_ID,
        help="External Agent identity; use a distinct value for every Agent client.",
    )
    config_parser.add_argument("--client", default="mcpServers", choices=["mcpServers", "opencode"])

    subparsers.add_parser("paths", help="Print WebFA local data paths.")

    doctor_parser = subparsers.add_parser("doctor", help="Run a local WebFA smoke test.")
    doctor_parser.add_argument("--runtime-url", default=None)
    doctor_parser.add_argument("--no-auto-start", action="store_true")

    login_parser = subparsers.add_parser("login", help="Open a manual login window for the WebFA profile.")
    login_parser.add_argument("site", nargs="?", help="Known site name, for example: github")
    login_parser.add_argument("--url", default=None, help="Login URL to open manually.")

    runtime_parser = subparsers.add_parser("runtime", help="Start or inspect the local Runtime sidecar.")
    runtime_parser.add_argument("runtime_command", nargs="?", default="start", choices=["start", "status"])
    runtime_parser.add_argument("--host", default=os.getenv("WEBFA_API_HOST", "127.0.0.1"))
    runtime_parser.add_argument("--port", type=int, default=int(os.getenv("WEBFA_API_PORT", "8787")))

    mcp_parser = subparsers.add_parser("mcp", help="Run the Agent-owned MCP stdio bridge.")
    mcp_parser.add_argument("--runtime-url", default=None)
    mcp_parser.add_argument("--no-auto-start", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "status":
        return _cmd_status(args.runtime_url)
    if args.command == "mcp-config":
        config = generate_config(
            runtime_url=args.runtime_url,
            installed=not args.source_mode,
            cwd=args.cwd,
            agent_id=args.agent_id,
            client=args.client,
        )
        print(json.dumps(config, indent=2, ensure_ascii=False))
        return 0
    if args.command == "paths":
        paths = ensure_webfa_data_dir()
        print(json.dumps({key: str(value) for key, value in paths.items()}, indent=2, ensure_ascii=False))
        return 0
    if args.command == "doctor":
        return _cmd_doctor(args.runtime_url, auto_start=not args.no_auto_start)
    if args.command == "login":
        return _cmd_login(args.site, args.url)
    if args.command == "runtime":
        return _run_runtime(args.runtime_command, args.host, args.port)
    if args.command == "mcp":
        return _run_mcp(args.runtime_url, no_auto_start=args.no_auto_start)
    raise ValueError(f"unsupported command: {args.command}")


def _cmd_status(runtime_url: str | None) -> int:
    url = get_runtime_url(runtime_url)
    health = runtime_health(url)
    if health is None:
        print(json.dumps({"status": "unreachable", "runtime_url": url}, indent=2))
        return 1
    print(json.dumps(health, indent=2, ensure_ascii=False))
    return 0


def _cmd_doctor(runtime_url: str | None, auto_start: bool) -> int:
    checks: list[dict[str, Any]] = []
    runtime_process = None
    original_home = os.environ.get("WEBFA_HOME")
    original_headless = os.environ.get("WEBFA_BROWSER_HEADLESS")
    temp_home = tempfile.TemporaryDirectory(ignore_cleanup_errors=True) if original_home is None else None
    if temp_home is not None:
        os.environ["WEBFA_HOME"] = str(Path(temp_home.name) / "WebFA")
    os.environ["WEBFA_BROWSER_HEADLESS"] = "1"
    try:
        _record(checks, "import", True, "Python package imports are available")
        runtime_process = ensure_runtime(runtime_url, auto_start=auto_start)
        health = wait_for_runtime(runtime_process.runtime_url)
        browser = health.get("browser", {})
        _record(checks, "runtime_health", True, runtime_process.runtime_url)
        _record(checks, "managed_chromium_default", browser.get("selected_driver") == "managed-chromium", str(browser))
        _record(checks, "chromium_executable", browser.get("executable_found") is not False, str(browser))
        _record(checks, "mcp_tools", _mcp_tools_are_default(runtime_process.runtime_url), "default browser tools only")
        _record(checks, "browser_loop", _run_browser_loop(runtime_process.runtime_url), "local fixture object-action loop")
        passed = all(check["ok"] for check in checks)
        print(json.dumps({"status": "pass" if passed else "fail", "checks": checks}, indent=2, ensure_ascii=False))
        return 0 if passed else 1
    except Exception as exc:
        _record(checks, "doctor", False, str(exc))
        print(json.dumps({"status": "fail", "checks": checks}, indent=2, ensure_ascii=False))
        return 1
    finally:
        if runtime_process is not None:
            runtime_process.close()
        if original_home is None:
            os.environ.pop("WEBFA_HOME", None)
        else:
            os.environ["WEBFA_HOME"] = original_home
        if original_headless is None:
            os.environ.pop("WEBFA_BROWSER_HEADLESS", None)
        else:
            os.environ["WEBFA_BROWSER_HEADLESS"] = original_headless
        if temp_home is not None:
            with suppress(OSError, PermissionError):
                temp_home.cleanup()


def _cmd_login(site: str | None, url: str | None) -> int:
    try:
        target = resolve_login_target(site=site, url=url)
        result = run_login_window(target)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, indent=2, ensure_ascii=False))
        return 1


def _record(checks: list[dict[str, Any]], name: str, ok: bool, detail: str) -> None:
    checks.append({"name": name, "ok": ok, "detail": detail})


def _mcp_tools_are_default(runtime_url: str) -> bool:
    import httpx

    response = httpx.get(f"{runtime_url}/v1/mcp/status", timeout=5, **runtime_http_options(runtime_url))
    response.raise_for_status()
    tools = response.json().get("tools")
    return tools == ["webfa.open_url", "webfa.observe", "webfa.act", "webfa.get_tabs", "webfa.switch_tab"]


def _run_browser_loop(runtime_url: str) -> bool:
    html = """
    <!doctype html>
    <title>WebFA Doctor</title>
    <form onsubmit="event.preventDefault(); result.textContent = 'Hello ' + nameInput.value;">
      <label for="nameInput">Your name</label>
      <input id="nameInput" name="name" placeholder="Your name">
      <button type="submit">Submit</button>
    </form>
    <p id="result">Waiting</p>
    """
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "doctor.html"
        page.write_text(html, encoding="utf-8")
        client = WebFARuntimeClient(base_url=runtime_url, agent_id="webfa-doctor")
        try:
            client.open_url(page.as_uri())
            observed = client.observe({"mode": "page", "detail": "full", "limit": 50})
            objects = observed["objects"]
            field = next(item for item in objects if item.get("role") in {"textbox", "searchbox"})
            form = next(item for item in objects if item.get("role") == "form")
            client.browser_act(
                {
                    "operation": "set_value",
                    "target": field["id"],
                    "arguments": {"value": "WebFA"},
                    "expected_object_version": field["version"],
                }
            )
            client.browser_act({"operation": "submit", "target": form["id"]})
            final_state = client.observe(
                {
                    "mode": "query",
                    "query": {"text_contains": "Hello WebFA"},
                    "detail": "full",
                }
            )
        finally:
            client.close()
    body = str(final_state).lower()
    forbidden = ("cookie", "localstorage", "sessionstorage", "token", "full_html", "full_dom")
    verified = any(
        "Hello WebFA" in (item.get("text") or item.get("name") or "")
        for item in final_state["objects"]
    )
    return verified and all(term not in body for term in forbidden)


if __name__ == "__main__":
    raise SystemExit(main_webfa())
