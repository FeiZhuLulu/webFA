from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from schemas.safety import (
    FinancialPolicy,
    PaymentInstrumentRef,
    ProfileOwnershipMetadata,
    SafetyDeclaration,
    SafetyOperationEnvelope,
)
from schemas.web import WebOpenRequest, WebOperationRequest, WebState


def _base_declaration() -> dict:
    return {
        "principal": {
            "agent_id": "shopping-agent",
            "profile_id": "profile-agent-shopping",
            "account_owner": "agent_owned",
        },
        "task": {"intent": "purchase_product", "subject": "A product"},
        "dimensions": [
            {
                "type": "identity_context",
                "account_owner": "agent_owned",
                "action": "use_existing_account",
            },
            {
                "type": "financial_commitment",
                "kind": "one_time_purchase",
                "currency": "cny",
                "maximum_amount": "300.00",
            },
        ],
        "authorization_claim": {
            "status": "explicit",
            "source_ref": "user_turn_42",
        },
        "expires_in_seconds": 3600,
    }


def test_safety_declaration_parses_discriminated_dimensions() -> None:
    declaration = SafetyDeclaration.model_validate(_base_declaration())

    assert declaration.dimensions[0].type == "identity_context"
    assert declaration.dimensions[1].type == "financial_commitment"
    assert declaration.dimensions[1].currency == "CNY"
    assert declaration.dimensions[1].maximum_amount == Decimal("300.00")
    assert declaration.principal.trust_mode == "trusted_agent"


def test_safety_schema_rejects_duplicate_dimensions_and_unknown_fields() -> None:
    payload = _base_declaration()
    payload["dimensions"].append(payload["dimensions"][0].copy())
    with pytest.raises(ValidationError, match="unique by type"):
        SafetyDeclaration.model_validate(payload)

    payload = _base_declaration()
    payload["secret"] = "not allowed"
    with pytest.raises(ValidationError):
        SafetyDeclaration.model_validate(payload)


def test_explicit_authorization_requires_source_reference() -> None:
    payload = _base_declaration()
    payload["authorization_claim"] = {"status": "explicit"}
    with pytest.raises(ValidationError, match="source_ref"):
        SafetyDeclaration.model_validate(payload)


def test_safety_operation_envelope_supports_reference_assert_and_fast_path() -> None:
    declaration = SafetyDeclaration.model_validate(_base_declaration())
    fast = SafetyOperationEnvelope(
        declaration=declaration,
        assertions={
            "assertions": {"user_explicitly_authorized_purchase": True},
            "authorization_source": "user_turn_42",
        },
    )
    assert fast.declaration is not None

    existing = SafetyOperationEnvelope(
        context_id="sctx_01",
        assertions={
            "assertions": {"actual_amount_within_authorized_scope": True},
            "authorization_source": "user_turn_42",
        },
    )
    assert existing.context_id == "sctx_01"

    with pytest.raises(ValidationError, match="context_id or declaration"):
        SafetyOperationEnvelope()


def test_financial_policy_validates_threshold_order_and_currency() -> None:
    policy = FinancialPolicy(
        policy_id="financial-01",
        currency="cny",
        autonomy_limit="300",
        step_up_limit="2000",
        absolute_limit="10000",
        daily_limit="1000",
        monthly_limit="3000",
    )
    assert policy.currency == "CNY"
    assert policy.subscriptions_allowed is False

    with pytest.raises(ValidationError, match="autonomy <= step_up <= absolute"):
        FinancialPolicy(
            policy_id="bad",
            currency="CNY",
            autonomy_limit="500",
            step_up_limit="100",
            absolute_limit="1000",
        )


def test_agent_owned_profile_defaults_unknown_effect_to_allow_with_audit() -> None:
    profile = ProfileOwnershipMetadata(
        profile_id="profile-agent",
        owner="agent_owned",
        bound_agent_ids=["agent-1"],
    )
    assert profile.trust_mode == "trusted_agent"
    assert profile.unknown_external_effect_policy == "allow_with_audit"


def test_payment_instrument_is_reference_only() -> None:
    instrument = PaymentInstrumentRef(
        instrument_id="pay_agent_01",
        owner="agent",
        profile_id="profile-agent",
        type="issuer_virtual_card",
        brand="visa",
        last4="4821",
        currency="CNY",
        policy_id="financial-01",
    )
    dumped = instrument.model_dump()
    assert dumped["last4"] == "4821"
    assert "pan" not in dumped
    assert "cvv" not in dumped

    with pytest.raises(ValidationError):
        PaymentInstrumentRef.model_validate({**dumped, "pan": "4111111111111111"})


def test_web_protocol_accepts_optional_safety_without_changing_default_shape() -> None:
    declaration = SafetyDeclaration.model_validate(_base_declaration())
    opened = WebOpenRequest(url="https://example.com", safety={"declaration": declaration})
    operation = WebOperationRequest(
        target="button_buy",
        operation="activate",
        expected_document_revision=3,
        safety={"context_id": "sctx_01"},
    )

    assert opened.safety is not None
    assert operation.safety is not None
    assert WebState().safety is None
