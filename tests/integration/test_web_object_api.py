from __future__ import annotations

from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading

import pytest
from fastapi.testclient import TestClient

from apps.runtime.main import create_app
from browser.managed_chromium_host import _find_chromium_executable
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


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        return


@contextmanager
def _serve_fixtures():
    handler = partial(_QuietHandler, directory=str(FIXTURE_PAGE.parent))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _require_managed_chromium() -> None:
    pytest.importorskip("websockets.sync.client")
    try:
        _find_chromium_executable()
    except RuntimeError as exc:
        pytest.skip(str(exc))


def _find_object(state: dict, *, role: str, name: str | None = None) -> dict:
    for item in state["objects"]:
        if item.get("role") != role:
            continue
        if name is not None and item.get("name") != name:
            continue
        return item
    raise AssertionError(f"WebObject not found: role={role}, name={name}")


def _set_agent_owned_profile(client: TestClient, agent_id: str) -> None:
    response = client.put(
        "/v1/visualizer/profile-policy/default",
        json={
            "profile_id": "default",
            "owner": "agent_owned",
            "bound_agent_ids": [agent_id],
            "allowed_origins": [],
            "trust_mode": "trusted_agent",
            "unknown_external_effect_policy": "allow_with_audit",
        },
    )
    assert response.status_code == 200, response.text


def test_public_web_object_rest_loop(monkeypatch, tmp_path: Path):
    _require_managed_chromium()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    monkeypatch.delenv("WEBFA_BROWSER_DRIVER", raising=False)
    reset_engine_for_tests()

    headers = {"X-WebFA-Agent-Id": "web-api-test"}
    with TestClient(create_app()) as client:
        opened = client.post(
            "/v1/browser/web/open",
            headers=headers,
            json={"url": FIXTURE_PAGE.as_uri()},
        )
        assert opened.status_code == 200, opened.text
        state = opened.json()["state"]
        assert state["document_id"]
        assert state["document_revision"] >= 1
        assert state["url"].endswith("agent_validation_page.html")

        field = _find_object(state, role="textbox", name="Your name")
        form = _find_object(state, role="form")
        assert "set_value" in field["capabilities"]
        assert "submit" in form["capabilities"]

        typed = client.post(
            "/v1/browser/web/act",
            headers=headers,
            json={
                "target": field["id"],
                "operation": "set_value",
                "arguments": {"value": "Fei"},
                "expected_object_version": field["version"],
            },
        )
        assert typed.status_code == 200, typed.text
        assert typed.json()["operation"] == "set_value"

        submitted = client.post(
            "/v1/browser/web/act",
            headers=headers,
            json={"target": form["id"], "operation": "submit", "arguments": {}},
        )
        assert submitted.status_code == 200, submitted.text

        queried = client.post(
            "/v1/browser/web/observe",
            headers=headers,
            json={
                "mode": "query",
                "query": {"text_contains": "Hello Fei"},
                "detail": "full",
                "limit": 10,
            },
        )
        assert queried.status_code == 200, queried.text
        query_state = queried.json()
        assert any("Hello Fei" in (item.get("text") or item.get("name") or "") for item in query_state["objects"])


def test_public_web_object_rest_safety_handshake(monkeypatch, tmp_path: Path):
    _require_managed_chromium()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    monkeypatch.delenv("WEBFA_BROWSER_DRIVER", raising=False)
    reset_engine_for_tests()

    agent_id = "safety-api-test"
    headers = {"X-WebFA-Agent-Id": agent_id}
    declaration = {
        "principal": {
            "agent_id": agent_id,
            "profile_id": "default",
            "account_owner": "agent_owned",
        },
        "task": {"intent": "submit_fixture", "subject": "fixture form"},
        "dimensions": [
            {
                "type": "financial_commitment",
                "kind": "one_time_purchase",
                "currency": "CNY",
                "maximum_amount": "300.00",
            }
        ],
        "authorization_claim": {
            "status": "explicit",
            "source_ref": "user_turn_fixture",
        },
        "expires_in_seconds": 3600,
        "max_uses": 1,
    }

    with TestClient(create_app()) as client:
        _set_agent_owned_profile(client, agent_id)
        opened = client.post(
            "/v1/browser/web/open",
            headers=headers,
            json={
                "url": FIXTURE_PAGE.as_uri(),
                "safety": {"declaration": declaration},
            },
        )
        assert opened.status_code == 200, opened.text
        opened_body = opened.json()
        assert opened_body["safety_decision"]["decision"] == "require_assertion"
        context_id = opened_body["safety_decision"]["context_id"]
        state = opened_body["state"]
        assert state["safety"]["status"] == "assertion_required"

        form = _find_object(state, role="form")
        pending = client.post(
            "/v1/browser/web/act",
            headers=headers,
            json={
                "target": form["id"],
                "operation": "submit",
                "arguments": {},
                "safety": {"context_id": context_id},
            },
        )
        assert pending.status_code == 200, pending.text
        pending_body = pending.json()
        assert pending_body["ok"] is False
        assert pending_body["safety_decision"]["decision"] == "require_assertion"
        assert pending_body["data"] == {"executed": False}

        submitted = client.post(
            "/v1/browser/web/act",
            headers=headers,
            json={
                "target": form["id"],
                "operation": "submit",
                "arguments": {},
                "expected_document_revision": state["document_revision"],
                "safety": {
                    "context_id": context_id,
                    "assertions": {
                        "assertions": {
                            "user_explicitly_authorized_purchase": True,
                            "user_explicitly_authorized_payment": True,
                            "actual_amount_within_authorized_scope": True,
                            "merchant_and_subject_match_task": True,
                            "no_unapproved_recurring_commitment": True,
                        },
                        "authorization_source": "user_turn_fixture",
                    },
                },
            },
        )
        assert submitted.status_code == 200, submitted.text
        body = submitted.json()
        assert body["ok"] is True
        assert body["safety_decision"]["decision"] == "allow_with_audit"
        assert body["state"]["safety"]["status"] == "consumed"
        assert body["data"] is None or body["data"].get("executed", True) is True


