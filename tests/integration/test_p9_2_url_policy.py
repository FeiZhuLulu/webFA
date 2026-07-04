from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.runtime.main import create_app
from browser.managed_chromium_host import _find_chromium_executable
from storage.db import reset_engine_for_tests

PUBLIC_PAGE = Path(__file__).resolve().parents[1] / "fixtures" / "agent_validation_page.html"


def _require_default_browser() -> None:
    pytest.importorskip("websockets.sync.client")
    try:
        _find_chromium_executable()
    except RuntimeError as exc:
        pytest.skip(str(exc))


def test_warn_policy_allows_local_url_with_security_metadata(monkeypatch, tmp_path: Path):
    _require_default_browser()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_PRIVATE_URL_POLICY", "warn")
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    monkeypatch.delenv("WEBFA_BROWSER_DRIVER", raising=False)
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        opened = client.post("/v1/browser/open", json={"url": PUBLIC_PAGE.as_uri()})
        assert opened.status_code == 200, opened.text
        security = opened.json()["state"]["security"]
        assert security["url_class"] == "file"
        assert security["policy"] == "warn"


def test_block_policy_rejects_private_url(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_PRIVATE_URL_POLICY", "block")
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        blocked = client.post("/v1/browser/open", json={"url": "http://127.0.0.1:8787/"})
        assert blocked.status_code == 403, blocked.text
        detail = blocked.json()["detail"]
        assert detail["code"] == "private_url_blocked"
        assert detail.get("recover_hint")


def test_block_policy_rejects_sensitive_query(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_PRIVATE_URL_POLICY", "block")
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        blocked = client.post(
            "/v1/browser/open",
            json={"url": "https://example.com/callback?access_token=secret"},
        )
        assert blocked.status_code == 403, blocked.text
        assert blocked.json()["detail"]["code"] == "sensitive_url_blocked"