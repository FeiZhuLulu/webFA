from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import threading
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlparse
from uuid import uuid4

from browser.exceptions import BrowserHostClosedError
from browser.human_control import HumanInputEvent
from browser.profile_storage import ProfileLaunchSpec, ProfileStorageManager
from browser.visual_surface import HostVisualFrame, HostVisualStreamState, VisualStreamConfig
from schemas.browser import BrowserTab


_CDP_CLIENT_ORIGIN = "https://runtime.webfa.invalid"


@dataclass
class PendingJavaScriptDialog:
    dialog_type: str
    message: str
    default_value: str = ""


@dataclass
class _ScreencastRuntimeState:
    backend_stream_id: str
    lifecycle: str = "starting"
    visible: bool = True
    frames_received: int = 0
    frames_dropped: int = 0
    last_error: str | None = None

    def snapshot(self) -> HostVisualStreamState:
        return HostVisualStreamState(
            backend_stream_id=self.backend_stream_id,
            lifecycle=self.lifecycle,  # type: ignore[arg-type]
            visible=self.visible,
            frames_received=self.frames_received,
            frames_dropped=self.frames_dropped,
            last_error=self.last_error,
        )


class ManagedChromiumHost:
    """WebFA-managed Chromium host controlled through an internal CDP channel."""

    def __init__(
        self,
        headless: bool = True,
        launch_spec: ProfileLaunchSpec | None = None,
    ) -> None:
        self._launch_spec = launch_spec
        self._headless = launch_spec.headless if launch_spec is not None else headless
        self._process: subprocess.Popen | None = None
        self._port: int | None = None
        self._page_target_id: str | None = None
        self._page_client: _CDPClient | None = None
        self._last_error: str | None = None
        self._executable: Path | None = None
        self._profile_dir: Path | None = None
        self._pending_dialog: PendingJavaScriptDialog | None = None
        self._handling_dialog: bool = False
        self._screencast_lock = threading.RLock()
        self._screencast_thread: threading.Thread | None = None
        self._screencast_stop: threading.Event | None = None
        self._screencast_started: threading.Event | None = None
        self._screencast_state: _ScreencastRuntimeState | None = None

    def navigate(self, url: str) -> None:
        client = self._ensure_page_client()
        self._ensure_page_domains(client)
        self._pending_dialog = None
        client.call("Page.navigate", {"url": url})
        self._wait_for_document_ready()

    def import_cookies(self, cookies: list[dict[str, Any]]) -> int:
        """Set cookies through the browser-level Storage domain.

        Raw Cookie values remain inside the protected maintenance process. The
        only returned value is the number of imported entries verified against
        browser storage after the protocol call succeeds.
        """

        if not cookies:
            return 0
        self._browser_protocol_call("Storage.setCookies", {"cookies": cookies})
        response = self._browser_protocol_call("Storage.getCookies")
        stored = response.get("cookies", []) if isinstance(response, dict) else []
        expected = {_cookie_verification_key(cookie) for cookie in cookies}
        actual = {
            _cookie_verification_key(cookie)
            for cookie in stored
            if isinstance(cookie, dict)
        }
        return len(expected & actual)

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

    def set_file_input_files(
        self,
        element_id: str,
        file_paths: list[str],
        *,
        frame_id: str | None = None,
    ) -> None:
        if not file_paths:
            raise RuntimeError("protected file upload requires at least one file")
        resolved_files = []
        for value in file_paths:
            path = Path(value).expanduser().resolve()
            if not path.is_file():
                raise RuntimeError("protected upload resource is unavailable")
            resolved_files.append(str(path))

        client = self._ensure_page_client()
        client.call("DOM.enable")
        expression = _file_input_expression(element_id, frame_id)
        response = client.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": False,
                "awaitPromise": True,
                "objectGroup": "webfa-protected-upload",
            },
        )
        if "exceptionDetails" in response:
            raise RuntimeError("protected file input could not be resolved")
        remote = response.get("result", {})
        object_id = remote.get("objectId")
        if not isinstance(object_id, str) or not object_id:
            raise RuntimeError("protected file input could not be resolved")
        try:
            client.call(
                "DOM.setFileInputFiles",
                {"files": resolved_files, "objectId": object_id},
            )
            client.call(
                "Runtime.callFunctionOn",
                {
                    "objectId": object_id,
                    "functionDeclaration": (
                        "function(){"
                        "this.dispatchEvent(new Event('input',{bubbles:true}));"
                        "this.dispatchEvent(new Event('change',{bubbles:true}));"
                        "return true;"
                        "}"
                    ),
                    "returnByValue": True,
                },
            )
        finally:
            try:
                client.call("Runtime.releaseObject", {"objectId": object_id})
            except Exception:
                pass

    def dispatch_human_input(self, event: HumanInputEvent) -> None:
        client = self._ensure_page_client()
        modifiers = _human_modifier_mask(event.modifiers)
        if event.type == "insert_text":
            client.call("Input.insertText", {"text": event.text or ""})
            return
        if event.type in {"key_down", "key_up"}:
            params: dict[str, Any] = {
                "type": "keyDown" if event.type == "key_down" else "keyUp",
                "key": event.key or "",
                "code": event.code or "",
                "modifiers": modifiers,
                "autoRepeat": event.auto_repeat,
            }
            virtual_key_code = _human_virtual_key_code(event.key, event.code)
            if virtual_key_code is not None:
                params["windowsVirtualKeyCode"] = virtual_key_code
                params["nativeVirtualKeyCode"] = virtual_key_code
            if event.type == "key_down" and event.text:
                params["text"] = event.text
                params["unmodifiedText"] = event.text
            elif event.type == "key_down" and (event.key == "Enter" or event.code in {"Enter", "NumpadEnter"}):
                params["text"] = "\r"
                params["unmodifiedText"] = "\r"
            client.call("Input.dispatchKeyEvent", params)
            return
        if event.x is None or event.y is None:
            raise ValueError("human mouse input requires coordinates")
        if event.type == "wheel":
            client.call(
                "Input.dispatchMouseEvent",
                {
                    "type": "mouseWheel",
                    "x": event.x,
                    "y": event.y,
                    "deltaX": event.delta_x,
                    "deltaY": event.delta_y,
                    "modifiers": modifiers,
                    "buttons": event.buttons,
                },
            )
            return
        event_type = {
            "mouse_move": "mouseMoved",
            "mouse_down": "mousePressed",
            "mouse_up": "mouseReleased",
        }[event.type]
        client.call(
            "Input.dispatchMouseEvent",
            {
                "type": event_type,
                "x": event.x,
                "y": event.y,
                "button": event.button,
                "buttons": event.buttons,
                "clickCount": event.click_count,
                "modifiers": modifiers,
            },
        )

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
        with self._screencast_lock:
            active_stream_id = (
                self._screencast_state.backend_stream_id
                if self._screencast_state is not None
                and self._screencast_state.lifecycle in {"starting", "running"}
                else None
            )
        if active_stream_id is not None:
            try:
                self.stop_screencast(active_stream_id)
            except Exception:
                pass
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
                self._request_graceful_browser_close()
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.terminate()
                    try:
                        self._process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self._process.kill()
                        self._process.wait(timeout=5)
        self._process = None
        self._port = None

    def _browser_protocol_call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._ensure_started()
        version = self._http_json("/json/version")
        websocket_url = version.get("webSocketDebuggerUrl") if isinstance(version, dict) else None
        if not websocket_url:
            raise RuntimeError("managed chromium browser endpoint is unavailable")
        client = _CDPClient(websocket_url)
        try:
            return client.call(method, params)
        finally:
            client.close()

    def _request_graceful_browser_close(self) -> None:
        if self._port is None or not self._process_is_running():
            return
        client: _CDPClient | None = None
        try:
            version = self._http_json("/json/version")
            websocket_url = version.get("webSocketDebuggerUrl") if isinstance(version, dict) else None
            if not websocket_url:
                return
            client = _CDPClient(websocket_url)
            try:
                client.call("Browser.close")
            except (RuntimeError, TimeoutError, OSError):
                # Chromium may close the transport before acknowledging Browser.close.
                pass
        except Exception:
            pass
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

    def relaunch_visible(self, url: str) -> None:
        self.close()
        self._headless = False
        self.navigate(url)

    def start_screencast(
        self,
        config: VisualStreamConfig,
        frame_sink: Callable[[HostVisualFrame], None],
    ) -> str:
        if not callable(frame_sink):
            raise TypeError("frame_sink must be callable")
        self._ensure_page_client()
        target = self._current_page_target()
        backend_stream_id = f"cdpcast_{uuid4().hex}"
        stop_event = threading.Event()
        started_event = threading.Event()
        state = _ScreencastRuntimeState(backend_stream_id=backend_stream_id)

        with self._screencast_lock:
            if self._screencast_state is not None and self._screencast_state.lifecycle in {"starting", "running"}:
                raise RuntimeError("managed chromium screencast is already running")
            self._screencast_state = state
            self._screencast_stop = stop_event
            self._screencast_started = started_event
            self._screencast_thread = threading.Thread(
                target=self._run_screencast,
                args=(
                    target["webSocketDebuggerUrl"],
                    str(target.get("id") or self._page_target_id or ""),
                    config,
                    frame_sink,
                    stop_event,
                    started_event,
                    state,
                ),
                name=f"webfa-cdp-screencast-{backend_stream_id[-8:]}",
                daemon=True,
            )
            self._screencast_thread.start()

        if not started_event.wait(timeout=5):
            stop_event.set()
            thread = self._screencast_thread
            if thread is not None:
                thread.join(timeout=2)
            with self._screencast_lock:
                state.lifecycle = "failed"
                state.last_error = "managed chromium screencast did not start"
            raise RuntimeError("managed chromium screencast did not start")
        with self._screencast_lock:
            current = self._screencast_state
            if current is None or current.backend_stream_id != backend_stream_id:
                raise RuntimeError("managed chromium screencast state was lost")
            if current.lifecycle == "failed":
                raise RuntimeError(current.last_error or "managed chromium screencast failed")
        return backend_stream_id

    def stop_screencast(self, backend_stream_id: str) -> HostVisualStreamState:
        with self._screencast_lock:
            state = self._screencast_state
            thread = self._screencast_thread
            stop_event = self._screencast_stop
            if state is None or state.backend_stream_id != backend_stream_id:
                raise KeyError(f"managed chromium screencast not found: {backend_stream_id}")
            if stop_event is not None:
                stop_event.set()
        if thread is not None and threading.current_thread() is not thread:
            thread.join(timeout=5)
        with self._screencast_lock:
            state = self._screencast_state
            if state is None:
                raise RuntimeError("managed chromium screencast state was lost")
            if thread is not None and thread.is_alive():
                state.lifecycle = "failed"
                state.last_error = "managed chromium screencast thread did not stop"
            elif state.lifecycle in {"starting", "running"}:
                state.lifecycle = "stopped"
            return state.snapshot()

    def screencast_status(self, backend_stream_id: str | None = None) -> HostVisualStreamState | None:
        with self._screencast_lock:
            state = self._screencast_state
            if state is None:
                return None
            if backend_stream_id is not None and state.backend_stream_id != backend_stream_id:
                return None
            return state.snapshot()

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
        screencast = self.screencast_status()
        return {
            "host_status": status,
            "headless": self._headless,
            "visible_window": status == "running" and not self._headless,
            "executable_found": executable_found,
            "executable_name": executable_name,
            "profile_id": "default",
            "last_error": self._last_error,
            "visual_stream_status": screencast.lifecycle if screencast is not None else "stopped",
            "visual_frames_received": screencast.frames_received if screencast is not None else 0,
        }

    def _run_screencast(
        self,
        websocket_url: str,
        target_id: str,
        config: VisualStreamConfig,
        frame_sink: Callable[[HostVisualFrame], None],
        stop_event: threading.Event,
        started_event: threading.Event,
        state: _ScreencastRuntimeState,
    ) -> None:
        client: _CDPClient | None = None
        if config.format == "webp":
            with self._screencast_lock:
                state.lifecycle = "failed"
                state.last_error = "CDP Page.startScreencast supports jpeg or png, not webp"
            started_event.set()
            return

        def handle_event(method: str, params: dict[str, Any]) -> None:
            if method == "Page.screencastVisibilityChanged":
                with self._screencast_lock:
                    state.visible = bool(params.get("visible", True))
                return
            if method != "Page.screencastFrame":
                return
            session_id = params.get("sessionId")
            try:
                encoded = params.get("data")
                metadata = params.get("metadata") or {}
                if not isinstance(encoded, str) or not encoded:
                    raise ValueError("screencast frame did not contain image data")
                frame = HostVisualFrame(
                    data=base64.b64decode(encoded, validate=True),
                    format=config.format,
                    width=max(1, int(metadata.get("deviceWidth") or config.max_width)),
                    height=max(1, int(metadata.get("deviceHeight") or config.max_height)),
                    device_scale_factor=float(metadata.get("pageScaleFactor") or 1.0),
                    scroll_offset_x=float(metadata.get("scrollOffsetX") or 0.0),
                    scroll_offset_y=float(metadata.get("scrollOffsetY") or 0.0),
                    captured_at=datetime_from_cdp_timestamp(metadata.get("timestamp")),
                    host_target_id=target_id or None,
                    host_frame_id=None,
                )
                with self._screencast_lock:
                    state.frames_received += 1
                try:
                    frame_sink(frame)
                except Exception:
                    with self._screencast_lock:
                        state.frames_dropped += 1
            except Exception as exc:
                with self._screencast_lock:
                    state.frames_dropped += 1
                    state.last_error = str(exc)
            finally:
                if client is not None and isinstance(session_id, int):
                    try:
                        client.send("Page.screencastFrameAck", {"sessionId": session_id})
                    except Exception:
                        pass

        try:
            client = _CDPClient(websocket_url, event_handler=handle_event)
            client.call("Page.enable")
            client.call(
                "Page.startScreencast",
                {
                    "format": config.format,
                    "quality": config.quality,
                    "maxWidth": config.max_width,
                    "maxHeight": config.max_height,
                    "everyNthFrame": config.every_nth_frame,
                },
            )
            with self._screencast_lock:
                state.lifecycle = "running"
                state.last_error = None
            started_event.set()
            while not stop_event.is_set():
                if not client.pump_events(0.1):
                    raise RuntimeError("managed chromium screencast connection closed")
        except Exception as exc:
            with self._screencast_lock:
                state.lifecycle = "failed"
                state.last_error = str(exc)
            started_event.set()
        finally:
            if client is not None:
                try:
                    client.call("Page.stopScreencast")
                except Exception:
                    pass
                client.close()
            with self._screencast_lock:
                if state.lifecycle != "failed":
                    state.lifecycle = "stopped"
            started_event.set()

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
        if self._launch_spec is not None:
            profile_dir = self._launch_spec.user_data_dir
            profile_dir.mkdir(parents=True, exist_ok=True)
        else:
            storage = ProfileStorageManager()
            storage.migrate_legacy_default_profile()
            profile_dir = storage.paths_for("default").user_data_dir
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
            "--profile-directory=Default",
            "--remote-debugging-port=0",
            f"--remote-allow-origins={_CDP_CLIENT_ORIGIN}",
            "--disable-extensions",
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

    def _current_page_target(self) -> dict[str, Any]:
        pages = [target for target in self._http_json("/json/list") if target.get("type") == "page"]
        if self._page_target_id is not None:
            for target in pages:
                if target.get("id") == self._page_target_id:
                    return target
        if pages:
            return pages[0]
        raise RuntimeError("managed chromium page target was not created")

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

    def send(self, method: str, params: dict[str, Any] | None = None) -> int:
        if self._ws is None:
            self._connect()
        message_id = self._next_id
        self._next_id += 1
        self._ws.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        return message_id

    def close(self) -> None:
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
        self._ws = None

    def pump_events(self, timeout: float) -> bool:
        if self._ws is None:
            return False
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                raw = self._ws.recv(timeout=max(0.01, deadline - time.monotonic()))
            except TimeoutError:
                return True
            except Exception:
                return False
            message = json.loads(raw)
            if "method" not in message or message.get("id") is not None:
                continue
            if self._event_handler is not None:
                params = message.get("params")
                if isinstance(params, dict):
                    self._event_handler(str(message["method"]), params)
        return True

    def _connect(self) -> None:
        from websockets.sync.client import connect

        self._ws = connect(
            self._websocket_url,
            origin=_CDP_CLIENT_ORIGIN,
            open_timeout=5,
            ping_interval=None,
        )

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