def test_runtime_evidence_requires_context_for_external_submit_then_allows_agent_owned_unknown_effect(monkeypatch, tmp_path: Path):
    _require_managed_chromium()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    monkeypatch.setenv("WEBFA_PRIVATE_URL_POLICY", "allow")
    monkeypatch.delenv("WEBFA_BROWSER_DRIVER", raising=False)
    reset_engine_for_tests()

    headers = {"X-WebFA-Agent-Id": "external-agent"}
    with _serve_fixtures() as base_url, TestClient(create_app()) as client:
        _set_agent_owned_profile(client, "external-agent")
        opened = client.post(
            "/v1/browser/web/open",
            headers=headers,
            json={"url": f"{base_url}/agent_validation_page.html"},
        )
        assert opened.status_code == 200, opened.text
        state = opened.json()["state"]
        form = _find_object(state, role="form")

        blocked = client.post(
            "/v1/browser/web/act",
            headers=headers,
            json={"target": form["id"], "operation": "submit", "arguments": {}},
        )
        assert blocked.status_code == 200, blocked.text
        blocked_body = blocked.json()
        assert blocked_body["ok"] is False
        assert blocked_body["data"]["executed"] is False
        assert blocked_body["safety_decision"]["decision"] == "require_assertion"
        assert blocked_body["safety_decision"]["status"] == "undeclared"
        assert "unknown_external_effect" in blocked_body["safety_decision"]["evidence_report"]["observed_dimensions"]

        allowed = client.post(
            "/v1/browser/web/act",
            headers=headers,
            json={
                "target": form["id"],
                "operation": "submit",
                "arguments": {},
                "safety": {
                    "declaration": {
                        "principal": {
                            "agent_id": "external-agent",
                            "profile_id": "default",
                            "account_owner": "agent_owned",
                            "trust_mode": "trusted_agent",
                        },
                        "task": {
                            "intent": "submit_agent_owned_form",
                            "subject": "validation form",
                        },
                        "dimensions": [
                            {
                                "type": "unknown_external_effect",
                                "summary": "submit the Agent-owned validation form",
                            }
                        ],
                        "authorization_claim": {
                            "status": "explicit",
                            "source_ref": "user_turn_external_submit",
                        },
                        "origin_scope": [base_url],
                        "max_uses": 1,
                    }
                },
            },
        )
        assert allowed.status_code == 200, allowed.text
        allowed_body = allowed.json()
        assert allowed_body["ok"] is True
        assert allowed_body["safety_decision"]["decision"] == "allow_with_audit"
        assert allowed_body["state"]["safety"]["status"] == "consumed"
        assert any(
            mismatch["severity"] == "audit"
            for mismatch in allowed_body["safety_decision"]["evidence_report"]["mismatches"]
        ) is False


def test_user_owned_identity_switch_requires_profile_step_up(monkeypatch, tmp_path: Path):
    _require_managed_chromium()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    monkeypatch.delenv("WEBFA_BROWSER_DRIVER", raising=False)
    reset_engine_for_tests()

    agent_id = "identity-agent"
    headers = {"X-WebFA-Agent-Id": agent_id}
    with TestClient(create_app()) as client:
        configured = client.put(
            "/v1/visualizer/profile-policy/default",
            json={
                "profile_id": "default",
                "owner": "user_owned",
                "bound_agent_ids": [agent_id],
                "allowed_origins": [],
                "trust_mode": "trusted_agent",
                "unknown_external_effect_policy": "require_step_up",
            },
        )
        assert configured.status_code == 200, configured.text
        opened = client.post(
            "/v1/browser/web/open",
            headers=headers,
            json={"url": FIXTURE_PAGE.as_uri()},
        )
        assert opened.status_code == 200, opened.text
        target = _find_object(opened.json()["state"], role="button")

        switched = client.post(
            "/v1/browser/web/act",
            headers=headers,
            json={
                "target": target["id"],
                "operation": "activate",
                "arguments": {},
                "safety": {
                    "declaration": {
                        "principal": {
                            "agent_id": agent_id,
                            "profile_id": "default",
                            "account_owner": "user_owned",
                            "trust_mode": "trusted_agent",
                        },
                        "task": {"intent": "switch_account", "subject": "user account"},
                        "dimensions": [
                            {
                                "type": "identity_context",
                                "account_owner": "user_owned",
                                "action": "switch_account",
                            }
                        ],
                        "authorization_claim": {
                            "status": "explicit",
                            "source_ref": "user_turn_identity",
                        },
                        "origin_scope": ["file://"],
                    },
                    "assertions": {
                        "assertions": {
                            "current_identity_matches_task": True,
                            "user_authorized_use_of_user_identity": True,
                            "no_unapproved_identity_switch": True,
                        },
                        "authorization_source": "user_turn_identity",
                    },
                },
            },
        )
        assert switched.status_code == 200, switched.text
        body = switched.json()
        assert body["ok"] is False
        assert body["safety_decision"]["decision"] == "require_step_up"
        assert body["safety_decision"]["status"] == "step_up_required"
        assert body["data"]["executed"] is False
        assert body["data"]["step_up_id"].startswith("stepup_")
        assert body["safety_decision"]["step_up"]["status"] == "pending"


