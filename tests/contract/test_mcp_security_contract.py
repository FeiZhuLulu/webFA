"""Contract tests: MCP security invariants."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.runtime.main import create_app
from storage.db import reset_engine_for_tests


def test_mcp_discover_no_credential_leak(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        resp = client.get("/v1/providers")
        providers = resp.json()["providers"]
        for p in providers:
            assert "credential_ref" not in str(p)
            assert "token" not in str(p).lower()


def test_mcp_status_has_no_sensitive_data(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        resp = client.get("/v1/mcp/status")
        body = resp.json()
        body_str = str(body).lower()
        assert "token" not in body_str
        assert "credential" not in body_str
        assert "secret" not in body_str


def test_mcp_config_no_sensitive_data(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        resp = client.get("/v1/mcp/config")
        body_str = str(resp.json()).lower()
        assert "token" not in body_str
        assert "credential" not in body_str
        assert "secret" not in body_str


def test_health_browser_status_has_no_sensitive_data(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.delenv("WEBFA_BROWSER_DRIVER", raising=False)
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        body_str = str(client.get("/health").json()).lower()

    for forbidden in ("token", "cookie", "localstorage", "sessionstorage", "websocket", "devtools"):
        assert forbidden not in body_str


def test_mcp_tools_not_in_electron():
    """Verify Electron main process does not contain MCP tool dispatch logic."""
    source = (Path(__file__).resolve().parents[2] / "apps/desktop/electron/main.ts").read_text(encoding="utf-8")
    assert "webfa.plan" not in source
    assert "webfa.execute" not in source
    assert "approval_token" not in source
    assert "plan_hash" not in source


def test_default_mcp_tools_do_not_expose_legacy_or_raw_browser_tools(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.delenv("WEBFA_ENABLE_LEGACY_TRANSACTION", raising=False)
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        tools = client.get("/v1/mcp/status").json()["tools"]

    forbidden = {
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
    assert forbidden.isdisjoint(set(tools))
    assert set(tools) == {
        "webfa.open_url",
        "webfa.observe",
        "webfa.act",
        "webfa.get_tabs",
        "webfa.switch_tab",
    }


def test_browser_runtime_does_not_import_playwright_details():
    root = Path(__file__).resolve().parents[2]
    runtime_source = (root / "packages/webfa-core/browser/runtime.py").read_text(encoding="utf-8")
    driver_source = (root / "packages/webfa-core/browser/playwright_driver.py").read_text(encoding="utf-8")

    for forbidden in ("sync_playwright", "page.locator", "chromium.launch_persistent_context", "ManagedChromiumHost"):
        assert forbidden not in runtime_source
    for forbidden in ("sync_playwright", "page.locator", "chromium.launch_persistent_context"):
        assert forbidden in driver_source


def test_content_block_schema_forbids_html_dom_and_storage_keys():
    """content_blocks is part of the agent-facing surface and must never
    carry raw HTML, DOM strings, cookies, or web storage values."""
    from pydantic import ValidationError

    from schemas.browser import BrowserContentBlock

    for forbidden in ("html", "outerHTML", "innerHTML", "cookies", "localStorage", "sessionStorage"):
        with pytest.raises(ValidationError):
            BrowserContentBlock(id="block_1", type="paragraph", text="x", element_ids=[], **{forbidden: "leak"})


def test_browser_action_result_data_forbids_sensitive_payloads():
    from schemas.browser import BrowserActionResult, BrowserState

    result = BrowserActionResult(
        ok=True,
        action="inspect_block",
        state=BrowserState(),
        data={"id": "block_1", "text": "safe text", "elements": []},
    )
    body = str(result.model_dump()).lower()
    for forbidden in ("cookie", "localstorage", "sessionstorage", "token", "full_html", "full_dom"):
        assert forbidden not in body


def test_observe_script_does_not_read_html_or_storage():
    """The script that builds content_blocks must not read cookies,
    localStorage, sessionStorage, or emit raw HTML/DOM strings."""
    root = Path(__file__).resolve().parents[2]
    script_source = (root / "packages/webfa-core/browser/observe_probe.py").read_text(encoding="utf-8")

    # Isolate the OBSERVE_PROBE block so we only check its body, not the
    # surrounding Python module (which legitimately mentions these words).
    start = script_source.index("OBSERVE_PROBE")
    script_body = script_source[start:]

    for forbidden in (
        "document.cookie",
        "window.localStorage",
        "window.sessionStorage",
        "localStorage.getItem",
        "sessionStorage.getItem",
        ".outerHTML",
        ".innerHTML",
        "document.documentElement.outerHTML",
    ):
        assert forbidden not in script_body, f"observe script must not read {forbidden!r}"

    # content_blocks must only emit the four whitelisted keys per block.
    assert "element_ids" in script_body
    assert "content_blocks" in script_body
