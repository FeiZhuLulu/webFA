from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any

from schemas.browser import BrowserTab
from storage.file_store import ensure_webfa_data_dir


class ManagedChromiumHost:
    """WebFA-managed Chromium host controlled through an internal CDP channel."""

    def __init__(self, headless: bool = True) -> None:
        self._headless = headless
        self._process: subprocess.Popen | None = None
        self._port: int | None = None
        self._page_target_id: str | None = None
        self._page_client: _CDPClient | None = None
        self._last_error: str | None = None
        self._executable: Path | None = None
        self._profile_dir: Path | None = None

    def navigate(self, url: str) -> None:
        client = self._ensure_page_client()
        client.call("Page.enable")
        client.call("Runtime.enable")
        client.call("Page.navigate", {"url": url})
        self._wait_for_document_ready()

    def evaluate(self, expression: str) -> object:
        client = self._ensure_page_client()
        response = client.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
        )
        result = response.get("result", {})
        if "exceptionDetails" in response:
            details = response["exceptionDetails"]
            exception = details.get("exception", {})
            text = exception.get("description") or exception.get("value") or details.get("text", "evaluation failed")
            raise RuntimeError(text)
        if "value" in result:
            return result["value"]
        return None

    def tabs(self) -> list[BrowserTab]:
        if self._port is None or not self._process_is_running():
            return []
        tabs = []
        for index, target in enumerate(self._http_json("/json/list")):
            if target.get("type") != "page":
                continue
            tabs.append(
                BrowserTab(
                    id=f"tab_{index + 1}",
                    url=target.get("url", ""),
                    title=target.get("title", ""),
                    active=target.get("id") == self._page_target_id,
                )
            )
        return tabs

    def close(self) -> None:
        if self._page_client is not None:
            try:
                self._page_client.close()
            except Exception:
                pass
        self._page_client = None
        self._page_target_id = None
        if self._process is not None:
            if self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=5)
        self._process = None
        self._port = None

    def status(self) -> dict[str, Any]:
        executable_found, executable_name = self._executable_status()
        status = "running" if self._process_is_running() else "not_started"
        if self._process is not None and self._process.poll() is not None:
            status = "exited"
        return {
            "host_status": status,
            "headless": self._headless,
            "executable_found": executable_found,
            "executable_name": executable_name,
            "profile_id": "default",
            "last_error": self._last_error,
        }

    def _ensure_page_client(self) -> "_CDPClient":
        self._ensure_started()
        if self._page_client is not None:
            return self._page_client
        target = self._first_page_target()
        self._page_target_id = target["id"]
        self._page_client = _CDPClient(target["webSocketDebuggerUrl"])
        return self._page_client

    def _ensure_started(self) -> None:
        if self._process_is_running():
            return
        if self._process is not None:
            self._reset_dead_process()
        paths = ensure_webfa_data_dir()
        data_dir = Path(paths["data_dir"])
        profile_dir = data_dir / "browser" / "managed-chromium-profile-default"
        profile_dir.mkdir(parents=True, exist_ok=True)
        active_port_file = profile_dir / "DevToolsActivePort"
        if active_port_file.exists():
            try:
                active_port_file.unlink()
            except OSError:
                pass
        executable = _find_chromium_executable()
        self._executable = executable
        self._profile_dir = profile_dir
        args = [
            str(executable),
            "about:blank",
            f"--user-data-dir={profile_dir}",
            "--remote-debugging-port=0",
            "--remote-allow-origins=*",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-sync",
            "--disable-gpu",
        ]
        if self._headless:
            args.append("--headless=new")
        try:
            self._process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._port = self._read_devtools_port(profile_dir)
            self._last_error = None
        except Exception as exc:
            self._last_error = str(exc)
            self.close()
            raise

    def _read_devtools_port(self, profile_dir: Path) -> int:
        active_port_file = profile_dir / "DevToolsActivePort"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self._process is not None and self._process.poll() is not None:
                code = self._process.returncode
                raise RuntimeError(f"managed chromium exited before DevTools became available (exit code {code})")
            if active_port_file.exists():
                try:
                    lines = active_port_file.read_text(encoding="utf-8").splitlines()
                    if lines:
                        return int(lines[0])
                except (OSError, ValueError):
                    pass
            time.sleep(0.05)
        raise RuntimeError("managed chromium DevTools port was not created")

    def _first_page_target(self) -> dict[str, Any]:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            pages = [target for target in self._http_json("/json/list") if target.get("type") == "page"]
            if pages:
                return pages[0]
            time.sleep(0.05)
        raise RuntimeError("managed chromium page target was not created")

    def _wait_for_document_ready(self) -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                ready = self.evaluate("document.readyState")
                if ready in ("interactive", "complete"):
                    return
            except Exception:
                pass
            time.sleep(0.05)
        raise RuntimeError("page did not reach an observable ready state")

    def _http_json(self, path: str) -> Any:
        if self._port is None or not self._process_is_running():
            raise RuntimeError("managed chromium is not started")
        with urllib.request.urlopen(f"http://127.0.0.1:{self._port}{path}", timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def _process_is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _reset_dead_process(self) -> None:
        if self._page_client is not None:
            try:
                self._page_client.close()
            except Exception:
                pass
        code = self._process.returncode if self._process is not None else None
        self._last_error = f"managed chromium process exited (exit code {code})"
        self._page_client = None
        self._page_target_id = None
        self._process = None
        self._port = None

    def _executable_status(self) -> tuple[bool, str | None]:
        if self._executable is not None and self._executable.exists():
            return True, self._executable.name
        return chromium_executable_status()


class _CDPClient:
    def __init__(self, websocket_url: str) -> None:
        from websockets.sync.client import connect

        self._next_id = 1
        self._ws = connect(websocket_url, open_timeout=5)

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        message_id = self._next_id
        self._next_id += 1
        self._ws.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            raw = self._ws.recv(timeout=max(0.1, deadline - time.monotonic()))
            message = json.loads(raw)
            if message.get("id") != message_id:
                continue
            if "error" in message:
                raise RuntimeError(message["error"].get("message", "CDP call failed"))
            return message.get("result", {})
        raise RuntimeError(f"CDP call timed out: {method}")

    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:
            pass


def _find_chromium_executable() -> Path:
    explicit = os.getenv("WEBFA_CHROMIUM_EXECUTABLE")
    if explicit:
        path = Path(explicit)
        if path.exists():
            return path
        raise RuntimeError("WEBFA_CHROMIUM_EXECUTABLE does not exist")

    candidates: list[Path] = []
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        candidates.extend(sorted(Path(local_app_data).glob("ms-playwright/chromium-*/chrome-win/chrome.exe"), reverse=True))
    for command in ("chrome", "chrome.exe", "chromium", "chromium.exe", "msedge", "msedge.exe"):
        found = shutil.which(command)
        if found:
            candidates.append(Path(found))
    candidates.extend(
        Path(path)
        for path in (
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        )
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise RuntimeError("Chromium executable not found; set WEBFA_CHROMIUM_EXECUTABLE")


def chromium_executable_status() -> tuple[bool, str | None]:
    try:
        executable = _find_chromium_executable()
        return True, executable.name
    except RuntimeError:
        return False, None