def test_open_url_profile_step_up_can_be_approved_and_consumed(monkeypatch, tmp_path: Path):
    _require_managed_chromium()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    monkeypatch.delenv("WEBFA_BROWSER_DRIVER", raising=False)
    reset_engine_for_tests()

    agent_id = "open-step-up-agent"
    headers = {"X-WebFA-Agent-Id": agent_id}
    declaration = {
        "principal": {
            "agent_id": agent_id,
            "profile_id": "default",
            "account_owner": "user_owned",
            "trust_mode": "trusted_agent",
        },
        "task": {"intent": "switch_account", "subject": "user account"},
        "dimensions": [
            {
                "type": "identity_context",
                "account_owner": "user_owned",
                "action": "switch_account",
            }
        ],
        "authorization_claim": {
            "status": "explicit",
            "source_ref": "user_turn_open_identity",
        },
        "origin_scope": ["https://other.example"],
        "max_uses": 1,
    }
    assertions = {
        "assertions": {
            "current_identity_matches_task": True,
            "user_authorized_use_of_user_identity": True,
            "no_unapproved_identity_switch": True,
        },
        "authorization_source": "user_turn_open_identity",
    }

    with TestClient(create_app()) as client:
        configured = client.put(
            "/v1/visualizer/profile-policy/default",
            json={
                "profile_id": "default",
                "owner": "user_owned",
                "bound_agent_ids": [agent_id],
                "allowed_origins": [],
                "trust_mode": "trusted_agent",
                "unknown_external_effect_policy": "require_step_up",
            },
        )
        assert configured.status_code == 200, configured.text

        first = client.post(
            "/v1/browser/web/open",
            headers=headers,
            json={
                "url": FIXTURE_PAGE.as_uri(),
                "safety": {"declaration": declaration, "assertions": assertions},
            },
        )
        assert first.status_code == 200, first.text
        first_body = first.json()
        assert first_body["ok"] is False
        assert first_body["safety_decision"]["decision"] == "require_step_up"
        step_up_request = first_body["safety_decision"]["step_up"]["request"]
        step_up_id = step_up_request["step_up_id"]
        assert step_up_request["requested_scope"]["action"] == "switch_account"
        assert step_up_request["requested_scope"]["origin"] == "file://"
        assert first_body["safety_receipt"]["step_up_id"] == step_up_id

        approved = client.post(
            f"/v1/visualizer/step-ups/{step_up_id}/approve",
            json={"decided_by": "test-user", "decision_note": "allow this navigation"},
        )
        assert approved.status_code == 200, approved.text

        retried = client.post(
            "/v1/browser/web/open",
            headers=headers,
            json={
                "url": FIXTURE_PAGE.as_uri(),
                "safety": {
                    "declaration": declaration,
                    "assertions": assertions,
                    "step_up_id": step_up_id,
                },
            },
        )
        assert retried.status_code == 200, retried.text
        retried_body = retried.json()
        assert retried_body["ok"] is True
        assert retried_body["state"]["url"].endswith("agent_validation_page.html")
        assert retried_body["safety_receipt"]["step_up_id"] == step_up_id
        states = client.get("/v1/visualizer/step-ups").json()["step_ups"]
        assert states[0]["status"] == "consumed"


def test_safety_context_origin_step_up_blocks_navigation_until_approved(monkeypatch, tmp_path: Path):
    _require_managed_chromium()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    monkeypatch.setenv("WEBFA_PRIVATE_URL_POLICY", "allow")
    monkeypatch.delenv("WEBFA_BROWSER_DRIVER", raising=False)
    reset_engine_for_tests()

    agent_id = "origin-step-up-agent"
    headers = {"X-WebFA-Agent-Id": agent_id}
    with _serve_fixtures() as base_url, TestClient(create_app()) as client:
        _set_agent_owned_profile(client, agent_id)
        initial = client.post(
            "/v1/browser/web/open",
            headers=headers,
            json={
                "url": FIXTURE_PAGE.as_uri(),
                "safety": {
                    "declaration": {
                        "principal": {
                            "agent_id": agent_id,
                            "profile_id": "default",
                            "account_owner": "agent_owned",
                            "trust_mode": "trusted_agent",
                        },
                        "task": {"intent": "use_agent_account", "subject": "local fixture"},
                        "dimensions": [
                            {
                                "type": "identity_context",
                                "account_owner": "agent_owned",
                                "action": "use_existing_account",
                            }
                        ],
                        "authorization_claim": {
                            "status": "explicit",
                            "source_ref": "user_turn_origin_scope",
                        },
                        "origin_scope": ["file://"],
                        "max_uses": 2,
                    },
                    "assertions": {
                        "assertions": {
                            "current_identity_matches_task": True,
                            "no_unapproved_identity_switch": True,
                        },
                        "authorization_source": "user_turn_origin_scope",
                    },
                },
            },
        )
        assert initial.status_code == 200, initial.text
        initial_body = initial.json()
        assert initial_body["ok"] is True
        context_id = initial_body["safety_decision"]["context_id"]

        blocked = client.post(
            "/v1/browser/web/open",
            headers=headers,
            json={
                "url": f"{base_url}/p11_safety_page.html",
                "safety": {"context_id": context_id},
            },
        )
        assert blocked.status_code == 200, blocked.text
        blocked_body = blocked.json()
        assert blocked_body["ok"] is False
        assert blocked_body["safety_decision"]["decision"] == "require_step_up"
        step_up_id = blocked_body["safety_decision"]["step_up"]["request"]["step_up_id"]
        requested_scope = blocked_body["safety_decision"]["step_up"]["request"]["requested_scope"]
        assert requested_scope["origin"] == base_url
        assert requested_scope["url"] == f"{base_url}/p11_safety_page.html"

        still_local = client.post(
            "/v1/browser/web/observe",
            headers=headers,
            json={"mode": "page", "detail": "summary", "limit": 10},
        )
        assert still_local.status_code == 200, still_local.text
        assert still_local.json()["url"].endswith("agent_validation_page.html")

        approved = client.post(
            f"/v1/visualizer/step-ups/{step_up_id}/approve",
            json={"decided_by": "test-user", "decision_note": "allow exact origin"},
        )
        assert approved.status_code == 200, approved.text

        retried = client.post(
            "/v1/browser/web/open",
            headers=headers,
            json={
                "url": f"{base_url}/p11_safety_page.html",
                "safety": {"context_id": context_id, "step_up_id": step_up_id},
            },
        )
        assert retried.status_code == 200, retried.text
        retried_body = retried.json()
        assert retried_body["ok"] is True
        assert retried_body["state"]["url"] == f"{base_url}/p11_safety_page.html"
        states = client.get("/v1/visualizer/step-ups").json()["step_ups"]
        assert states[0]["status"] == "consumed"


