from fastapi.testclient import TestClient

from apps.runtime.api.visualizer_control import (
    VISUALIZER_CONTROL_HEADER,
    VISUALIZER_CONTROL_SECURITY_SCHEME,
)
from apps.runtime.main import create_app
from browser.profile_storage import ProfileStorageManager
from storage.db import reset_engine_for_tests


TOKEN = "visualizer-control-contract-token"
CONTROL_HEADERS = {VISUALIZER_CONTROL_HEADER: TOKEN}
PROFILE_PAYLOAD = {
    "profile_id": "default",
    "owner": "agent_owned",
    "bound_agent_ids": ["agent-a"],
    "allowed_origins": [],
    "trust_mode": "trusted_agent",
    "unknown_external_effect_policy": "allow_with_audit",
}


def test_visualizer_control_plane_requires_separate_token_for_reads_and_mutations(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_VISUALIZER_CONTROL_TOKEN", TOKEN)
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        missing_state = client.get("/v1/visualizer/state")
        allowed_state = client.get(
            "/v1/visualizer/state",
            headers=CONTROL_HEADERS,
        )
        missing = client.put(
            "/v1/visualizer/profile-policy/default",
            json=PROFILE_PAYLOAD,
        )
        wrong = client.put(
            "/v1/visualizer/profile-policy/default",
            headers={"X-WebFA-Visualizer-Token": "wrong-token"},
            json=PROFILE_PAYLOAD,
        )
        allowed = client.put(
            "/v1/visualizer/profile-policy/default",
            headers=CONTROL_HEADERS,
            json=PROFILE_PAYLOAD,
        )
        missing_provider_connect = client.post(
            "/v1/providers/github/connect",
            json={"token": "must-not-be-stored", "resource_scope": {}},
        )
        missing_provider_test = client.post("/v1/providers/github/test")
        missing_provider_disconnect = client.delete("/v1/providers/github/disconnect")
        missing_provider_status = client.get("/v1/providers/github")
        allowed_provider_status = client.get(
            "/v1/providers/github",
            headers=CONTROL_HEADERS,
        )

    assert missing_state.status_code == 403
    assert allowed_state.status_code == 200
    assert missing.status_code == 403
    assert missing.json()["detail"]["code"] == "visualizer_control_forbidden"
    assert wrong.status_code == 403
    assert allowed.status_code == 200
    assert missing_provider_connect.status_code == 403
    assert missing_provider_test.status_code == 403
    assert missing_provider_disconnect.status_code == 403
    assert missing_provider_status.status_code == 403
    assert allowed_provider_status.status_code == 200
    assert allowed_provider_status.json()["status"] == "disconnected"
    serialized = " ".join(
        response.text
        for response in (
            missing_state,
            allowed_state,
            missing,
            wrong,
            allowed,
            missing_provider_connect,
            missing_provider_test,
            missing_provider_disconnect,
            missing_provider_status,
            allowed_provider_status,
        )
    )
    assert TOKEN not in serialized


def test_profile_policy_control_does_not_create_a_browser_session(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_VISUALIZER_CONTROL_TOKEN", TOKEN)
    reset_engine_for_tests()
    app = create_app()

    with TestClient(app) as client:
        read = client.get(
            "/v1/visualizer/profile-policy/default",
            headers=CONTROL_HEADERS,
        )
        assert read.status_code == 200, read.text
        assert getattr(app.state, "browser_runtime", None) is None
        assert getattr(app.state, "browser_runtime_supervisor", None) is None

        written = client.put(
            "/v1/visualizer/profile-policy/default",
            headers=CONTROL_HEADERS,
            json=PROFILE_PAYLOAD,
        )
        assert written.status_code == 200, written.text
        assert getattr(app.state, "browser_runtime", None) is None
        assert getattr(app.state, "browser_runtime_supervisor", None) is None


def test_empty_control_reads_do_not_create_a_browser_session(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_VISUALIZER_CONTROL_TOKEN", TOKEN)
    reset_engine_for_tests()
    app = create_app()

    with TestClient(app) as client:
        responses = {
            "/v1/visualizer/financial-policies": "policies",
            "/v1/visualizer/payment-instruments": "instruments",
            "/v1/visualizer/step-ups": "step_ups",
            "/v1/visualizer/safety-receipts": "receipts",
            "/v1/visualizer/resources": "resources",
        }
        for path, field in responses.items():
            response = client.get(path, headers=CONTROL_HEADERS)
            assert response.status_code == 200, response.text
            assert response.json()[field] == []

        supervisor = app.state.browser_runtime_supervisor
        assert supervisor is not None
        assert supervisor.status()["active_session_count"] == 0


def test_profile_policy_update_is_catalog_metadata_not_storage_maintenance(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_VISUALIZER_CONTROL_TOKEN", TOKEN)
    reset_engine_for_tests()
    app = create_app()

    with TestClient(app) as client:
        storage = ProfileStorageManager(tmp_path / "WebFA")
        app.state.profile_storage_manager = storage
        blocker = storage.acquire_process_lock(
            "default",
            runtime_instance_id="other-runtime",
            runtime_generation="other-generation",
            session_id="other-session",
        )
        try:
            updated = client.put(
                "/v1/visualizer/profile-policy/default",
                headers=CONTROL_HEADERS,
                json=PROFILE_PAYLOAD,
            )
            assert updated.status_code == 200, updated.text
            changed = app.state.profile_repository.get_profile("default")
            assert changed.owner == "agent_owned"
            assert changed.bound_agent_ids == ["agent-a"]
            assert changed.version == 2
            assert getattr(app.state, "browser_runtime", None) is None
        finally:
            blocker.release()


def test_visualizer_control_plane_fails_closed_when_token_is_unconfigured(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.delenv("WEBFA_VISUALIZER_CONTROL_TOKEN", raising=False)
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        response = client.put(
            "/v1/visualizer/profile-policy/default",
            headers=CONTROL_HEADERS,
            json=PROFILE_PAYLOAD,
        )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "visualizer_control_unavailable"


def test_openapi_describes_the_human_control_boundary():
    schema = create_app().openapi()
    security_schemes = schema["components"]["securitySchemes"]
    assert security_schemes[VISUALIZER_CONTROL_SECURITY_SCHEME] == {
        "type": "apiKey",
        "description": (
            "Process-local capability for the trusted human control plane. "
            "It is not an Agent Runtime credential."
        ),
        "in": "header",
        "name": VISUALIZER_CONTROL_HEADER,
    }

    expected_security = [{VISUALIZER_CONTROL_SECURITY_SCHEME: []}]
    for path, path_item in schema["paths"].items():
        if path.startswith(("/v1/visualizer/", "/v1/profiles", "/v1/profile-bundles/")):
            for operation in path_item.values():
                assert operation.get("security") == expected_security, path

    for method, path in (
        ("post", "/v1/approvals/{approval_id}/approve"),
        ("post", "/v1/approvals/{approval_id}/reject"),
        ("get", "/v1/providers/github"),
        ("post", "/v1/providers/github/connect"),
        ("post", "/v1/providers/github/test"),
        ("delete", "/v1/providers/github/disconnect"),
    ):
        assert schema["paths"][path][method]["security"] == expected_security

    for method, path in (
        ("get", "/health"),
        ("post", "/v1/browser/web/open"),
        ("get", "/v1/approvals"),
        ("get", "/v1/approvals/{approval_id}"),
        ("get", "/v1/providers"),
    ):
        assert "security" not in schema["paths"][path][method]

    for method, path in (
        ("post", "/v1/browser/legacy/open"),
        ("get", "/v1/browser/legacy/observe"),
        ("post", "/v1/browser/legacy/act"),
        ("post", "/v1/browser/legacy/tabs/switch"),
        ("post", "/v1/visualizer/open-auth-surface"),
        ("post", "/v1/visualizer/open-host"),
        ("post", "/v1/visualizer/close-auth-surface"),
    ):
        assert schema["paths"][path][method]["deprecated"] is True
