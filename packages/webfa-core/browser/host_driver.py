from __future__ import annotations

import copy
import json
import time

from browser.driver import ACTION_TIMEOUT_MS, RawPageSnapshot
from browser.host import BrowserHost
from browser.raw_snapshot import RawWebSnapshot
from browser.raw_snapshot_collector import RawSnapshotCollector
from browser.runtime_errors import BrowserRuntimeError, dialog_not_found, dialog_required, frame_unsupported
from schemas.browser import BrowserActionRequest, BrowserTab


class HostBrowserDriver:
    """BrowserDriver implementation backed by a BrowserHost."""

    def __init__(self, host: BrowserHost) -> None:
        self._host = host
        self._snapshot_collector = RawSnapshotCollector(host)
        self._element_frames: dict[str, str | None] = {}
        self._last_web_snapshot: RawWebSnapshot | None = None

    def open(self, url: str) -> None:
        self._last_web_snapshot = None
        self._host.navigate(url)

    def observe_raw(self) -> RawPageSnapshot:
        return self.observe_web_raw().to_page_snapshot()

    def observe_web_raw(self) -> RawWebSnapshot:
        dialogs = _dialogs_from_host(self._host)
        if dialogs and self._last_web_snapshot is not None:
            snapshot = copy.deepcopy(self._last_web_snapshot)
            snapshot.dialogs = dialogs
        else:
            snapshot = self._snapshot_collector.collect(tabs=self.tabs(), dialogs=dialogs)
            self._last_web_snapshot = copy.deepcopy(snapshot)
        self._element_frames = {
            str(item.get("id")): item.get("frame_id")
            for item in snapshot.interactive_elements
            if isinstance(item, dict) and item.get("id")
        }
        return snapshot

    def act(self, request: BrowserActionRequest) -> None:
        action = request.action
        if action == "accept_dialog":
            self._accept_dialog(request.target)
            return
        if action == "dismiss_dialog":
            self._dismiss_dialog(request.target)
            return
        if action == "wait":
            time.sleep((request.ms or 0) / 1000)
            return
        if action == "wait_for_text":
            self._wait_for_text(request.text or "", request.timeout_ms or ACTION_TIMEOUT_MS)
            return
        if action == "press":
            if request.target:
                self._focus(request.target)
            self._press(request.key or "")
            return
        if action == "click":
            self._element_action(request.target, "click")
            return
        if action == "double_click":
            self._element_action(request.target, "double_click")
            return
        if action == "type":
            self._element_action(request.target, "type", request.text or "")
            return
        if action == "clear":
            self._element_action(request.target, "type", "")
            return
        if action == "focus":
            self._focus(request.target)
            return
        if action == "select":
            self._element_action(request.target, "select", request.value or request.text or "")
            return
        raise ValueError(f"{action} is not supported by managed chromium driver")

    def upload_file(self, element_id: str, file_path: str) -> None:
        setter = getattr(self._host, "set_file_input_files", None)
        if not callable(setter):
            raise ValueError("selected BrowserHost does not support protected file upload")
        try:
            setter(
                element_id,
                [file_path],
                frame_id=self._element_frames.get(element_id),
            )
        except BrowserRuntimeError:
            raise
        except RuntimeError as exc:
            message = str(exc)
            if "cross-origin" in message or "frame not found" in message:
                raise frame_unsupported(self._element_frames.get(element_id)) from exc
            raise ValueError("protected file upload failed") from exc

    def has_pending_dialog(self) -> bool:
        getter = getattr(self._host, "get_pending_dialog", None)
        if not callable(getter):
            return False
        return getter() is not None

    def tabs(self) -> list[BrowserTab]:
        return self._host.tabs()

    def switch_tab(self, tab_id: str) -> None:
        raise ValueError("switch_tab is not supported by managed chromium driver yet")

    def close(self) -> None:
        self._host.close()

    def status(self) -> dict:
        if hasattr(self._host, "status"):
            status = self._host.status()
            if isinstance(status, dict):
                return status
        return {"host_status": "running"}

    def relaunch_visible(self, url: str) -> None:
        if not hasattr(self._host, "relaunch_visible"):
            raise RuntimeError("browser host does not support visible relaunch")
        self._host.relaunch_visible(url)

    def capture_screenshot(self) -> str | None:
        capture = getattr(self._host, "capture_screenshot", None)
        if not callable(capture):
            return None
        return capture()

    def visual_surface_backend(self):
        start = getattr(self._host, "start_screencast", None)
        stop = getattr(self._host, "stop_screencast", None)
        status = getattr(self._host, "screencast_status", None)
        if not callable(start) or not callable(stop) or not callable(status):
            return None
        return self._host

    def _accept_dialog(self, dialog_id: str | None) -> None:
        if dialog_id != "dialog_1":
            raise dialog_not_found(dialog_id)
        if not self.has_pending_dialog():
            raise dialog_not_found(dialog_id)
        pending = _current_dialog(self._host)
        if pending is not None and pending["type"] == "prompt":
            raise dialog_not_found(dialog_id)
        accept = getattr(self._host, "accept_javascript_dialog", None)
        if not callable(accept):
            raise frame_unsupported("dialog")
        try:
            accept()
        except RuntimeError as exc:
            if "no dialog" in str(exc).lower():
                raise dialog_not_found(dialog_id) from exc
            raise

    def _dismiss_dialog(self, dialog_id: str | None) -> None:
        if dialog_id != "dialog_1":
            raise dialog_not_found(dialog_id)
        if not self.has_pending_dialog():
            raise dialog_not_found(dialog_id)
        dismiss = getattr(self._host, "dismiss_javascript_dialog", None)
        if not callable(dismiss):
            raise frame_unsupported("dialog")
        try:
            dismiss()
        except RuntimeError as exc:
            if "no dialog" in str(exc).lower():
                raise dialog_not_found(dialog_id) from exc
            raise

    def _focus(self, element_id: str | None) -> None:
        if not element_id:
            raise ValueError("target is required")
        try:
            self._host.evaluate(_element_expression(element_id, "focus", frame_id=self._element_frames.get(element_id)))
        except BrowserRuntimeError:
            raise
        except RuntimeError as exc:
            raise ValueError(str(exc)) from exc

    def _press(self, key: str) -> None:
        self._host.evaluate(
            f"""
            (() => {{
              const target = document.activeElement || document.body;
              const event = new KeyboardEvent('keydown', {{
                key: {json.dumps(key)},
                code: {json.dumps(_key_code(key))},
                bubbles: true,
                cancelable: true
              }});
              target.dispatchEvent(event);
              if ({json.dumps(key)} === 'Enter' && target && target.form) {{
                target.form.requestSubmit ? target.form.requestSubmit() : target.form.submit();
              }}
              return true;
            }})()
            """
        )

    def _element_action(self, element_id: str | None, action: str, text: str | None = None) -> None:
        if not element_id:
            raise ValueError("target is required")
        try:
            self._host.evaluate(
                _element_expression(element_id, action, text, frame_id=self._element_frames.get(element_id))
            )
            if action in {"click", "double_click"}:
                self._raise_if_dialog_opened()
        except BrowserRuntimeError:
            raise
        except RuntimeError as exc:
            message = str(exc)
            if "cross-origin" in message or "frame not found" in message:
                raise frame_unsupported(self._element_frames.get(element_id)) from exc
            raise ValueError(message) from exc

    def _raise_if_dialog_opened(self) -> None:
        waiter = getattr(self._host, "wait_for_pending_dialog", None)
        if callable(waiter) and waiter(1.0) is not None:
            raise dialog_required()

    def _wait_for_text(self, text: str, timeout_ms: int) -> None:
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            found = self._host.evaluate(
                f"((document.body ? document.body.innerText : '').includes({json.dumps(text)}))"
            )
            if found:
                return
            time.sleep(0.05)
        raise RuntimeError("text was not found before timeout")