def test_act_origin_step_up_extends_existing_context_after_manual_navigation(monkeypatch, tmp_path: Path):
    _require_managed_chromium()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    monkeypatch.setenv("WEBFA_PRIVATE_URL_POLICY", "allow")
    monkeypatch.delenv("WEBFA_BROWSER_DRIVER", raising=False)
    reset_engine_for_tests()

    agent_id = "act-origin-step-up-agent"
    headers = {"X-WebFA-Agent-Id": agent_id}
    with _serve_fixtures() as base_url, TestClient(create_app()) as client:
        _set_agent_owned_profile(client, agent_id)
        initial = client.post(
            "/v1/browser/web/open",
            headers=headers,
            json={
                "url": FIXTURE_PAGE.as_uri(),
                "safety": {
                    "declaration": {
                        "principal": {
                            "agent_id": agent_id,
                            "profile_id": "default",
                            "account_owner": "agent_owned",
                            "trust_mode": "trusted_agent",
                        },
                        "task": {"intent": "submit_agent_form", "subject": "validation"},
                        "dimensions": [
                            {
                                "type": "identity_context",
                                "account_owner": "agent_owned",
                                "action": "use_existing_account",
                            }
                        ],
                        "authorization_claim": {
                            "status": "explicit",
                            "source_ref": "user_turn_act_origin_scope",
                        },
                        "origin_scope": ["file://"],
                        "max_uses": 2,
                    },
                    "assertions": {
                        "assertions": {
                            "current_identity_matches_task": True,
                            "no_unapproved_identity_switch": True,
                        },
                        "authorization_source": "user_turn_act_origin_scope",
                    },
                },
            },
        )
        context_id = initial.json()["safety_decision"]["context_id"]
        navigated = client.post(
            "/v1/browser/web/open",
            headers=headers,
            json={"url": f"{base_url}/agent_validation_page.html"},
        )
        assert navigated.status_code == 200, navigated.text
        target = next(
            item
            for item in navigated.json()["state"]["objects"]
            if item.get("role") == "button" and item.get("name") == "Submit"
        )

        blocked = client.post(
            "/v1/browser/web/act",
            headers=headers,
            json={
                "target": target["id"],
                "operation": "activate",
                "arguments": {},
                "safety": {"context_id": context_id},
            },
        )
        assert blocked.status_code == 200, blocked.text
        blocked_body = blocked.json()
        assert blocked_body["ok"] is False
        assert blocked_body["safety_decision"]["decision"] == "require_step_up"
        step_up_id = blocked_body["data"]["step_up_id"]

        waiting = client.post(
            "/v1/browser/web/observe",
            headers=headers,
            json={
                "mode": "query",
                "query": {"text_contains": "Waiting"},
                "detail": "full",
                "limit": 10,
            },
        )
        assert waiting.json()["objects"]

        approved = client.post(
            f"/v1/visualizer/step-ups/{step_up_id}/approve",
            json={"decided_by": "test-user", "decision_note": "allow exact origin action"},
        )
        assert approved.status_code == 200, approved.text
        retried = client.post(
            "/v1/browser/web/act",
            headers=headers,
            json={
                "target": target["id"],
                "operation": "activate",
                "arguments": {},
                "safety": {"context_id": context_id, "step_up_id": step_up_id},
            },
        )
        assert retried.status_code == 200, retried.text
        assert retried.json()["ok"] is True
        assert retried.json()["safety_receipt"]["step_up_id"] == step_up_id
        states = client.get("/v1/visualizer/step-ups").json()["step_ups"]
        assert states[0]["status"] == "consumed"


