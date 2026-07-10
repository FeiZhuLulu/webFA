from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from browser.exceptions import BrowserHostClosedError
from schemas.browser import BrowserTab
from storage.file_store import ensure_webfa_data_dir


@dataclass
class PendingJavaScriptDialog:
    dialog_type: str
    message: str
    default_value: str = ""


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
        self._pending_dialog: PendingJavaScriptDialog | None = None
        self._handling_dialog: bool = False

    def navigate(self, url: str) -> None:
        client = self._ensure_page_client()
        self._ensure_page_domains(client)
        self._pending_dialog = None
        client.call("Page.navigate", {"url": url})
        self._wait_for_document_ready()

    def get_pending_dialog(self) -> PendingJavaScriptDialog | None:
        self._ensure_page_client()
        return self._pending_dialog

    def accept_javascript_dialog(self, prompt_text: str | None = None) -> None:
        params: dict[str, Any] = {"accept": True}
        if prompt_text is not None:
            params["promptText"] = prompt_text
        self._handle_javascript_dialog(params)
        self._pending_dialog = None

    def dismiss_javascript_dialog(self) -> None:
        self._handle_javascript_dialog({"accept": False})
        self._pending_dialog = None

    def _handle_javascript_dialog(self, params: dict[str, Any]) -> None:
        self._handling_dialog = True
        try:
            if self._page_client is not None:
                try:
                    self._page_client.call("Page.handleJavaScriptDialog", params)
                    return
                except RuntimeError:
                    pass
            client = self._dialog_client()
            try:
                client.call("Page.enable")
                client.call("Page.handleJavaScriptDialog", params)
            finally:
                client.close()
        finally:
            self._handling_dialog = False

    def _dialog_client(self) -> "_CDPClient":
        target = self._first_page_target()
        return _CDPClient(target["webSocketDebuggerUrl"])

    def get_frame_tree(self) -> list[dict[str, Any]]:
        client = self._ensure_page_client()
        self._ensure_page_domains(client)
        result = client.call("Page.getFrameTree")
        return _flatten_frame_tree(result.get("frameTree", {}))

    def capture_accessibility_tree(self) -> dict[str, Any]:
        client = self._ensure_page_client()
        client.call("Accessibility.enable")
        return client.call("Accessibility.getFullAXTree")

    def capture_dom_snapshot(self) -> dict[str, Any]:
        client = self._ensure_page_client()
        client.call("DOMSnapshot.enable")
        return client.call(
            "DOMSnapshot.captureSnapshot",
            {
                "computedStyles": [],
                "includePaintOrder": True,
                "includeDOMRects": True,
                "includeBlendedBackgroundColors": False,
                "includeTextColorOpacities": False,
            },
        )

    def _on_javascript_dialog_opening(self, params: dict[str, Any]) -> None:
        dialog_type = str(params.get("type", "alert")).lower()
        if dialog_type == "beforeunload":
            dialog_type = "confirm"
        self._pending_dialog = PendingJavaScriptDialog(
            dialog_type=dialog_type,
            message=str(params.get("message", "")),
            default_value=str(params.get("defaultPrompt") or ""),
        )

    def _ensure_page_domains(self, client: "_CDPClient") -> None:
        client.call("Page.enable")
        client.call("Runtime.enable")

    def wait_for_pending_dialog(self, timeout_s: float = 1.0) -> PendingJavaScriptDialog | None:
        if self._pending_dialog is not None:
            return self._pending_dialog
        client = self._page_client
        if client is None:
            return None
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self._pending_dialog is not None:
                return self._pending_dialog
            client.pump_events(min(0.1, deadline - time.monotonic()))
        return self._pending_dialog

    def evaluate(self, expression: str) -> object:
        from browser.runtime_errors import dialog_required

        client = self._ensure_page_client()
        try:
            response = client.call(
                "Runtime.evaluate",
                {
                    "expression": expression,
                    "returnByValue": True,
                    "awaitPromise": True,
                },
            )
        except (RuntimeError, TimeoutError, OSError) as exc:
            if self._pending_dialog is not None:
                raise dialog_required() from exc
            if _is_timeout_error(exc) and self._probe_for_blocking_dialog():
                raise dialog_required() from exc
            raise
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
        self._pending_dialog = None
        self._handling_dialog = False
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

    def relaunch_visible(self, url: str) -> None:
        self.close()
        self._headless = False
        self.navigate(url)

    def capture_screenshot(self) -> str | None:
        if not self._process_is_running():
            return None
        client = self._ensure_page_client()
        client.call("Page.enable")
        result = client.call("Page.captureScreenshot", {"format": "png", "fromSurface": True})
        data = result.get("data")
        return data if isinstance(data, str) and data else None

    def status(self) -> dict[str, Any]:
        executable_found, executable_name = self._executable_status()
        status = "running" if self._process_is_running() else "not_started"
        if self._process is not None and self._process.poll() is not None:
            status = "exited"
        return {
            "host_status": status,
            "headless": self._headless,
            "visible_window": status == "running" and not self._headless,
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
        self._page_client = _CDPClient(
            target["webSocketDebuggerUrl"],
            event_handler=self._handle_cdp_event,
            should_abort=self._dialog_blocks_execution,
        )
        self._ensure_page_domains(self._page_client)
        return self._page_client

    def _handle_cdp_event(self, method: str, params: dict[str, Any]) -> None:
        if method == "Page.javascriptDialogOpening":
            self._on_javascript_dialog_opening(params)

    def _dialog_blocks_execution(self) -> bool:
        if self._handling_dialog:
            return False
        return self._pending_dialog is not None

    def _probe_for_blocking_dialog(self, timeout_s: float = 0.5) -> bool:
        if self._pending_dialog is not None:
            return True
        client = self._page_client
        if client is None:
            return False
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            client.pump_events(min(0.1, deadline - time.monotonic()))
            if self._pending_dialog is not None:
                return True
        return False

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
            "--remote-allow-origins=*",  # dev-preview: tighten before public release
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
        ready_expression = """
        (() => {
          const state = document.readyState;
          if (state !== 'interactive' && state !== 'complete') return false;
          const interactiveSelector = 'input, textarea, select, button, a, [role="button"], [role="link"]';
          for (const iframe of Array.from(document.querySelectorAll('iframe'))) {
            if (!iframe.hasAttribute('srcdoc') && !iframe.getAttribute('src')) continue;
            try {
              const doc = iframe.contentDocument;
              if (!doc || !doc.body) return false;
              if (iframe.hasAttribute('srcdoc') && !doc.querySelector(interactiveSelector)) {
                return false;
              }
            } catch (err) {
              return false;
            }
          }
          return true;
        })()
        """
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                if self.evaluate(ready_expression):
                    return
            except Exception:
                pass
            time.sleep(0.05)
        raise RuntimeError("page did not reach an observable ready state")

    def _http_json(self, path: str) -> Any:
        if self._port is None or not self._process_is_running():
            raise BrowserHostClosedError("managed chromium host is not running")
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
        self._pending_dialog = None
        self._handling_dialog = False
        self._process = None
        self._port = None

    def _executable_status(self) -> tuple[bool, str | None]:
        if self._executable is not None and self._executable.exists():
            return True, self._executable.name
        return chromium_executable_status()


class _CDPClient:
    def __init__(
        self,
        websocket_url: str,
        *,
        event_handler: Callable[[str, dict[str, Any]], None] | None = None,
        should_abort: Callable[[], bool] | None = None,
    ) -> None:
        self._websocket_url = websocket_url
        self._next_id = 1
        self._ws = None
        self._event_handler = event_handler
        self._should_abort = should_abort
        self._connect()

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                return self._call_once(method, params)
            except Exception as exc:
                last_error = exc
                self.close()
                if attempt == 0:
                    self._connect()
                    continue
                raise
        raise last_error or RuntimeError(f"CDP call failed: {method}")

    def close(self) -> None:
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
        self._ws = None

    def pump_events(self, timeout: float) -> None:
        if self._ws is None:
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                raw = self._ws.recv(timeout=max(0.01, deadline - time.monotonic()))
            except TimeoutError:
                return
            except Exception:
                return
            message = json.loads(raw)
            if "method" not in message or message.get("id") is not None:
                continue
            if self._event_handler is not None:
                params = message.get("params")
                if isinstance(params, dict):
                    self._event_handler(str(message["method"]), params)

    def _connect(self) -> None:
        from websockets.sync.client import connect

        self._ws = connect(self._websocket_url, open_timeout=5, ping_interval=None)

    def _call_once(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._ws is None:
            self._connect()
        message_id = self._next_id
        self._next_id += 1
        self._ws.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            raw = self._ws.recv(timeout=max(0.1, deadline - time.monotonic()))
            message = json.loads(raw)
            if "method" in message and message.get("id") is None:
                if self._event_handler is not None:
                    params = message.get("params")
                    if isinstance(params, dict):
                        self._event_handler(str(message["method"]), params)
                if self._should_abort is not None and self._should_abort():
                    raise RuntimeError("javascript dialog blocked execution")
                continue
            if message.get("id") != message_id:
                continue
            if "error" in message:
                raise RuntimeError(message["error"].get("message", "CDP call failed"))
            return message.get("result", {})
        raise RuntimeError(f"CDP call timed out: {method}")


def _is_timeout_error(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    message = str(exc).lower()
    return "timed out" in message or "timeout" in message


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


def _flatten_frame_tree(node: dict[str, Any], *, parent_id: str | None = None, items: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    collected = items if items is not None else []
    frame = node.get("frame", {})
    frame_id = str(frame.get("id", ""))
    if frame_id:
        collected.append(
            {
                "cdp_frame_id": frame_id,
                "parent_cdp_frame_id": parent_id,
                "url": str(frame.get("url", "")),
                "name": str(frame.get("name", "")),
                "security_origin": str(frame.get("securityOrigin", "")),
                "mime_type": str(frame.get("mimeType", "")),
                "unreachable_url": str(frame.get("unreachableUrl", "")),
            }
        )
    for child in node.get("childFrames", []):
        _flatten_frame_tree(child, parent_id=frame_id or parent_id, items=collected)
    return collected


def chromium_executable_status() -> tuple[bool, str | None]:
    try:
        executable = _find_chromium_executable()
        return True, executable.name
    except RuntimeError:
        return False, None