def _dialogs_from_host(host: BrowserHost) -> list[dict]:
    getter = getattr(host, "get_pending_dialog", None)
    pending = getter() if callable(getter) else None
    if pending is None:
        try:
            marker = host.evaluate(
                "(() => window.__webfaPendingDialog ? JSON.stringify(window.__webfaPendingDialog) : '')()"
            )
            if isinstance(marker, str) and marker:
                import json as _json

                payload = _json.loads(marker)
                pending_type = str(payload.get("type", "alert"))
                return [
                    {
                        "id": "dialog_1",
                        "type": pending_type if pending_type in {"alert", "confirm", "prompt"} else "alert",
                        "message": str(payload.get("message", "")),
                        "default_value": str(payload.get("default_value", "")),
                        "user_action_required": pending_type == "prompt",
                    }
                ]
        except Exception:
            return []
        return []
    dialog_type = pending.dialog_type
    if dialog_type not in {"alert", "confirm", "prompt"}:
        dialog_type = "alert"
    return [
        {
            "id": "dialog_1",
            "type": dialog_type,
            "message": pending.message,
            "default_value": pending.default_value,
            "user_action_required": dialog_type == "prompt",
        }
    ]


def _current_dialog(host: BrowserHost) -> dict | None:
    dialogs = _dialogs_from_host(host)
    return dialogs[0] if dialogs else None


