from __future__ import annotations

from decimal import Decimal

import pytest

from browser.local_resource_broker import LocalResourceBroker, LocalResourceError
from browser.payment_broker import PaymentInstrumentBroker, PaymentInstrumentError
from browser.safety_audit import SafetyReceiptStore
from browser.safety_context import SafetyContextManager
from browser.step_up import StepUpError, StepUpManager
from schemas.safety import (
    FinancialPolicy,
    PaymentInstrumentRef,
    SafetyDeclaration,
    SafetyOperationEnvelope,
    SafetyReceipt,
)


def _declaration() -> SafetyDeclaration:
    return SafetyDeclaration.model_validate(
        {
            "principal": {
                "agent_id": "agent-a",
                "profile_id": "profile-a",
                "account_owner": "agent_owned",
                "trust_mode": "trusted_agent",
            },
            "task": {"intent": "purchase_product", "subject": "A product"},
            "dimensions": [
                {
                    "type": "financial_commitment",
                    "kind": "one_time_purchase",
                    "currency": "CNY",
                    "maximum_amount": "100",
                }
            ],
            "authorization_claim": {
                "status": "explicit",
                "source_ref": "user_turn_1",
            },
            "origin_scope": ["https://shop.example"],
            "expires_in_seconds": 300,
            "max_uses": 2,
        }
    )


def _assertions() -> dict[str, bool]:
    return {
        "user_explicitly_authorized_purchase": True,
        "user_explicitly_authorized_payment": True,
        "actual_amount_within_authorized_scope": True,
        "merchant_and_subject_match_task": True,
        "no_unapproved_recurring_commitment": True,
    }


def test_safety_context_rejects_other_connection_without_poisoning_owner() -> None:
    manager = SafetyContextManager(
        profile_id="profile-a",
        session_id="session-a",
        runtime_generation="generation-a",
    )
    ready = manager.evaluate(
        SafetyOperationEnvelope(
            declaration=_declaration(),
            assertions={
                "assertions": _assertions(),
                "authorization_source": "user_turn_1",
            },
        ),
        agent_id="agent-a",
        profile_id="profile-a",
        current_origin="https://shop.example",
        connection_id="conn-a",
    )
    assert ready.context_id is not None
    assert ready.state is not None
    assert ready.state.session_id == "session-a"
    assert ready.state.runtime_generation == "generation-a"

    denied = manager.evaluate(
        SafetyOperationEnvelope(context_id=ready.context_id),
        agent_id="agent-a",
        profile_id="profile-a",
        current_origin="https://shop.example",
        connection_id="conn-b",
    )
    assert denied.decision == "deny"
    assert denied.state is None

    owner = manager.evaluate(
        SafetyOperationEnvelope(context_id=ready.context_id),
        agent_id="agent-a",
        profile_id="profile-a",
        current_origin="https://shop.example",
        connection_id="conn-a",
    )
    assert owner.decision == "allow_with_audit"
    assert owner.status == "ready"


def test_step_up_is_connection_document_and_generation_bound() -> None:
    manager = StepUpManager(
        profile_id="profile-a",
        session_id="session-a",
        runtime_generation="generation-a",
    )
    pending = manager.request(
        reason="financial_limit",
        context_id="ctx-a",
        agent_id="agent-a",
        profile_id="profile-a",
        connection_id="conn-a",
        origin="https://shop.example",
        document_id="doc-a",
        target_object_id="obj-a",
        operation="activate",
        message="approval required",
        requested_scope={"amount": "100"},
    )
    manager.approve(pending.request.step_up_id)

    with pytest.raises(StepUpError) as wrong_connection:
        manager.authorize(
            pending.request.step_up_id,
            context_id="ctx-a",
            agent_id="agent-a",
            profile_id="profile-a",
            connection_id="conn-b",
            origin="https://shop.example",
            document_id="doc-a",
            target_object_id="obj-a",
            operation="activate",
            requested_scope={"amount": "100"},
        )
    assert wrong_connection.value.code == "step_up_binding_mismatch"

    with pytest.raises(StepUpError) as wrong_document:
        manager.authorize(
            pending.request.step_up_id,
            context_id="ctx-a",
            agent_id="agent-a",
            profile_id="profile-a",
            connection_id="conn-a",
            origin="https://shop.example",
            document_id="doc-b",
            target_object_id="obj-a",
            operation="activate",
            requested_scope={"amount": "100"},
        )
    assert wrong_document.value.code == "step_up_binding_mismatch"

    authorized = manager.authorize(
        pending.request.step_up_id,
        context_id="ctx-a",
        agent_id="agent-a",
        profile_id="profile-a",
        connection_id="conn-a",
        origin="https://shop.example",
        document_id="doc-a",
        target_object_id="obj-a",
        operation="activate",
        requested_scope={"amount": "100"},
    )
    assert authorized.status == "approved"
    with pytest.raises(StepUpError):
        manager.consume(pending.request.step_up_id, connection_id="conn-b")
    assert manager.consume(pending.request.step_up_id, connection_id="conn-a").status == "consumed"


