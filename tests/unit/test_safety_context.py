from __future__ import annotations

from datetime import datetime, timedelta, timezone

from browser.safety_context import SafetyContextManager
from schemas.safety import SafetyDeclaration, SafetyOperationEnvelope


def _declaration(*, trust_mode: str = "trusted_agent", max_uses: int = 1) -> SafetyDeclaration:
    return SafetyDeclaration.model_validate(
        {
            "principal": {
                "agent_id": "agent-1",
                "profile_id": "profile-1",
                "account_owner": "agent_owned",
                "trust_mode": trust_mode,
            },
            "task": {"intent": "purchase_product", "subject": "A product"},
            "dimensions": [
                {
                    "type": "financial_commitment",
                    "kind": "one_time_purchase",
                    "currency": "CNY",
                    "maximum_amount": "300",
                }
            ],
            "authorization_claim": {
                "status": "explicit",
                "source_ref": "user_turn_42",
            },
            "origin_scope": ["https://shop.example"],
            "expires_in_seconds": 60,
            "max_uses": max_uses,
        }
    )


def _all_assertions() -> dict:
    return {
        "user_explicitly_authorized_purchase": True,
        "user_explicitly_authorized_payment": True,
        "actual_amount_within_authorized_scope": True,
        "merchant_and_subject_match_task": True,
        "no_unapproved_recurring_commitment": True,
    }


def test_context_declare_assert_ready_and_consume() -> None:
    manager = SafetyContextManager()
    declared = manager.evaluate(
        SafetyOperationEnvelope(declaration=_declaration()),
        agent_id="agent-1",
        profile_id="profile-1",
        current_origin="https://shop.example",
    )

    assert declared.decision == "require_assertion"
    assert declared.status == "assertion_required"
    assert declared.context_id is not None

    ready = manager.evaluate(
        SafetyOperationEnvelope(
            context_id=declared.context_id,
            assertions={
                "assertions": _all_assertions(),
                "authorization_source": "user_turn_42",
            },
        ),
        agent_id="agent-1",
        profile_id="profile-1",
        current_origin="https://shop.example",
    )

    assert ready.decision == "allow_with_audit"
    assert ready.status == "ready"
    assert ready.state is not None
    assert ready.state.pending_assertions == []

    consumed = manager.consume(
        declared.context_id,
        agent_id="agent-1",
        profile_id="profile-1",
        current_origin="https://shop.example",
    )
    assert consumed is not None
    assert consumed.status == "consumed"
    assert consumed.remaining_uses == 0


def test_trusted_fast_path_accepts_declaration_and_assertions_together() -> None:
    manager = SafetyContextManager()
    result = manager.evaluate(
        SafetyOperationEnvelope(
            declaration=_declaration(max_uses=2),
            assertions={
                "assertions": _all_assertions(),
                "authorization_source": "user_turn_42",
            },
        ),
        agent_id="agent-1",
        profile_id="profile-1",
        current_origin="https://shop.example",
    )

    assert result.decision == "allow_with_audit"
    assert result.status == "ready"
    assert result.state is not None
    assert result.state.remaining_uses == 2


def test_origin_change_requires_step_up() -> None:
    manager = SafetyContextManager()
    declared = manager.evaluate(
        SafetyOperationEnvelope(declaration=_declaration()),
        agent_id="agent-1",
        profile_id="profile-1",
        current_origin="https://shop.example",
    )
    assert declared.context_id is not None

    result = manager.evaluate(
        SafetyOperationEnvelope(context_id=declared.context_id),
        agent_id="agent-1",
        profile_id="profile-1",
        current_origin="https://other.example",
    )

    assert result.decision == "require_step_up"
    assert result.status == "step_up_required"