def test_payment_instrument_broker_enforces_runtime_amount_and_completes_saved_method_flow(monkeypatch, tmp_path: Path):
    _require_managed_chromium()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    monkeypatch.setenv("WEBFA_PRIVATE_URL_POLICY", "allow")
    monkeypatch.delenv("WEBFA_BROWSER_DRIVER", raising=False)
    reset_engine_for_tests()

    agent_id = "shopping-agent"
    headers = {"X-WebFA-Agent-Id": agent_id}
    with _serve_fixtures() as base_url, TestClient(create_app()) as client:
        _set_agent_owned_profile(client, agent_id)
        policy = client.post(
            "/v1/visualizer/financial-policies",
            json={
                "policy_id": "policy-shopping",
                "currency": "CNY",
                "autonomy_limit": "300.00",
                "step_up_limit": "2000.00",
                "absolute_limit": "10000.00",
                "daily_limit": "1000.00",
                "monthly_limit": "3000.00",
                "subscriptions_allowed": False,
                "transfers_allowed": False,
                "cash_equivalents_allowed": False,
                "minimum_assurance": "runtime_observed",
            },
        )
        assert policy.status_code == 200, policy.text
        instrument = client.post(
            "/v1/visualizer/payment-instruments",
            json={
                "instrument_id": "pay-agent-01",
                "owner": "agent",
                "profile_id": "default",
                "type": "merchant_saved",
                "brand": "Visa",
                "last4": "4821",
                "currency": "CNY",
                "policy_id": "policy-shopping",
                "bound_agent_ids": [agent_id],
                "allowed_origins": [base_url],
                "display_name": "Agent Shopping Card",
            },
        )
        assert instrument.status_code == 200, instrument.text
        assert "4111111111111111" not in instrument.text
        assert "cvv" not in instrument.text.lower()

        opened = client.post(
            "/v1/browser/web/open",
            headers=headers,
            json={"url": f"{base_url}/p11_safety_page.html"},
        )
        assert opened.status_code == 200, opened.text

        observed = client.post(
            "/v1/browser/web/observe",
            headers=headers,
            json={
                "mode": "query",
                "query": {"capability": "provide_payment_instrument"},
                "detail": "full",
                "limit": 10,
            },
        )
        assert observed.status_code == 200, observed.text
        target = observed.json()["objects"][0]
        assert target["name"] == "Pay with Visa ending in 4821"
        assert target["capabilities"] == ["provide_payment_instrument"]

        paid = client.post(
            "/v1/browser/web/act",
            headers=headers,
            json={
                "target": target["id"],
                "operation": "provide_payment_instrument",
                "arguments": {
                    "instrument_id": "pay-agent-01",
                    "amount": "279.00",
                    "currency": "CNY",
                    "transaction_kind": "one_time_purchase",
                    "recurring": False,
                },
                "safety": {
                    "declaration": {
                        "principal": {
                            "agent_id": agent_id,
                            "profile_id": "default",
                            "account_owner": "agent_owned",
                            "trust_mode": "trusted_agent",
                        },
                        "task": {
                            "intent": "purchase_product",
                            "subject": "A product",
                        },
                        "dimensions": [
                            {
                                "type": "financial_commitment",
                                "kind": "one_time_purchase",
                                "currency": "CNY",
                                "estimated_amount": "279.00",
                                "maximum_amount": "300.00",
                                "merchant": "Fixture Shop",
                                "item_summary": "A product",
                                "quantity": 1,
                                "payment_instrument_ref": "pay-agent-01",
                            }
                        ],
                        "authorization_claim": {
                            "status": "explicit",
                            "source_ref": "user_turn_payment",
                        },
                        "origin_scope": [base_url],
                        "max_uses": 2,
                    },
                    "assertions": {
                        "assertions": {
                            "user_explicitly_authorized_purchase": True,
                            "user_explicitly_authorized_payment": True,
                            "actual_amount_within_authorized_scope": True,
                            "merchant_and_subject_match_task": True,
                            "no_unapproved_recurring_commitment": True,
                        },
                        "authorization_source": "user_turn_payment",
                    },
                },
            },
        )
        assert paid.status_code == 200, paid.text
        body = paid.json()
        assert body["ok"] is True
        assert body["safety_decision"]["decision"] == "allow_with_audit"
        assert body["data"]["payment_selection"] == {
            "amount": "279.00",
            "currency": "CNY",
            "transaction_kind": "one_time_purchase",
            "assurance": "runtime_observed",
            "committed": False,
        }
        assert body["data"]["payment_instrument"] == {
            "type": "merchant_saved",
            "brand": "Visa",
            "last4": "4821",
        }
        context_id = body["safety_decision"]["context_id"]
        assert body["safety_receipt"]["operation"] == "provide_payment_instrument"
        assert body["safety_receipt"]["authority_source"].startswith("sha256:")
        assert "user_turn_payment" not in paid.text
        assert "instrument_id" not in body["safety_receipt"]
        assert "card_number" not in paid.text.lower()

        usage_before_commit = client.get("/v1/visualizer/financial-policies/policy-shopping/usage")
        assert usage_before_commit.status_code == 200, usage_before_commit.text
        assert usage_before_commit.json()["usage"]["daily_spent"] == "0"

        commit_target_response = client.post(
            "/v1/browser/web/observe",
            headers=headers,
            json={
                "mode": "query",
                "query": {"text_contains": "Place order"},
                "detail": "full",
                "limit": 10,
            },
        )
        assert commit_target_response.status_code == 200, commit_target_response.text
        commit_target = next(
            item
            for item in commit_target_response.json()["objects"]
            if item.get("role") == "button" and item.get("name") == "Place order"
        )
        committed = client.post(
            "/v1/browser/web/act",
            headers=headers,
            json={
                "target": commit_target["id"],
                "operation": "activate",
                "arguments": {},
                "safety": {"context_id": context_id},
            },
        )
        assert committed.status_code == 200, committed.text
        committed_body = committed.json()
        assert committed_body["ok"] is True
        assert committed_body["data"]["financial_commitment"] == {
            "amount": "279.00",
            "currency": "CNY",
            "transaction_kind": "one_time_purchase",
            "assurance": "runtime_observed",
            "committed": True,
        }
        assert committed_body["data"]["financial_usage"]["daily_spent"] == "279.00"
        assert committed_body["safety_receipt"]["operation"] == "activate"

        result = client.post(
            "/v1/browser/web/observe",
            headers=headers,
            json={
                "mode": "query",
                "query": {"text_contains": "Payment completed with Visa ending in 4821"},
                "detail": "full",
                "limit": 10,
            },
        )
        assert result.status_code == 200, result.text
        assert result.json()["objects"]

        usage = client.get("/v1/visualizer/financial-policies/policy-shopping/usage")
        assert usage.status_code == 200, usage.text
        assert usage.json()["usage"]["daily_spent"] == "279.00"


