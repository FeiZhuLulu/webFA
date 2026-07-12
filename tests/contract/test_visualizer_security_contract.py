from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.runtime.main import create_app
from storage.db import reset_engine_for_tests

FIXTURE_PAGE = Path(__file__).resolve().parents[1] / "fixtures" / "agent_validation_page.html"
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


def test_visualizer_state_has_no_sensitive_fields(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        body = client.get("/v1/visualizer/state").json()
        body_str = str(body).lower()

    assert body["step_ups"] == []
    assert body["safety_receipts"] == []
    assert {"bound_agent_ids", "allowed_origins", "financial_policy_id"}.issubset(body["profile"])
    for forbidden in (
        "cookie",
        "localstorage",
        "sessionstorage",
        "authorization",
        "devtools",
        "websocket",
        "card_number",
        "payment_password",
        "wallet_token",
    ):
        assert forbidden not in body_str


def test_open_host_compat_is_disabled_in_favor_of_same_page_human_control(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.delenv("WEBFA_ENABLE_LEGACY_AUTH_SURFACE", raising=False)
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        response = client.post("/v1/visualizer/open-host")

    assert response.status_code == 410
    detail = response.json()["detail"]
    assert detail["code"] == "legacy_auth_surface_disabled"
    assert "HumanControlLease" in detail["message"]


def test_visualizer_resource_grant_exposes_only_opaque_reference(monkeypatch, tmp_path: Path):
    import base64

    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        created = client.post(
            "/v1/visualizer/resources",
            json={
                "display_name": "safe.txt",
                "content_base64": base64.b64encode(b"safe").decode("ascii"),
                "owner": "user",
                "purpose": "contract_test",
                "allowed_origins": ["https://example.com"],
                "bound_agent_ids": ["agent-a"],
                "bound_profile_ids": ["default"],
                "expires_in_seconds": 3600,
                "max_uses": 1,
            },
        )
        assert created.status_code == 200, created.text
        body = created.json()
        listed = client.get("/v1/visualizer/resources").json()

    serialized = f"{body} {listed}".lower()
    assert body["resource"]["grant"]["resource_ref"].startswith("resource_")
    assert "path" not in serialized
    assert str(tmp_path).lower() not in serialized
    assert "content_base64" not in serialized


def test_payment_instrument_api_exposes_safe_metadata_only(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        policy = client.post(
            "/v1/visualizer/financial-policies",
            json={
                "policy_id": "policy-safe",
                "currency": "USD",
                "autonomy_limit": "50.00",
                "step_up_limit": "200.00",
                "absolute_limit": "500.00",
            },
        )
        assert policy.status_code == 200, policy.text
        created = client.post(
            "/v1/visualizer/payment-instruments",
            json={
                "instrument_id": "pay-safe",
                "owner": "agent",
                "profile_id": "default",
                "type": "merchant_saved",
                "brand": "Visa",
                "last4": "4821",
                "currency": "USD",
                "policy_id": "policy-safe",
            },
        )
        assert created.status_code == 200, created.text
        rejected = client.post(
            "/v1/visualizer/payment-instruments",
            json={
                "instrument_id": "pay-secret",
                "owner": "agent",
                "profile_id": "default",
                "type": "merchant_saved",
                "brand": "Visa",
                "last4": "1111",
                "currency": "USD",
                "policy_id": "policy-safe",
                "card_number": "4111111111111111",
                "cvv": "123",
            },
        )
        listed = client.get("/v1/visualizer/payment-instruments")

    assert rejected.status_code == 422
    serialized = f"{created.text} {listed.text}".lower()
    assert "4111111111111111" not in serialized
    assert '"cvv"' not in serialized
    assert "wallet_token" not in serialized
    assert "payment_password" not in serialized
    assert "4821" in serialized


def test_mcp_tool_count_unchanged_after_visualizer_route(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        tools = client.get("/v1/mcp/status").json()["tools"]

    assert tools == [
        "webfa.open_url",
        "webfa.observe",
        "webfa.act",
        "webfa.get_tabs",
        "webfa.switch_tab",
    ]