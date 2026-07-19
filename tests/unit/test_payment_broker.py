from decimal import Decimal

import pytest

from browser.payment_broker import PaymentInstrumentBroker, PaymentInstrumentError
from schemas.safety import FinancialPolicy, PaymentInstrumentRef


def _broker() -> PaymentInstrumentBroker:
    broker = PaymentInstrumentBroker()
    broker.register_policy(
        FinancialPolicy(
            policy_id="policy-shopping",
            currency="CNY",
            autonomy_limit=Decimal("300"),
            step_up_limit=Decimal("2000"),
            absolute_limit=Decimal("10000"),
            daily_limit=Decimal("1000"),
            monthly_limit=Decimal("3000"),
            subscriptions_allowed=False,
            transfers_allowed=False,
            cash_equivalents_allowed=False,
            minimum_assurance="runtime_observed",
        )
    )
    broker.register_instrument(
        PaymentInstrumentRef(
            instrument_id="pay-agent-01",
            owner="agent",
            profile_id="default",
            type="merchant_saved",
            brand="Visa",
            last4="4821",
            currency="CNY",
            policy_id="policy-shopping",
            bound_agent_ids=["shopping-agent"],
            allowed_origins=["https://shop.example"],
            display_name="Agent Shopping Card",
        )
    )
    return broker


def _authorize(
    broker: PaymentInstrumentBroker,
    *,
    amount: str = "279.00",
    recurring: bool = False,
    assurance: str = "runtime_observed",
    label: str = "Pay with Visa ending in 4821",
    kind: str = "one_time_purchase",
):
    return broker.authorize(
        instrument_id="pay-agent-01",
        agent_id="shopping-agent",
        profile_id="default",
        origin="https://shop.example",
        target_label=label,
        amount=Decimal(amount),
        currency="CNY",
        transaction_kind=kind,
        recurring=recurring,
        assurance=assurance,
    )


def test_low_value_merchant_saved_payment_is_allowed_and_recorded():
    broker = _broker()

    authorization = _authorize(broker)
    usage = broker.record_use(authorization)

    assert authorization.decision == "allow_with_audit"
    assert authorization.instrument.last4 == "4821"
    assert usage.daily_spent == Decimal("279.00")
    assert usage.monthly_spent == Decimal("279.00")


def test_payment_selection_validates_instrument_without_consuming_financial_scope():
    broker = _broker()

    selection = broker.authorize(
        instrument_id="pay-agent-01",
        agent_id="shopping-agent",
        profile_id="default",
        origin="https://shop.example",
        target_label="Pay with Visa ending in 4821",
        amount=Decimal("800.00"),
        currency="CNY",
        transaction_kind="one_time_purchase",
        recurring=False,
        assurance="runtime_observed",
        enforce_financial_limits=False,
    )

    assert selection.decision == "allow_with_audit"
    assert broker.usage("policy-shopping").daily_spent == Decimal("0")


def test_amount_and_assurance_boundaries_return_step_up_or_deny():
    broker = _broker()

    above_autonomy = _authorize(broker, amount="800.00")
    below_assurance = _authorize(broker, assurance="agent_asserted")
    above_absolute = _authorize(broker, amount="12000.00")

    assert above_autonomy.decision == "require_step_up"
    assert below_assurance.decision == "require_step_up"
    assert above_absolute.decision == "deny"


def test_subscription_transfer_target_and_origin_boundaries_are_enforced():
    broker = _broker()

    recurring = _authorize(broker, recurring=True)
    transfer = _authorize(broker, kind="transfer")
    wrong_target = _authorize(broker, label="Pay with Visa ending in 9999")
    wrong_origin = broker.authorize(
        instrument_id="pay-agent-01",
        agent_id="shopping-agent",
        profile_id="default",
        origin="https://other.example",
        target_label="Pay with Visa ending in 4821",
        amount=Decimal("10.00"),
        currency="CNY",
        transaction_kind="one_time_purchase",
        recurring=False,
        assurance="runtime_observed",
    )

    assert recurring.decision == "deny"
    assert recurring.mismatches[0].code == "recurring_commitment_not_allowed"
    assert transfer.decision == "deny"
    assert transfer.mismatches[0].code == "transaction_type_not_allowed"
    assert wrong_target.decision == "deny"
    assert wrong_origin.decision == "deny"


def test_tokenized_wallet_backend_uses_opaque_reference_without_wallet_token():
    broker = PaymentInstrumentBroker()
    broker.register_policy(
        FinancialPolicy(
            policy_id="wallet-policy",
            currency="USD",
            autonomy_limit=Decimal("100"),
            step_up_limit=Decimal("500"),
            absolute_limit=Decimal("1000"),
            minimum_assurance="runtime_observed",
        )
    )
    broker.register_instrument(
        PaymentInstrumentRef(
            instrument_id="wallet-agent-01",
            owner="agent",
            profile_id="default",
            type="tokenized_wallet",
            brand="Google Pay",
            currency="USD",
            policy_id="wallet-policy",
            bound_agent_ids=["shopping-agent"],
            allowed_origins=["https://shop.example"],
            display_name="Google Pay",
        )
    )

    authorization = broker.authorize(
        instrument_id="wallet-agent-01",
        agent_id="shopping-agent",
        profile_id="default",
        origin="https://shop.example",
        target_label="Pay with Google Pay",
        amount=Decimal("25.00"),
        currency="USD",
        transaction_kind="one_time_purchase",
        recurring=False,
        assurance="runtime_observed",
    )

    assert authorization.decision == "allow_with_audit"
    assert authorization.instrument.type == "tokenized_wallet"
    assert "token" not in PaymentInstrumentRef.model_fields
    assert "wallet_token" not in PaymentInstrumentRef.model_fields


def test_local_card_vault_is_not_enabled_and_secrets_are_not_schema_fields():
    broker = PaymentInstrumentBroker()
    broker.register_policy(
        FinancialPolicy(
            policy_id="policy",
            currency="USD",
            autonomy_limit=Decimal("10"),
            step_up_limit=Decimal("20"),
            absolute_limit=Decimal("30"),
        )
    )

    with pytest.raises(PaymentInstrumentError) as raised:
        broker.register_instrument(
            PaymentInstrumentRef(
                instrument_id="local-card",
                owner="user",
                profile_id="default",
                type="local_protected_card",
                brand="Visa",
                last4="1234",
                currency="USD",
                policy_id="policy",
            )
        )

    assert raised.value.code == "payment_backend_unavailable"
    assert "pan" not in PaymentInstrumentRef.model_fields
    assert "cvv" not in PaymentInstrumentRef.model_fields
    assert "card_number" not in PaymentInstrumentRef.model_fields


def test_instrument_preflight_is_side_effect_free():
    broker = _broker()
    candidate = PaymentInstrumentRef(
        instrument_id="pay-agent-02",
        owner="agent",
        profile_id="default",
        type="merchant_saved",
        brand="Visa",
        last4="9912",
        currency="CNY",
        policy_id="policy-shopping",
    )

    validated = broker.validate_instrument(candidate)

    assert validated == candidate
    assert [item.instrument.instrument_id for item in broker.list_instruments()] == [
        "pay-agent-01"
    ]
