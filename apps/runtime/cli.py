from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from apps.runtime.mcp.config_generator import generate_config
from apps.runtime.process import ensure_runtime, get_runtime_url, runtime_health, wait_for_runtime
from storage.file_store import ensure_webfa_data_dir


def main_runtime(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="webfa-runtime", description="Start the WebFA local runtime.")
    parser.add_argument("command", nargs="?", default="start", choices=["start", "status"])
    parser.add_argument("--host", default=os.getenv("WEBFA_API_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("WEBFA_API_PORT", "8787")))
    args = parser.parse_args(argv)

    runtime_url = f"http://{args.host}:{args.port}"
    if args.command == "status":
        health = runtime_health(runtime_url)
        if health is None:
            print(json.dumps({"status": "unreachable", "runtime_url": runtime_url}, indent=2))
            return 1
        print(json.dumps(health, indent=2, ensure_ascii=False))
        return 0

    os.environ.setdefault("WEBFA_BROWSER_DRIVER", "managed-chromium")
    import uvicorn

    uvicorn.run("apps.runtime.main:app", host=args.host, port=args.port, log_level="info")
    return 0


def main_mcp(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="webfa-mcp", description="Run the WebFA MCP stdio server.")
    parser.add_argument("--runtime-url", default=None)
    parser.add_argument("--no-auto-start", action="store_true")
    args = parser.parse_args(argv)

    runtime_url = get_runtime_url(args.runtime_url)
    os.environ["WEBFA_RUNTIME_URL"] = runtime_url
    runtime_process = ensure_runtime(runtime_url, auto_start=not args.no_auto_start)
    try:
        from apps.runtime.mcp.server import main

        main()
        return 0
    finally:
        if runtime_process.process is not None and runtime_process.process.poll() is None:
            runtime_process.process.terminate()
            try:
                runtime_process.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                runtime_process.process.kill()


def main_webfa(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="webfa", description="WebFA local agent runtime helper.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status", help="Print Runtime health.")
    status_parser.add_argument("--runtime-url", default=None)

    config_parser = subparsers.add_parser("mcp-config", help="Print MCP client config JSON.")
    config_parser.add_argument("--runtime-url", default=None)
    config_parser.add_argument("--source-mode", action="store_true", help="Use python -m apps.runtime.mcp.server style config.")
    config_parser.add_argument("--cwd", default=None)

    subparsers.add_parser("paths", help="Print WebFA local data paths.")

    doctor_parser = subparsers.add_parser("doctor", help="Run a local WebFA smoke test.")
    doctor_parser.add_argument("--runtime-url", default=None)
    doctor_parser.add_argument("--no-auto-start", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "status":
        return _cmd_status(args.runtime_url)
    if args.command == "mcp-config":
        config = generate_config(runtime_url=args.runtime_url, installed=not args.source_mode, cwd=args.cwd)
        print(json.dumps(config, indent=2, ensure_ascii=False))
        return 0
    if args.command == "paths":
        paths = ensure_webfa_data_dir()
        print(json.dumps({key: str(value) for key, value in paths.items()}, indent=2, ensure_ascii=False))
        return 0
    if args.command == "doctor":
        return _cmd_doctor(args.runtime_url, auto_start=not args.no_auto_start)
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
    temp_home = tempfile.TemporaryDirectory(ignore_cleanup_errors=True) if original_home is None else None
    if temp_home is not None:
        os.environ["WEBFA_HOME"] = str(Path(temp_home.name) / "WebFA")
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
        if runtime_process is not None and runtime_process.process is not None and runtime_process.process.poll() is None:
            runtime_process.process.terminate()
            try:
                runtime_process.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                runtime_process.process.kill()
        if original_home is None:
            os.environ.pop("WEBFA_HOME", None)
        else:
            os.environ["WEBFA_HOME"] = original_home
        if temp_home is not None:
            temp_home.cleanup()


def _record(checks: list[dict[str, Any]], name: str, ok: bool, detail: str) -> None:
    checks.append({"name": name, "ok": ok, "detail": detail})


def _mcp_tools_are_default(runtime_url: str) -> bool:
    import httpx

    response = httpx.get(f"{runtime_url}/v1/mcp/status", timeout=5)
    response.raise_for_status()
    tools = response.json().get("tools")
    return tools == ["webfa.open_url", "webfa.observe", "webfa.act", "webfa.get_tabs", "webfa.switch_tab"]


def _run_browser_loop(runtime_url: str) -> bool:
    import httpx

    html = """
    <!doctype html>
    <title>WebFA Doctor</title>
    <form>
      <label>Your name <input name="name" placeholder="Your name"></label>
      <button type="button" onclick="result.textContent = 'Hello ' + document.querySelector('[name=name]').value">Submit</button>
    </form>
    <div id="result"></div>
    """
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "doctor.html"
        page.write_text(html, encoding="utf-8")
        with httpx.Client(timeout=20) as client:
            opened = client.post(f"{runtime_url}/v1/browser/open", json={"url": page.as_uri()})
            opened.raise_for_status()
            state = opened.json()["state"]
            form_id = state["forms"][0]["id"]
            filled = client.post(
                f"{runtime_url}/v1/browser/act",
                json={"action": "fill_form", "target": form_id, "fields": {"name": "WebFA"}},
            )
            filled.raise_for_status()
            submitted = client.post(f"{runtime_url}/v1/browser/act", json={"action": "submit_form", "target": form_id})
            submitted.raise_for_status()
            final_state = submitted.json()["state"]
    body = str(final_state).lower()
    forbidden = ("cookie", "localstorage", "sessionstorage", "token", "full_html", "full_dom")
    return "Hello WebFA" in final_state["visible_text"] and all(term not in body for term in forbidden)


if __name__ == "__main__":
    raise SystemExit(main_webfa())
