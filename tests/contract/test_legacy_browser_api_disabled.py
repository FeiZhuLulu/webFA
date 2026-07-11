from __future__ import annotations

from fastapi.testclient import TestClient

from apps.runtime.main import create_app
from storage.db import reset_engine_for_tests


def test_legacy_browser_api_is_disabled_by_default(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.delenv("WEBFA_ENABLE_UNSAFE_LEGACY_BROWSER_API", raising=False)
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        responses = [
            client.post("/v1/browser/legacy/open", json={"url": "https://example.com"}),
            client.get("/v1/browser/legacy/observe"),
            client.post(
                "/v1/browser/legacy/act",
                json={"action": "click", "target": "element_1"},
            ),
            client.post(
                "/v1/browser/legacy/tabs/switch",
                json={"tab_id": "tab_1"},
            ),
            client.post(
                "/v1/browser/act",
                json={"action": "click", "target": "element_1"},
            ),
        ]

    assert all(response.status_code == 410 for response in responses)
    assert all(
        response.json()["detail"]["code"] == "legacy_browser_api_disabled"
        for response in responses
    )