def _human_virtual_key_code(key: str | None, code: str | None) -> int | None:
    normalized = key or code or ""
    special = {
        "Backspace": 8,
        "Tab": 9,
        "Enter": 13,
        "NumpadEnter": 13,
        "Escape": 27,
        " ": 32,
        "Space": 32,
        "PageUp": 33,
        "PageDown": 34,
        "End": 35,
        "Home": 36,
        "ArrowLeft": 37,
        "ArrowUp": 38,
        "ArrowRight": 39,
        "ArrowDown": 40,
        "Delete": 46,
    }
    if normalized in special:
        return special[normalized]
    if len(normalized) == 1:
        return ord(normalized.upper())
    return None


def _human_modifier_mask(modifiers: tuple[str, ...]) -> int:
    mask = 0
    for modifier in modifiers:
        if modifier == "alt":
            mask |= 1
        elif modifier == "control":
            mask |= 2
        elif modifier == "meta":
            mask |= 4
        elif modifier == "shift":
            mask |= 8
    return mask


def datetime_from_cdp_timestamp(value: object) -> datetime:
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)
    if timestamp <= 0:
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def _file_input_expression(element_id: str, frame_id: str | None) -> str:
    return f"""
    (() => {{
      const frameId = {json.dumps(frame_id)};
      const resolveRoot = () => {{
        if (!frameId || frameId === 'frame_1') return document;
        const iframe = Array.from(document.querySelectorAll('iframe[data-webfa-frame-id]'))
          .find((node) => node.getAttribute('data-webfa-frame-id') === frameId);
        if (!iframe) throw new Error('frame not found');
        try {{
          const doc = iframe.contentDocument;
          if (!doc) throw new Error('cross-origin frame is not supported');
          return doc;
        }} catch (err) {{
          throw new Error('cross-origin frame is not supported');
        }}
      }};
      const root = resolveRoot();
      const element = root.querySelector(`[data-webfa-id="${{CSS.escape({json.dumps(element_id)})}}"]`);
      if (!element) throw new Error('element id is stale');
      if (!element.tagName || element.tagName.toLowerCase() !== 'input' || String(element.type).toLowerCase() !== 'file') {{
        throw new Error('target is not a file input');
      }}
      return element;
    }})()
    """


