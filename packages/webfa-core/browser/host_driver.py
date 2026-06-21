from __future__ import annotations

import json
import time

from browser.driver import (
    ACTION_TIMEOUT_MS,
    CONTENT_BLOCK_MAX_CHARS,
    CONTENT_BLOCK_MAX_COUNT,
    VISIBLE_TEXT_MAX_CHARS,
    RawPageSnapshot,
)
from browser.host import BrowserHost
from browser.observe_probe import OBSERVE_PROBE
from schemas.browser import BrowserActionRequest, BrowserTab, BrowserViewport


class HostBrowserDriver:
    """BrowserDriver implementation backed by a BrowserHost."""

    def __init__(self, host: BrowserHost) -> None:
        self._host = host

    def open(self, url: str) -> None:
        self._host.navigate(url)

    def observe_raw(self) -> RawPageSnapshot:
        raw = self._host.evaluate(_probe_expression())
        if not isinstance(raw, dict):
            raise RuntimeError("observe probe did not return a raw page snapshot")
        url = str(self._host.evaluate("window.location.href"))
        title = str(self._host.evaluate("document.title"))
        viewport = self._host.evaluate("({ width: window.innerWidth, height: window.innerHeight })")
        if not isinstance(viewport, dict):
            viewport = {"width": 1280, "height": 720}
        return RawPageSnapshot(
            url=url,
            title=title,
            loading=bool(raw.get("loading")),
            focused_element_id=raw.get("focused_element_id"),
            viewport=BrowserViewport(width=int(viewport.get("width", 1280)), height=int(viewport.get("height", 720))),
            tabs=self.tabs(),
            visible_text=raw.get("visible_text", ""),
            content_blocks=raw.get("content_blocks", []),
            forms=raw.get("forms", []),
            interactive_elements=raw.get("interactive_elements", []),
        )

    def act(self, request: BrowserActionRequest) -> None:
        action = request.action
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

    def _focus(self, element_id: str | None) -> None:
        if not element_id:
            raise ValueError("target is required")
        try:
            self._host.evaluate(_element_expression(element_id, "focus"))
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
            self._host.evaluate(_element_expression(element_id, action, text))
        except RuntimeError as exc:
            raise ValueError(str(exc)) from exc

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


def _probe_expression() -> str:
    opts = {
        "maxChars": VISIBLE_TEXT_MAX_CHARS,
        "blockChars": CONTENT_BLOCK_MAX_CHARS,
        "blockCount": CONTENT_BLOCK_MAX_COUNT,
    }
    return f"({OBSERVE_PROBE})({json.dumps(opts)})"


def _element_expression(element_id: str, action: str, text: str | None = None) -> str:
    return f"""
    (() => {{
      const el = document.querySelector(`[data-webfa-id="${{CSS.escape({json.dumps(element_id)})}}"]`);
      if (!el) throw new Error('element id is stale; call observe again');
      if ({json.dumps(action)} === 'focus') {{
        el.focus();
        return true;
      }}
      if ({json.dumps(action)} === 'click') {{
        el.click();
        return true;
      }}
      if ({json.dumps(action)} === 'type') {{
        el.focus();
        if ('value' in el) {{
          el.value = {json.dumps(text or '')};
          el.dispatchEvent(new InputEvent('input', {{ bubbles: true, inputType: 'insertText', data: {json.dumps(text or '')} }}));
          el.dispatchEvent(new Event('change', {{ bubbles: true }}));
        }} else if (el.isContentEditable) {{
          el.textContent = {json.dumps(text or '')};
          el.dispatchEvent(new InputEvent('input', {{ bubbles: true, inputType: 'insertText', data: {json.dumps(text or '')} }}));
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