def _element_expression(element_id: str, action: str, text: str | None = None, frame_id: str | None = None) -> str:
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
      const el = root.querySelector(`[data-webfa-id="${{CSS.escape({json.dumps(element_id)})}}"]`);
      if (!el) throw new Error('element id is stale; call observe again');
      if ({json.dumps(action)} === 'focus') {{
        el.focus();
        return true;
      }}
      if ({json.dumps(action)} === 'click') {{
        setTimeout(() => el.click(), 0);
        return true;
      }}
      if ({json.dumps(action)} === 'double_click') {{
        setTimeout(() => {{
          const options = {{ bubbles: true, cancelable: true, view: window, detail: 2 }};
          el.dispatchEvent(new MouseEvent('mousedown', options));
          el.dispatchEvent(new MouseEvent('mouseup', options));
          el.dispatchEvent(new MouseEvent('click', options));
          el.dispatchEvent(new MouseEvent('mousedown', options));
          el.dispatchEvent(new MouseEvent('mouseup', options));
          el.dispatchEvent(new MouseEvent('click', options));
          el.dispatchEvent(new MouseEvent('dblclick', options));
        }}, 0);
        return true;
      }}
      if ({json.dumps(action)} === 'type') {{
        el.focus();
        if ('value' in el) {{
          const value = {json.dumps(text or '')};
          const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
          const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
          if (descriptor && descriptor.set) {{
            descriptor.set.call(el, value);
          }} else {{
            el.value = value;
          }}
          el.dispatchEvent(new InputEvent('beforeinput', {{ bubbles: true, cancelable: true, inputType: 'insertText', data: value }}));
          el.dispatchEvent(new InputEvent('input', {{ bubbles: true, inputType: 'insertText', data: value }}));
          el.dispatchEvent(new Event('change', {{ bubbles: true }}));
        }} else if (el.isContentEditable) {{
          const value = {json.dumps(text or '')};
          el.textContent = value;
          el.dispatchEvent(new InputEvent('beforeinput', {{ bubbles: true, cancelable: true, inputType: 'insertText', data: value }}));
          el.dispatchEvent(new InputEvent('input', {{ bubbles: true, inputType: 'insertText', data: value }}));
        }} else {{
          throw new Error('element does not accept text');
        }}
        return true;
      }}
      if ({json.dumps(action)} === 'select') {{
        if (el.tagName.toLowerCase() !== 'select') throw new Error('element is not a select');
        const wanted = {json.dumps(text or '')};
        let matched = false;
        for (const option of Array.from(el.options)) {{
          if (option.value === wanted || option.textContent.trim() === wanted) {{
            el.value = option.value;
            matched = true;
            break;
          }}
        }}
        if (!matched) throw new Error('option not found');
        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
        return true;
      }}
      throw new Error('unsupported element action');
    }})()
    """


def _key_code(key: str) -> str:
    if len(key) == 1:
        return f"Key{key.upper()}"
    return key