def _cookie_verification_key(cookie: dict[str, Any]) -> tuple[object, ...]:
    domain = str(cookie.get("domain") or "").strip().lower()
    if not domain:
        url = str(cookie.get("url") or "")
        domain = (urlparse(url).hostname or "").lower()
    partition = cookie.get("partitionKey")
    if isinstance(partition, dict):
        partition_site = str(partition.get("topLevelSite") or "")
        cross_site = bool(partition.get("hasCrossSiteAncestor", False))
    else:
        partition_site = ""
        cross_site = False
    return (
        str(cookie.get("name") or ""),
        str(cookie.get("value") or ""),
        domain,
        str(cookie.get("path") or "/"),
        partition_site,
        cross_site,
    )


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
    for command in ("chrome", "chrome.exe", "chromium", "chromium.exe", "msedge", "msedge.exe"):
        found = shutil.which(command)
        if found:
            candidates.append(Path(found))
    candidates.extend(_chromium_install_candidates())
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise RuntimeError("Chromium executable not found; set WEBFA_CHROMIUM_EXECUTABLE")


def _chromium_install_candidates(
    *,
    platform_name: str | None = None,
    environment: Mapping[str, str] | None = None,
) -> list[Path]:
    if (platform_name or os.name) != "nt":
        return []
    env = environment if environment is not None else os.environ
    install_roots: list[Path] = []
    for key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432"):
        value = env.get(key)
        if value:
            root = Path(value)
            if root not in install_roots:
                install_roots.append(root)
    local_app_data = env.get("LOCALAPPDATA")
    if local_app_data:
        root = Path(local_app_data)
        if root not in install_roots:
            install_roots.append(root)
    if not install_roots:
        system_drive = env.get("SYSTEMDRIVE")
        if system_drive:
            install_roots.extend(
                [Path(system_drive) / "Program Files", Path(system_drive) / "Program Files (x86)"]
            )
    return [
        candidate
        for root in install_roots
        for candidate in (
            root / "Google" / "Chrome" / "Application" / "chrome.exe",
            root / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        )
    ]


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
                "loader_id": str(frame.get("loaderId", "")),
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