def test_approved_origin_scope_extension_restores_context_readiness() -> None:
    manager = SafetyContextManager()
    ready = manager.evaluate(
        SafetyOperationEnvelope(
            declaration=_declaration(max_uses=2),
            assertions={
                "assertions": _all_assertions(),
                "authorization_source": "user_turn_42",
            },
        ),
        agent_id="agent-1",
        profile_id="profile-1",
        current_origin="https://shop.example",
    )
    assert ready.context_id is not None

    blocked = manager.evaluate(
        SafetyOperationEnvelope(context_id=ready.context_id),
        agent_id="agent-1",
        profile_id="profile-1",
        current_origin="https://other.example/path",
    )
    assert blocked.decision == "require_step_up"

    extended = manager.extend_origin_scope(
        ready.context_id,
        "https://other.example/path",
        agent_id="agent-1",
        profile_id="profile-1",
    )
    assert extended.decision == "allow_with_audit"
    assert extended.status == "ready"

    evaluated = manager.evaluate(
        SafetyOperationEnvelope(context_id=ready.context_id),
        agent_id="agent-1",
        profile_id="profile-1",
        current_origin="https://other.example",
    )
    assert evaluated.decision == "allow_with_audit"


def test_principal_mismatch_is_denied() -> None:
    manager = SafetyContextManager()
    result = manager.evaluate(
        SafetyOperationEnvelope(declaration=_declaration()),
        agent_id="other-agent",
        profile_id="profile-1",
        current_origin="https://shop.example",
    )

    assert result.decision == "deny"
    assert result.status == "blocked"
    assert result.context_id is None


def test_host_attested_mode_requires_attestation() -> None:
    manager = SafetyContextManager()
    declared = manager.evaluate(
        SafetyOperationEnvelope(declaration=_declaration(trust_mode="host_attested")),
        agent_id="agent-1",
        profile_id="profile-1",
        current_origin="https://shop.example",
    )
    assert declared.context_id is not None

    result = manager.evaluate(
        SafetyOperationEnvelope(
            context_id=declared.context_id,
            assertions={
                "assertions": _all_assertions(),
                "authorization_source": "user_turn_42",
            },
        ),
        agent_id="agent-1",
        profile_id="profile-1",
        current_origin="https://shop.example",
    )

    assert result.decision == "require_assertion"
    assert "host_attestation" in result.message


def test_expired_host_attestation_is_not_accepted() -> None:
    now = datetime(2026, 7, 11, 4, 0, tzinfo=timezone.utc)
    manager = SafetyContextManager(clock=lambda: now)
    declared = manager.evaluate(
        SafetyOperationEnvelope(declaration=_declaration(trust_mode="host_attested")),
        agent_id="agent-1",
        profile_id="profile-1",
        current_origin="https://shop.example",
    )
    assert declared.context_id is not None

    result = manager.evaluate(
        SafetyOperationEnvelope(
            context_id=declared.context_id,
            assertions={
                "assertions": _all_assertions(),
                "authorization_source": "user_turn_42",
                "host_attestation": {
                    "issuer": "agent-host",
                    "subject": "user_turn_42",
                    "issued_at": now - timedelta(minutes=10),
                    "expires_at": now - timedelta(minutes=1),
                },
            },
        ),
        agent_id="agent-1",
        profile_id="profile-1",
        current_origin="https://shop.example",
    )

    assert result.decision == "require_assertion"
    assert "host_attestation" in result.message


def test_context_expires_deterministically() -> None:
    now = datetime(2026, 7, 11, 4, 0, tzinfo=timezone.utc)
    clock_value = [now]
    manager = SafetyContextManager(clock=lambda: clock_value[0])
    declared = manager.evaluate(
        SafetyOperationEnvelope(declaration=_declaration()),
        agent_id="agent-1",
        profile_id="profile-1",
        current_origin="https://shop.example",
    )
    assert declared.context_id is not None

    clock_value[0] = now + timedelta(seconds=61)
    result = manager.evaluate(
        SafetyOperationEnvelope(context_id=declared.context_id),
        agent_id="agent-1",
        profile_id="profile-1",
        current_origin="https://shop.example",
    )

    assert result.status == "expired"
    assert result.decision == "deny"
