import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.runtime.main import create_app
from browser.managed_chromium_host import _find_chromium_executable
from browser.profile_storage import ProfileStorageManager
from storage.db import reset_engine_for_tests

FIXTURE_PAGE = Path(__file__).resolve().parents[1] / "fixtures" / "agent_validation_page.html"
P11_FIXTURE_PAGE = Path(__file__).resolve().parents[1] / "fixtures" / "p11_safety_page.html"
CONTROL_TOKEN = "test-visualizer-control-token"
CONTROL_HEADERS = {"X-WebFA-Visualizer-Token": CONTROL_TOKEN}


@pytest.fixture(autouse=True)
def _visualizer_control_token(monkeypatch):
    monkeypatch.setenv("WEBFA_VISUALIZER_CONTROL_TOKEN", CONTROL_TOKEN)
    original_init = TestClient.__init__

    def _init_with_control_header(self, *args, **kwargs):
        headers = {**CONTROL_HEADERS, **(kwargs.get("headers") or {})}
        kwargs["headers"] = headers
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(TestClient, "__init__", _init_with_control_header)


def _require_default_browser() -> None:
    pytest.importorskip("websockets.sync.client")
    try:
        _find_chromium_executable()
    except RuntimeError as exc:
        pytest.skip(str(exc))


def test_visualizer_state_before_browser_start(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/v1/visualizer/state")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["runtime"]["host_status"] == "not_started"
        assert body["browser_state"] is None
        assert body["web_state"] is None
        assert body["takeover_surface"]["active"] is False
        assert body["recent_actions"] == []
        assert "cookie" not in str(body).lower()

        supervisor = app.state.browser_runtime_supervisor
        assert supervisor.status()["active_session_count"] == 0
        profile = app.state.profile_repository.get_profile("default")
        mutation = ProfileStorageManager(tmp_path / "WebFA").acquire_mutation_lease(
            profile,
            mutation_id="visualizer-read-check",
            operation="cookie_import",
        )
        mutation.release()


def test_visualizer_state_after_open_and_action_log(monkeypatch, tmp_path: Path):
    _require_default_browser()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    monkeypatch.delenv("WEBFA_BROWSER_DRIVER", raising=False)
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        opened = client.post("/v1/browser/open", json={"url": FIXTURE_PAGE.as_uri()})
        assert opened.status_code == 200, opened.text

        response = client.get("/v1/visualizer/state")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["page"]["title"] == "WebFA Agent Validation"
        assert body["browser_state"]["url_parts"]["scheme"] == "file"
        assert body["web_state"]["document_id"]
        assert body["web_state"]["object_count"] >= len(body["web_state"]["objects"])
        assert body["takeover_surface"]["active"] is False
        assert any(entry["tool"] == "webfa.open_url" for entry in body["recent_actions"])
        assert "password" not in str(body).lower() or "[redacted]" in str(body).lower() or body["browser_state"]["forms"]


def test_duplicate_page_auth_surface_is_disabled_by_default(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.delenv("WEBFA_ENABLE_LEGACY_AUTH_SURFACE", raising=False)
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        opened = client.post("/v1/visualizer/open-auth-surface")
        compat = client.post("/v1/visualizer/open-host")
        closed = client.post("/v1/visualizer/close-auth-surface")

    for response in (opened, compat, closed):
        assert response.status_code == 410, response.text
        assert response.json()["detail"]["code"] == "legacy_auth_surface_disabled"
        assert "HumanControlLease" in response.json()["detail"]["message"]


def test_protected_payment_field_requests_payment_verification_takeover(monkeypatch, tmp_path: Path):
    _require_default_browser()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    monkeypatch.setenv("WEBFA_AUTH_SURFACE_MODE", "electron")
    monkeypatch.delenv("WEBFA_BROWSER_DRIVER", raising=False)
    reset_engine_for_tests()

    headers = {"X-WebFA-Agent-Id": "safety-agent"}
    with TestClient(create_app()) as client:
        opened = client.post(
            "/v1/browser/web/open",
            headers=headers,
            json={"url": P11_FIXTURE_PAGE.as_uri()},
        )
        assert opened.status_code == 200, opened.text
        queried = client.post(
            "/v1/browser/web/observe",
            headers=headers,
            json={
                "mode": "query",
                "query": {"name": "Card number"},
                "detail": "full",
                "limit": 10,
            },
        )
        assert queried.status_code == 200, queried.text
        card = next(item for item in queried.json()["objects"] if item.get("name") == "Card number")
        assert card["security"]["protected_kind"] == "payment_card"
        assert card["capabilities"] == ["request_human_takeover"]
        assert card.get("value") in (None, "")

        takeover = client.post(
            "/v1/browser/web/act",
            headers=headers,
            json={
                "target": card["id"],
                "operation": "request_human_takeover",
                "arguments": {},
            },
        )
        assert takeover.status_code == 200, takeover.text
        body = takeover.json()
        assert body["ok"] is True
        assert body["state"]["takeover"]["required"] is True
        assert body["state"]["takeover"]["reason"] == "payment_verification"
        assert body["data"]["takeover_requested"] is True
        assert "4111111111111111" not in str(body)


def test_visualizer_resource_grant_and_real_upload(monkeypatch, tmp_path: Path):
    _require_default_browser()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    monkeypatch.delenv("WEBFA_BROWSER_DRIVER", raising=False)
    reset_engine_for_tests()

    headers = {"X-WebFA-Agent-Id": "upload-agent"}
    with TestClient(create_app()) as client:
        configured = client.put(
            "/v1/visualizer/profile-policy/default",
            json={
                "profile_id": "default",
                "owner": "user_owned",
                "bound_agent_ids": ["upload-agent"],
                "allowed_origins": [],
                "trust_mode": "trusted_agent",
                "unknown_external_effect_policy": "require_step_up",
            },
        )
        assert configured.status_code == 200, configured.text
        opened = client.post(
            "/v1/browser/web/open",
            headers=headers,
            json={"url": P11_FIXTURE_PAGE.as_uri()},
        )
        assert opened.status_code == 200, opened.text
        state = opened.json()["state"]
        upload = next(item for item in state["objects"] if item.get("role") == "upload_target")
        assert upload["capabilities"] == ["upload"]
        serialized = str(state)
        assert "secret-password" not in serialized
        assert "4111111111111111" not in serialized
        assert "123456" not in serialized
        assert "pay-secret" not in serialized

        granted = client.post(
            "/v1/visualizer/resources",
            json={
                "display_name": "resume.txt",
                "content_base64": base64.b64encode(b"WebFA P11 resource").decode("ascii"),
                "owner": "user",
                "purpose": "validation_upload",
                "allowed_origins": ["file://"],
                "bound_agent_ids": ["upload-agent"],
                "bound_profile_ids": ["default"],
                "expires_in_seconds": 3600,
                "max_uses": 1,
            },
        )
        assert granted.status_code == 200, granted.text
        resource = granted.json()["resource"]
        resource_ref = resource["grant"]["resource_ref"]
        assert resource["status"] == "active"
        assert "path" not in str(resource).lower()

        acted = client.post(
            "/v1/browser/web/act",
            headers=headers,
            json={
                "target": upload["id"],
                "operation": "upload",
                "arguments": {
                    "resource_ref": resource_ref,
                    "purpose": "validation_upload",
                },
                "safety": {
                    "declaration": {
                        "principal": {
                            "agent_id": "upload-agent",
                            "profile_id": "default",
                            "account_owner": "user_owned",
                            "trust_mode": "trusted_agent",
                        },
                        "task": {
                            "intent": "upload_validation_file",
                            "subject": "resume.txt",
                        },
                        "dimensions": [
                            {
                                "type": "local_data_egress",
                                "source_owner": "user",
                                "resource_refs": [resource_ref],
                                "destination_origin": "file://",
                                "purpose": "validation_upload",
                            }
                        ],
                        "authorization_claim": {
                            "status": "explicit",
                            "source_ref": "user_turn_upload",
                        },
                        "origin_scope": ["file://"],
                        "max_uses": 1,
                    },
                    "assertions": {
                        "assertions": {
                            "user_authorized_specific_resources": True,
                            "user_authorized_destination": True,
                            "resource_use_matches_task": True,
                        },
                        "authorization_source": "user_turn_upload",
                    },
                },
            },
        )
        assert acted.status_code == 200, acted.text
        body = acted.json()
        assert body["ok"] is True
        assert body["safety_decision"]["decision"] == "allow_with_audit"
        assert body["state"]["safety"]["status"] == "consumed"
        assert "provider_verified" == body["safety_decision"]["evidence_report"]["minimum_assurance"]
        assert "path" not in str(body).lower()

        resources = client.get("/v1/visualizer/resources").json()["resources"]
        uploaded = next(item for item in resources if item["grant"]["resource_ref"] == resource_ref)
        assert uploaded["status"] == "consumed"
        assert uploaded["remaining_uses"] == 0

        observed = client.post(
            "/v1/browser/web/observe",
            headers=headers,
            json={
                "mode": "query",
                "query": {"text_contains": "resume.txt"},
                "detail": "full",
                "limit": 10,
            },
        )
        assert observed.status_code == 200, observed.text
        assert any("resume.txt" in (item.get("text") or item.get("name") or "") for item in observed.json()["objects"])


def test_visualizer_restart_host(monkeypatch, tmp_path: Path):
    _require_default_browser()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    monkeypatch.delenv("WEBFA_BROWSER_DRIVER", raising=False)
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        client.post("/v1/browser/open", json={"url": FIXTURE_PAGE.as_uri()})
        response = client.post("/v1/visualizer/restart-host")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["runtime"]["host_status"] == "running"
        assert body["page"]["title"] == "WebFA Agent Validation"
        assert any(entry["tool"] == "visualizer.restart_host" for entry in body["recent_actions"])
