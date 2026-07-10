from __future__ import annotations

import json
import time
from typing import Any, Callable, TypeVar

from browser.driver import CONTENT_BLOCK_MAX_CHARS, CONTENT_BLOCK_MAX_COUNT, VISIBLE_TEXT_MAX_CHARS
from browser.host import BrowserHost
from browser.observe_probe import OBSERVE_PROBE
from browser.raw_snapshot import (
    RawEvidenceError,
    RawWebSnapshot,
    parse_accessibility_tree,
    parse_dom_snapshot,
    parse_frame_tree,
)
from schemas.browser import BrowserTab, BrowserViewport


T = TypeVar("T")


class RawSnapshotCollector:
    """Collect WebFA-owned raw evidence without exposing CDP payloads to agents."""

    def __init__(self, host: BrowserHost) -> None:
        self._host = host

    def collect(self, *, tabs: list[BrowserTab], dialogs: list[dict]) -> RawWebSnapshot:
        probe = self._read_probe_snapshot()
        if not isinstance(probe, dict):
            raise RuntimeError("observe probe did not return a raw page snapshot")

        url = str(self._host.evaluate("window.location.href"))
        title = str(self._host.evaluate("document.title"))
        viewport_value = self._host.evaluate("({ width: window.innerWidth, height: window.innerHeight })")
        viewport = viewport_value if isinstance(viewport_value, dict) else {"width": 1280, "height": 720}

        errors: list[RawEvidenceError] = []
        accessibility_nodes = self._capture_optional(
            "capture_accessibility_tree",
            parse_accessibility_tree,
            "accessibility",
            errors,
        )
        dom_documents = self._capture_optional(
            "capture_dom_snapshot",
            parse_dom_snapshot,
            "dom_snapshot",
            errors,
        )
        engine_frames = self._capture_optional(
            "get_frame_tree",
            parse_frame_tree,
            "frame_tree",
            errors,
        )

        frames = probe.get("frames", [])
        if not frames:
            frames = [
                {
                    "id": "frame_1",
                    "parent_id": None,
                    "url": url,
                    "title": title,
                    "same_origin": True,
                    "visible": True,
                }
            ]

        interactive_elements = _sanitize_legacy_elements(probe.get("interactive_elements", []))
        forms = _sanitize_legacy_forms(probe.get("forms", []))

        return RawWebSnapshot(
            url=url,
            title=title,
            loading=bool(probe.get("loading")),
            focused_element_id=_optional_string(probe.get("focused_element_id")),
            viewport=BrowserViewport(
                width=_safe_int(viewport.get("width"), 1280),
                height=_safe_int(viewport.get("height"), 720),
            ),
            tabs=tabs,
            visible_text=str(probe.get("visible_text", "")),
            content_blocks=_dict_list(probe.get("content_blocks")),
            forms=forms,
            interactive_elements=interactive_elements,
            dialogs=_dict_list(dialogs),
            frames=_dict_list(frames),
            accessibility_nodes=accessibility_nodes,
            dom_documents=dom_documents,
            engine_frames=engine_frames,
            evidence_errors=errors,
        )

    def _capture_optional(
        self,
        method_name: str,
        parser: Callable[[Any], list[T]],
        source: str,
        errors: list[RawEvidenceError],
    ) -> list[T]:
        method = getattr(self._host, method_name, None)
        if not callable(method):
            errors.append(
                RawEvidenceError(
                    source=source,
                    code="evidence_unavailable",
                    message=f"browser host does not provide {method_name}",
                )
            )
            return []
        try:
            payload = method()
            return parser(payload)
        except Exception as exc:
            errors.append(
                RawEvidenceError(
                    source=source,
                    code="evidence_collection_failed",
                    message=str(exc),
                )
            )
            return []

    def _read_probe_snapshot(self) -> dict:
        deadline = time.monotonic() + 2.0
        last: dict | None = None
        while time.monotonic() < deadline:
            raw = self._host.evaluate(_probe_expression())
            if isinstance(raw, dict):
                last = raw
                if not _probe_needs_iframe_retry(raw):
                    return raw
            time.sleep(0.05)
        return last or {}


def _probe_expression() -> str:
    opts = {
        "maxChars": VISIBLE_TEXT_MAX_CHARS,
        "blockChars": CONTENT_BLOCK_MAX_CHARS,
        "blockCount": CONTENT_BLOCK_MAX_COUNT,
    }
    return f"({OBSERVE_PROBE})({json.dumps(opts)})"


def _probe_needs_iframe_retry(raw: dict) -> bool:
    frames = raw.get("frames", [])
    child_frames = [frame for frame in frames if isinstance(frame, dict) and frame.get("id") != "frame_1"]
    if not child_frames:
        return False
    if not any(frame.get("same_origin") for frame in child_frames):
        return False
    elements = raw.get("interactive_elements", [])
    return not any(
        isinstance(element, dict)
        and element.get("frame_id")
        and element.get("frame_id") != "frame_1"
        for element in elements
    )


def _sanitize_legacy_elements(value: Any) -> list[dict]:
    elements: list[dict] = []
    for item in _dict_list(value):
        clean = dict(item)
        if str(clean.get("input_type") or "").lower() == "password":
            clean["value"] = ""
        elements.append(clean)
    return elements


def _sanitize_legacy_forms(value: Any) -> list[dict]:
    forms: list[dict] = []
    for item in _dict_list(value):
        clean = dict(item)
        details: list[dict] = []
        for field in _dict_list(clean.get("field_details")):
            field_clean = dict(field)
            if str(field_clean.get("type") or "").lower() == "password":
                field_clean["value"] = ""
            details.append(field_clean)
        clean["field_details"] = details
        forms.append(clean)
    return forms


def _dict_list(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _optional_string(value: Any) -> str | None:
    return str(value) if value else None


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