def test_local_resource_invalid_caller_cannot_claim_connection_binding(tmp_path) -> None:
    broker = LocalResourceBroker(
        resource_dir=tmp_path / "resources",
        profile_id="profile-a",
        session_id="session-a",
        runtime_generation="generation-a",
    )
    state = broker.register_bytes(
        display_name="upload.txt",
        content=b"payload",
        owner="user",
        purpose="support",
        allowed_origins=["https://support.example"],
        bound_agent_ids=["agent-a"],
        bound_profile_ids=["profile-a"],
    )

    with pytest.raises(LocalResourceError) as invalid_agent:
        broker.authorize(
            state.grant.resource_ref,
            agent_id="agent-b",
            profile_id="profile-a",
            connection_id="conn-b",
            session_id="session-a",
            runtime_generation="generation-a",
            origin="https://support.example",
            purpose="support",
        )
    assert invalid_agent.value.code == "resource_agent_mismatch"

    broker.authorize(
        state.grant.resource_ref,
        agent_id="agent-a",
        profile_id="profile-a",
        connection_id="conn-a",
        session_id="session-a",
        runtime_generation="generation-a",
        origin="https://support.example",
        purpose="support",
    )
    with pytest.raises(LocalResourceError) as replay:
        broker.authorize(
            state.grant.resource_ref,
            agent_id="agent-a",
            profile_id="profile-a",
            connection_id="conn-b",
            session_id="session-a",
            runtime_generation="generation-a",
            origin="https://support.example",
            purpose="support",
        )
    assert replay.value.code == "resource_connection_mismatch"


def _payment_broker(*, generation: str) -> PaymentInstrumentBroker:
    broker = PaymentInstrumentBroker(
        profile_id="profile-a",
        session_id="session-a",
        runtime_generation=generation,
    )
    broker.register_policy(
        FinancialPolicy(
            policy_id="policy-a",
            currency="CNY",
            autonomy_limit=Decimal("100"),
            step_up_limit=Decimal("500"),
            absolute_limit=Decimal("1000"),
            minimum_assurance="runtime_observed",
        )
    )
    broker.register_instrument(
        PaymentInstrumentRef(
            instrument_id="instrument-a",
            owner="user",
            profile_id="profile-a",
            type="merchant_saved",
            brand="Visa",
            last4="1234",
            currency="CNY",
            policy_id="policy-a",
            bound_agent_ids=["agent-a"],
            allowed_origins=["https://shop.example"],
        )
    )
    return broker


def test_payment_authorization_cannot_be_recorded_in_new_generation() -> None:
    old = _payment_broker(generation="generation-a")
    authorization = old.authorize(
        instrument_id="instrument-a",
        agent_id="agent-a",
        connection_id="conn-a",
        profile_id="profile-a",
        session_id="session-a",
        runtime_generation="generation-a",
        origin="https://shop.example",
        target_label="Visa ending in 1234",
        amount=Decimal("10"),
        currency="CNY",
        transaction_kind="one_time_purchase",
        recurring=False,
        assurance="runtime_observed",
    )
    with pytest.raises(PaymentInstrumentError) as wrong_connection:
        old.record_use(
            authorization,
            agent_id="agent-a",
            connection_id="conn-b",
            profile_id="profile-a",
            session_id="session-a",
            runtime_generation="generation-a",
        )
    assert wrong_connection.value.code == "payment_authority_binding_mismatch"

    replacement = _payment_broker(generation="generation-b")
    with pytest.raises(PaymentInstrumentError) as replay:
        replacement.record_use(authorization)
    assert replay.value.code == "payment_runtime_binding_mismatch"


def test_safety_receipt_store_rejects_wrong_generation() -> None:
    store = SafetyReceiptStore(
        profile_id="profile-a",
        session_id="session-a",
        runtime_generation="generation-a",
    )
    receipt = SafetyReceipt(
        receipt_id="receipt-a",
        context_id="ctx-a",
        agent_id="agent-a",
        profile_id="profile-a",
        session_id="session-a",
        runtime_generation="generation-b",
        origin="https://shop.example",
        document_id="doc-a",
        target_object_id="obj-a",
        operation="activate",
        final_decision="allow_with_audit",
        result="executed",
    )
    with pytest.raises(ValueError, match="another Browser Session generation"):
        store.append(receipt, connection_id="conn-a")