def test_payment_step_up_ui_approval_is_exact_scope_single_use_and_audited(monkeypatch, tmp_path: Path):
    _require_managed_chromium()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    monkeypatch.setenv("WEBFA_PRIVATE_URL_POLICY", "allow")
    monkeypatch.delenv("WEBFA_BROWSER_DRIVER", raising=False)
    reset_engine_for_tests()

    agent_id = "step-up-shopping-agent"
    headers = {"X-WebFA-Agent-Id": agent_id}
    with _serve_fixtures() as base_url, TestClient(create_app()) as client:
        _set_agent_owned_profile(client, agent_id)
        assert client.post(
            "/v1/visualizer/financial-policies",
            json={
                "policy_id": "policy-step-up",
                "currency": "CNY",
                "autonomy_limit": "100.00",
                "step_up_limit": "500.00",
                "absolute_limit": "1000.00",
                "daily_limit": "1000.00",
                "monthly_limit": "3000.00",
                "subscriptions_allowed": False,
                "transfers_allowed": False,
                "cash_equivalents_allowed": False,
                "minimum_assurance": "runtime_observed",
            },
        ).status_code == 200
        assert client.post(
            "/v1/visualizer/payment-instruments",
            json={
                "instrument_id": "pay-step-up-01",
                "owner": "agent",
                "profile_id": "default",
                "type": "merchant_saved",
                "brand": "Visa",
                "last4": "4821",
                "currency": "CNY",
                "policy_id": "policy-step-up",
                "bound_agent_ids": [agent_id],
                "allowed_origins": [base_url],
                "display_name": "Step-up card",
            },
        ).status_code == 200

        opened = client.post(
            "/v1/browser/web/open",
            headers=headers,
            json={"url": f"{base_url}/p11_safety_page.html"},
        )
        assert opened.status_code == 200, opened.text
        observed = client.post(
            "/v1/browser/web/observe",
            headers=headers,
            json={
                "mode": "query",
                "query": {"capability": "provide_payment_instrument"},
                "detail": "full",
                "limit": 10,
            },
        )
        target = observed.json()["objects"][0]
        declaration = {
            "principal": {
                "agent_id": agent_id,
                "profile_id": "default",
                "account_owner": "agent_owned",
                "trust_mode": "trusted_agent",
            },
            "task": {"intent": "purchase_product", "subject": "A product"},
            "dimensions": [
                {
                    "type": "financial_commitment",
                    "kind": "one_time_purchase",
                    "currency": "CNY",
                    "estimated_amount": "279.00",
                    "maximum_amount": "300.00",
                    "merchant": "Fixture Shop",
                    "item_summary": "A product",
                    "quantity": 1,
                    "payment_instrument_ref": "pay-step-up-01",
                }
            ],
            "authorization_claim": {
                "status": "explicit",
                "source_ref": "user_turn_step_up_payment",
            },
            "origin_scope": [base_url],
            "max_uses": 2,
        }
        arguments = {
            "instrument_id": "pay-step-up-01",
            "amount": "279.00",
            "currency": "CNY",
            "transaction_kind": "one_time_purchase",
            "recurring": False,
        }
        first = client.post(
            "/v1/browser/web/act",
            headers=headers,
            json={
                "target": target["id"],
                "operation": "provide_payment_instrument",
                "arguments": arguments,
                "safety": {
                    "declaration": declaration,
                    "assertions": {
                        "assertions": {
                            "user_explicitly_authorized_purchase": True,
                            "user_explicitly_authorized_payment": True,
                            "actual_amount_within_authorized_scope": True,
                            "merchant_and_subject_match_task": True,
                            "no_unapproved_recurring_commitment": True,
                        },
                        "authorization_source": "user_turn_step_up_payment",
                    },
                },
            },
        )
        assert first.status_code == 200, first.text
        first_body = first.json()
        assert first_body["ok"] is True
        assert first_body["data"]["payment_selection"]["committed"] is False
        context_id = first_body["safety_decision"]["context_id"]
        usage_before_commit = client.get("/v1/visualizer/financial-policies/policy-step-up/usage")
        assert usage_before_commit.json()["usage"]["daily_spent"] == "0"

        commit_target_response = client.post(
            "/v1/browser/web/observe",
            headers=headers,
            json={
                "mode": "query",
                "query": {"text_contains": "Place order"},
                "detail": "full",
                "limit": 10,
            },
        )
        commit_target = next(
            item
            for item in commit_target_response.json()["objects"]
            if item.get("role") == "button" and item.get("name") == "Place order"
        )
        commit_attempt = client.post(
            "/v1/browser/web/act",
            headers=headers,
            json={
                "target": commit_target["id"],
                "operation": "activate",
                "arguments": {},
                "safety": {"context_id": context_id},
            },
        )
        assert commit_attempt.status_code == 200, commit_attempt.text
        commit_body = commit_attempt.json()
        assert commit_body["ok"] is False
        assert commit_body["safety_decision"]["decision"] == "require_step_up"
        step_up_id = commit_body["data"]["step_up_id"]
        assert commit_body["safety_receipt"]["step_up_id"] == step_up_id
        assert commit_body["safety_receipt"]["authority_source"].startswith("sha256:")
        assert "user_turn_step_up_payment" not in commit_attempt.text
        assert commit_body["safety_receipt"]["result"] == "not_executed"

        pending = client.get("/v1/visualizer/step-ups").json()["step_ups"]
        assert pending[0]["request"]["step_up_id"] == step_up_id
        assert pending[0]["request"]["operation"] == "activate"
        assert pending[0]["request"]["requested_scope"]["amount"] == "279.00"
        assert pending[0]["request"]["requested_scope"]["document_id"]
        assert pending[0]["request"]["requested_scope"]["object_version"] >= 1

        approved = client.post(
            f"/v1/visualizer/step-ups/{step_up_id}/approve",
            json={
                "decided_by": "test-user",
                "decision_note": "approve exact amount",
            },
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["step_up"]["status"] == "approved"

        retry = client.post(
            "/v1/browser/web/act",
            headers=headers,
            json={
                "target": commit_target["id"],
                "operation": "activate",
                "arguments": {},
                "safety": {
                    "context_id": context_id,
                    "step_up_id": step_up_id,
                },
            },
        )
        assert retry.status_code == 200, retry.text
        retry_body = retry.json()
        assert retry_body["ok"] is True
        assert retry_body["safety_decision"]["decision"] == "allow_with_audit"
        assert retry_body["data"]["financial_commitment"]["committed"] is True
        assert retry_body["data"]["financial_usage"]["daily_spent"] == "279.00"
        assert retry_body["safety_receipt"]["step_up_id"] == step_up_id
        assert retry_body["safety_receipt"]["result"] == "executed"

        step_up_state = client.get("/v1/visualizer/step-ups").json()["step_ups"][0]
        assert step_up_state["status"] == "consumed"
        receipts = client.get("/v1/visualizer/safety-receipts").json()["receipts"]
        assert any(item["step_up_id"] == step_up_id and item["result"] == "not_executed" for item in receipts)
        assert any(item["step_up_id"] == step_up_id and item["result"] == "executed" for item in receipts)
        serialized = str(receipts).lower()
        assert "4111111111111111" not in serialized
        assert "cvv" not in serialized


def test_one_click_payment_button_enforces_financial_policy_before_click(monkeypatch, tmp_path: Path):
    _require_managed_chromium()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    monkeypatch.setenv("WEBFA_PRIVATE_URL_POLICY", "allow")
    monkeypatch.delenv("WEBFA_BROWSER_DRIVER", raising=False)
    reset_engine_for_tests()

    agent_id = "one-click-payment-agent"
    headers = {"X-WebFA-Agent-Id": agent_id}
    with _serve_fixtures() as base_url, TestClient(create_app()) as client:
        _set_agent_owned_profile(client, agent_id)
        assert client.post(
            "/v1/visualizer/financial-policies",
            json={
                "policy_id": "policy-one-click",
                "currency": "CNY",
                "autonomy_limit": "100.00",
                "step_up_limit": "500.00",
                "absolute_limit": "1000.00",
                "minimum_assurance": "runtime_observed",
            },
        ).status_code == 200
        assert client.post(
            "/v1/visualizer/payment-instruments",
            json={
                "instrument_id": "pay-one-click",
                "owner": "agent",
                "profile_id": "default",
                "type": "merchant_saved",
                "brand": "Visa",
                "last4": "4821",
                "currency": "CNY",
                "policy_id": "policy-one-click",
                "bound_agent_ids": [agent_id],
                "allowed_origins": [base_url],
                "display_name": "One-click Visa",
            },
        ).status_code == 200
        opened = client.post(
            "/v1/browser/web/open",
            headers=headers,
            json={"url": f"{base_url}/p11_safety_page.html"},
        )
        assert opened.status_code == 200, opened.text
        observed = client.post(
            "/v1/browser/web/observe",
            headers=headers,
            json={
                "mode": "query",
                "query": {"text_contains": "Pay now with Visa ending in 4821"},
                "detail": "full",
                "limit": 10,
            },
        )
        target = next(
            item
            for item in observed.json()["objects"]
            if item.get("role") == "button"
            and item.get("name") == "Pay now with Visa ending in 4821"
        )
        attempted = client.post(
            "/v1/browser/web/act",
            headers=headers,
            json={
                "target": target["id"],
                "operation": "provide_payment_instrument",
                "arguments": {
                    "instrument_id": "pay-one-click",
                    "amount": "279.00",
                    "currency": "CNY",
                    "transaction_kind": "one_time_purchase",
                    "recurring": False,
                },
                "safety": {
                    "declaration": {
                        "principal": {
                            "agent_id": agent_id,
                            "profile_id": "default",
                            "account_owner": "agent_owned",
                            "trust_mode": "trusted_agent",
                        },
                        "task": {"intent": "one_click_purchase", "subject": "A product"},
                        "dimensions": [
                            {
                                "type": "financial_commitment",
                                "kind": "one_time_purchase",
                                "currency": "CNY",
                                "estimated_amount": "279.00",
                                "maximum_amount": "300.00",
                                "merchant": "Fixture Shop",
                                "item_summary": "A product",
                                "quantity": 1,
                                "payment_instrument_ref": "pay-one-click",
                            }
                        ],
                        "authorization_claim": {
                            "status": "explicit",
                            "source_ref": "user_turn_one_click_payment",
                        },
                        "origin_scope": [base_url],
                    },
                    "assertions": {
                        "assertions": {
                            "user_explicitly_authorized_purchase": True,
                            "user_explicitly_authorized_payment": True,
                            "actual_amount_within_authorized_scope": True,
                            "merchant_and_subject_match_task": True,
                            "no_unapproved_recurring_commitment": True,
                        },
                        "authorization_source": "user_turn_one_click_payment",
                    },
                },
            },
        )
        assert attempted.status_code == 200, attempted.text
        body = attempted.json()
        assert body["ok"] is False
        assert body["safety_decision"]["decision"] == "require_step_up"
        assert body["data"]["executed"] is False
        assert body["data"]["step_up_id"].startswith("stepup_")
        usage = client.get(
            "/v1/visualizer/financial-policies/policy-one-click/usage"
        ).json()["usage"]
        assert usage["daily_spent"] == "0"
        pending = client.post(
            "/v1/browser/web/observe",
            headers=headers,
            json={
                "mode": "query",
                "query": {"text_contains": "Payment pending"},
                "detail": "full",
                "limit": 10,
            },
        )
        assert pending.json()["objects"]


def test_final_payment_commit_cannot_bypass_profile_financial_policy(monkeypatch, tmp_path: Path):
    _require_managed_chromium()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    monkeypatch.setenv("WEBFA_PRIVATE_URL_POLICY", "allow")
    monkeypatch.delenv("WEBFA_BROWSER_DRIVER", raising=False)
    reset_engine_for_tests()

    agent_id = "default-payment-agent"
    headers = {"X-WebFA-Agent-Id": agent_id}
    with _serve_fixtures() as base_url, TestClient(create_app()) as client:
        policy = client.post(
            "/v1/visualizer/financial-policies",
            json={
                "policy_id": "policy-default-payment",
                "currency": "CNY",
                "autonomy_limit": "100.00",
                "step_up_limit": "500.00",
                "absolute_limit": "1000.00",
                "minimum_assurance": "runtime_observed",
            },
        )
        assert policy.status_code == 200, policy.text
        configured = client.put(
            "/v1/visualizer/profile-policy/default",
            json={
                "profile_id": "default",
                "owner": "agent_owned",
                "bound_agent_ids": [agent_id],
                "allowed_origins": [],
                "financial_policy_id": "policy-default-payment",
                "trust_mode": "trusted_agent",
                "unknown_external_effect_policy": "allow_with_audit",
            },
        )
        assert configured.status_code == 200, configured.text
        opened = client.post(
            "/v1/browser/web/open",
            headers=headers,
            json={"url": f"{base_url}/p11_safety_page.html"},
        )
        assert opened.status_code == 200, opened.text
        observed = client.post(
            "/v1/browser/web/observe",
            headers=headers,
            json={
                "mode": "query",
                "query": {"text_contains": "Place order"},
                "detail": "full",
                "limit": 10,
            },
        )
        target = next(
            item
            for item in observed.json()["objects"]
            if item.get("role") == "button" and item.get("name") == "Place order"
        )
        attempted = client.post(
            "/v1/browser/web/act",
            headers=headers,
            json={
                "target": target["id"],
                "operation": "activate",
                "arguments": {},
                "safety": {
                    "declaration": {
                        "principal": {
                            "agent_id": agent_id,
                            "profile_id": "default",
                            "account_owner": "agent_owned",
                            "trust_mode": "trusted_agent",
                        },
                        "task": {"intent": "purchase_product", "subject": "default payment"},
                        "dimensions": [
                            {
                                "type": "financial_commitment",
                                "kind": "one_time_purchase",
                                "currency": "CNY",
                                "estimated_amount": "279.00",
                                "maximum_amount": "300.00",
                                "merchant": "Fixture Shop",
                                "item_summary": "A product",
                                "quantity": 1,
                            }
                        ],
                        "authorization_claim": {
                            "status": "explicit",
                            "source_ref": "user_turn_default_payment",
                        },
                        "origin_scope": [base_url],
                    },
                    "assertions": {
                        "assertions": {
                            "user_explicitly_authorized_purchase": True,
                            "user_explicitly_authorized_payment": True,
                            "actual_amount_within_authorized_scope": True,
                            "merchant_and_subject_match_task": True,
                            "no_unapproved_recurring_commitment": True,
                        },
                        "authorization_source": "user_turn_default_payment",
                    },
                },
            },
        )
        assert attempted.status_code == 200, attempted.text
        body = attempted.json()
        assert body["ok"] is False
        assert body["safety_decision"]["decision"] == "require_step_up"
        assert body["data"]["executed"] is False
        assert body["data"]["step_up_id"].startswith("stepup_")
        usage = client.get(
            "/v1/visualizer/financial-policies/policy-default-payment/usage"
        ).json()["usage"]
        assert usage["daily_spent"] == "0"
        state = client.post(
            "/v1/browser/web/observe",
            headers=headers,
            json={
                "mode": "query",
                "query": {"text_contains": "Payment pending"},
                "detail": "full",
                "limit": 10,
            },
        )
        assert state.json()["objects"]


def test_openapi_exposes_p10_and_explicit_legacy_namespaces_only(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        paths = set(client.get("/openapi.json").json()["paths"])

    assert {
        "/v1/browser/web/open",
        "/v1/browser/web/observe",
        "/v1/browser/web/act",
        "/v1/browser/web/tabs/switch",
    }.issubset(paths)
    assert {
        "/v1/browser/legacy/open",
        "/v1/browser/legacy/observe",
        "/v1/browser/legacy/act",
        "/v1/browser/legacy/tabs/switch",
    }.issubset(paths)
    assert "/v1/browser/open" not in paths
    assert "/v1/browser/observe" not in paths
    assert "/v1/browser/act" not in paths
    assert "/v1/browser/tabs/switch" not in paths


def test_public_web_object_api_rejects_browser_primitives_and_selectors(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        primitive = client.post(
            "/v1/browser/web/act",
            json={"target": "obj_1", "operation": "click", "arguments": {}},
        )
        selector = client.post(
            "/v1/browser/web/observe",
            json={"mode": "query", "query": {"selector": "button"}},
        )

    assert primitive.status_code == 422
    assert selector.status_code == 422
    combined = f"{primitive.text} {selector.text}".lower()
    assert "playwright" not in combined
    assert "cdp" not in combined
