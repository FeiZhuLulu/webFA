from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from threading import RLock

from schemas.safety import (
    FinancialPolicy,
    FinancialUsageState,
    PaymentInstrumentRef,
    PaymentInstrumentState,
    SafetyAssuranceLevel,
    SafetyDecisionName,
    SafetyEvidenceItem,
    SafetyMismatch,
)


_ASSURANCE_ORDER: dict[SafetyAssuranceLevel, int] = {
    "agent_asserted": 0,
    "runtime_observed": 1,
    "provider_verified": 2,
    "user_confirmed": 3,
}
_SUPPORTED_BACKENDS = {"merchant_saved", "system_wallet", "tokenized_wallet"}


class PaymentInstrumentError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class FinancialAuthorization:
    decision: SafetyDecisionName
    status: str
    message: str
    policy: FinancialPolicy
    amount: Decimal
    currency: str
    transaction_kind: str
    assurance: SafetyAssuranceLevel
    evidence: tuple[SafetyEvidenceItem, ...] = ()
    mismatches: tuple[SafetyMismatch, ...] = ()
    authority_fingerprint: tuple[str, str, str, str, str] = (
        "default",
        "default",
        "default",
        "default",
        "default",
    )


@dataclass(frozen=True)
class PaymentAuthorization:
    decision: SafetyDecisionName
    status: str
    message: str
    instrument: PaymentInstrumentRef
    policy: FinancialPolicy
    amount: Decimal
    currency: str
    transaction_kind: str
    assurance: SafetyAssuranceLevel
    evidence: tuple[SafetyEvidenceItem, ...] = ()
    mismatches: tuple[SafetyMismatch, ...] = ()
    authority_fingerprint: tuple[str, str, str, str, str] = (
        "default",
        "default",
        "default",
        "default",
        "default",
    )


class PaymentInstrumentBroker:
    """Secret-free payment references plus deterministic financial policy.

    Selecting or providing an instrument is distinct from committing money.
    Instrument selection validates bindings and safe display evidence only.
    Financial limits and usage accounting are applied at the final semantic
    commit operation.
    """

    def __init__(
        self,
        *,
        profile_id: str | None = None,
        session_id: str = "default",
        runtime_generation: str = "default",
    ) -> None:
        self._profile_id = profile_id
        self._session_id = session_id
        self._runtime_generation = runtime_generation
        self._policies: dict[str, FinancialPolicy] = {}
        self._instruments: dict[str, PaymentInstrumentState] = {}
        self._usage: dict[str, list[tuple[datetime, Decimal]]] = {}
        self._lock = RLock()

    def register_policy(self, policy: FinancialPolicy) -> FinancialPolicy:
        with self._lock:
            self._policies[policy.policy_id] = policy.model_copy(deep=True)
            self._usage.setdefault(policy.policy_id, [])
            return self.get_policy(policy.policy_id)

    def get_policy(self, policy_id: str) -> FinancialPolicy:
        with self._lock:
            policy = self._policies.get(policy_id)
            if policy is None:
                raise PaymentInstrumentError("financial_policy_missing", "financial policy was not found")
            return policy.model_copy(deep=True)

    def list_policies(self) -> list[FinancialPolicy]:
        with self._lock:
            return [self.get_policy(policy_id) for policy_id in sorted(self._policies)]

    def register_instrument(self, instrument: PaymentInstrumentRef) -> PaymentInstrumentState:
        with self._lock:
            self.validate_instrument(instrument)
            state = PaymentInstrumentState(instrument=instrument.model_copy(deep=True))
            self._instruments[instrument.instrument_id] = state
            return state.model_copy(deep=True)

    def validate_instrument(self, instrument: PaymentInstrumentRef) -> PaymentInstrumentRef:
        """Validate a reference without creating or replacing broker state."""
        with self._lock:
            if self._profile_id is not None and instrument.profile_id != self._profile_id:
                raise PaymentInstrumentError(
                    "payment_profile_mismatch",
                    "payment instrument is bound to another Browser Profile",
                )
            if instrument.policy_id not in self._policies:
                raise PaymentInstrumentError(
                    "financial_policy_missing",
                    "payment instrument references an unknown financial policy",
                )
            if instrument.type == "local_protected_card":
                raise PaymentInstrumentError(
                    "payment_backend_unavailable",
                    "local protected card storage is not enabled in the P11 payment MVP",
                )
            return instrument.model_copy(deep=True)

    def get_instrument(self, instrument_id: str) -> PaymentInstrumentState:
        with self._lock:
            return self._require_instrument(instrument_id).model_copy(deep=True)

    def list_instruments(self) -> list[PaymentInstrumentState]:
        with self._lock:
            return [
                self._instruments[instrument_id].model_copy(deep=True)
                for instrument_id in sorted(self._instruments)
            ]

    def revoke_instrument(self, instrument_id: str) -> PaymentInstrumentState:
        with self._lock:
            state = self._require_instrument(instrument_id)
            revoked = state.model_copy(update={"status": "revoked"}, deep=True)
            self._instruments[instrument_id] = revoked
            return revoked.model_copy(deep=True)

    def authorize(
        self,
        *,
        instrument_id: str,
        agent_id: str,
        profile_id: str,
        origin: str,
        target_label: str | None,
        amount: Decimal,
        currency: str,
        transaction_kind: str,
        recurring: bool,
        assurance: SafetyAssuranceLevel,
        connection_id: str = "default",
        session_id: str = "default",
        runtime_generation: str = "default",
        enforce_financial_limits: bool = True,
    ) -> PaymentAuthorization:
        fingerprint = (agent_id, connection_id, profile_id, session_id, runtime_generation)
        if (
            (self._profile_id is not None and profile_id != self._profile_id)
            or session_id != self._session_id
            or runtime_generation != self._runtime_generation
        ):
            raise PaymentInstrumentError(
                "payment_runtime_binding_mismatch",
                "payment authorization is bound to another Browser Session generation",
            )
        with self._lock:
            state = self._require_instrument(instrument_id)
            instrument = state.instrument
            policy = self.get_policy(instrument.policy_id)
            evidence = (
                SafetyEvidenceItem(
                    code="payment:instrument_policy",
                    kind="payment_instrument",
                    source="browser_host",
                    assurance="provider_verified",
                    dimension="financial_commitment",
                    summary="WebFA validated the opaque payment instrument and its bindings",
                    origin=origin,
                    details={
                        "instrument_type": instrument.type,
                        "brand": instrument.brand,
                        "last4": instrument.last4,
                        "policy_id": policy.policy_id,
                    },
                ),
            )

            denied = self._validate_instrument_scope(
                state=state,
                agent_id=agent_id,
                profile_id=profile_id,
                origin=origin,
                target_label=target_label,
                amount=amount,
                currency=currency,
                transaction_kind=transaction_kind,
                assurance=assurance,
                evidence=evidence,
            )
            if denied is not None:
                return replace(denied, authority_fingerprint=fingerprint)

            if not enforce_financial_limits:
                return PaymentAuthorization(
                    decision="allow_with_audit",
                    status="ready",
                    message="Payment instrument bindings allow selection for the current transaction",
                    instrument=instrument.model_copy(deep=True),
                    policy=policy.model_copy(deep=True),
                    amount=amount,
                    currency=currency.upper(),
                    transaction_kind=transaction_kind,
                    assurance=assurance,
                    evidence=evidence,
                    authority_fingerprint=fingerprint,
                )

            financial = self._evaluate_policy(
                policy=policy,
                amount=amount,
                currency=currency,
                transaction_kind=transaction_kind,
                recurring=recurring,
                assurance=assurance,
                origin=origin,
                evidence=evidence,
            )
            return PaymentAuthorization(
                decision=financial.decision,
                status=financial.status,
                message=financial.message,
                instrument=instrument.model_copy(deep=True),
                policy=financial.policy,
                amount=financial.amount,
                currency=financial.currency,
                transaction_kind=financial.transaction_kind,
                assurance=financial.assurance,
                evidence=financial.evidence,
                mismatches=financial.mismatches,
                authority_fingerprint=fingerprint,
            )

    def authorize_policy(
        self,
        *,
        policy_id: str,
        amount: Decimal,
        currency: str,
        transaction_kind: str,
        recurring: bool,
        assurance: SafetyAssuranceLevel,
        origin: str,
        agent_id: str = "anonymous-mcp",
        connection_id: str = "default",
        profile_id: str = "default",
        session_id: str = "default",
        runtime_generation: str = "default",
    ) -> FinancialAuthorization:
        fingerprint = (agent_id, connection_id, profile_id, session_id, runtime_generation)
        if (
            (self._profile_id is not None and profile_id != self._profile_id)
            or session_id != self._session_id
            or runtime_generation != self._runtime_generation
        ):
            raise PaymentInstrumentError(
                "payment_runtime_binding_mismatch",
                "financial authorization is bound to another Browser Session generation",
            )
        with self._lock:
            policy = self.get_policy(policy_id)
            return replace(self._evaluate_policy(
                policy=policy,
                amount=amount,
                currency=currency,
                transaction_kind=transaction_kind,
                recurring=recurring,
                assurance=assurance,
                origin=origin,
                evidence=(),
            ), authority_fingerprint=fingerprint)

    def record_use(
        self,
        authorization: PaymentAuthorization | FinancialAuthorization,
        *,
        agent_id: str | None = None,
        connection_id: str | None = None,
        profile_id: str | None = None,
        session_id: str | None = None,
        runtime_generation: str | None = None,
    ) -> FinancialUsageState:
        if authorization.decision not in {"allow", "allow_with_audit"}:
            raise PaymentInstrumentError("payment_not_authorized", "cannot record a denied financial authorization")
        (
            bound_agent_id,
            bound_connection_id,
            bound_profile_id,
            bound_session_id,
            bound_runtime_generation,
        ) = authorization.authority_fingerprint
        supplied = (
            agent_id or bound_agent_id,
            connection_id or bound_connection_id,
            profile_id or bound_profile_id,
            session_id or bound_session_id,
            runtime_generation or bound_runtime_generation,
        )
        if supplied != authorization.authority_fingerprint:
            raise PaymentInstrumentError(
                "payment_authority_binding_mismatch",
                "financial authorization is bound to another Agent connection",
            )
        profile_id = bound_profile_id
        session_id = bound_session_id
        runtime_generation = bound_runtime_generation
        if (
            (self._profile_id is not None and profile_id != self._profile_id)
            or session_id != self._session_id
            or runtime_generation != self._runtime_generation
        ):
            raise PaymentInstrumentError(
                "payment_runtime_binding_mismatch",
                "financial authorization cannot be recorded outside its Browser Session generation",
            )
        with self._lock:
            now = datetime.now(timezone.utc)
            self._usage.setdefault(authorization.policy.policy_id, []).append((now, authorization.amount))
            daily, monthly = self._usage_totals(authorization.policy.policy_id, now=now)
            return FinancialUsageState(
                policy_id=authorization.policy.policy_id,
                currency=authorization.currency,
                daily_spent=daily,
                monthly_spent=monthly,
                updated_at=now,
            )

    def usage(self, policy_id: str) -> FinancialUsageState:
        policy = self.get_policy(policy_id)
        daily, monthly = self._usage_totals(policy_id)
        return FinancialUsageState(
            policy_id=policy_id,
            currency=policy.currency,
            daily_spent=daily,
            monthly_spent=monthly,
        )

    def _validate_instrument_scope(
        self,
        *,
        state: PaymentInstrumentState,
        agent_id: str,
        profile_id: str,
        origin: str,
        target_label: str | None,
        amount: Decimal,
        currency: str,
        transaction_kind: str,
        assurance: SafetyAssuranceLevel,
        evidence: tuple[SafetyEvidenceItem, ...],
    ) -> PaymentAuthorization | None:
        instrument = state.instrument
        policy = self.get_policy(instrument.policy_id)
        if state.status != "active":
            return _payment_deny("Payment instrument is revoked", instrument, policy, amount, currency, transaction_kind, assurance, evidence, "payment_instrument_scope_mismatch")
        if instrument.type not in _SUPPORTED_BACKENDS:
            return _payment_deny("Payment instrument backend is not available in the P11 payment MVP", instrument, policy, amount, currency, transaction_kind, assurance, evidence, "payment_instrument_scope_mismatch")
        if instrument.profile_id != profile_id:
            return _payment_deny("Payment instrument is bound to a different Browser Profile", instrument, policy, amount, currency, transaction_kind, assurance, evidence, "payment_instrument_scope_mismatch")
        if instrument.bound_agent_ids and agent_id not in instrument.bound_agent_ids:
            return _payment_deny("Active Agent is not bound to this payment instrument", instrument, policy, amount, currency, transaction_kind, assurance, evidence, "payment_instrument_scope_mismatch")
        if instrument.allowed_origins and origin not in instrument.allowed_origins:
            return _payment_deny("Current origin is outside the payment instrument scope", instrument, policy, amount, currency, transaction_kind, assurance, evidence, "payment_instrument_scope_mismatch")
        if currency.upper() != policy.currency or currency.upper() != instrument.currency:
            return _payment_deny("Payment currency does not match the instrument and financial policy", instrument, policy, amount, currency, transaction_kind, assurance, evidence, "financial_currency_mismatch")
        if target_label is not None and not _target_matches_instrument(target_label, instrument):
            return _payment_deny("Payment target does not match the selected payment instrument", instrument, policy, amount, currency, transaction_kind, assurance, evidence, "payment_instrument_scope_mismatch")
        return None

    def _evaluate_policy(
        self,
        *,
        policy: FinancialPolicy,
        amount: Decimal,
        currency: str,
        transaction_kind: str,
        recurring: bool,
        assurance: SafetyAssuranceLevel,
        origin: str,
        evidence: tuple[SafetyEvidenceItem, ...],
    ) -> FinancialAuthorization:
        policy_evidence = (
            *evidence,
            SafetyEvidenceItem(
                code="payment:financial_policy",
                kind="financial_policy",
                source="financial_policy",
                assurance="provider_verified",
                dimension="financial_commitment",
                summary="WebFA evaluated the configured financial policy for the final transaction commit",
                origin=origin,
                details={"policy_id": policy.policy_id, "currency": policy.currency},
            ),
        )
        normalized_currency = currency.upper()
        if normalized_currency != policy.currency:
            return _financial_deny("Payment currency does not match the financial policy", policy, amount, normalized_currency, transaction_kind, assurance, policy_evidence, "financial_currency_mismatch")
        if transaction_kind == "transfer" and not policy.transfers_allowed:
            return _financial_deny("Transfers are disabled by the financial policy", policy, amount, normalized_currency, transaction_kind, assurance, policy_evidence, "transaction_type_not_allowed")
        if transaction_kind == "cash_equivalent" and not policy.cash_equivalents_allowed:
            return _financial_deny("Cash-equivalent transactions are disabled by the financial policy", policy, amount, normalized_currency, transaction_kind, assurance, policy_evidence, "transaction_type_not_allowed")
        if recurring and not policy.subscriptions_allowed:
            return _financial_deny("Recurring commitments are disabled by the financial policy", policy, amount, normalized_currency, transaction_kind, assurance, policy_evidence, "recurring_commitment_not_allowed")
        if _ASSURANCE_ORDER[assurance] < _ASSURANCE_ORDER[policy.minimum_assurance]:
            return _financial_step_up("Observed payment assurance is below the financial policy requirement", policy, amount, normalized_currency, transaction_kind, assurance, policy_evidence, "assurance_below_policy")
        if amount > policy.absolute_limit:
            return _financial_deny("Payment amount exceeds the absolute financial limit", policy, amount, normalized_currency, transaction_kind, assurance, policy_evidence, "financial_limit_exceeded")

        daily_spent, monthly_spent = self._usage_totals(policy.policy_id)
        if policy.daily_limit is not None and daily_spent + amount > policy.daily_limit:
            return _financial_deny("Payment would exceed the daily financial limit", policy, amount, normalized_currency, transaction_kind, assurance, policy_evidence, "financial_limit_exceeded")
        if policy.monthly_limit is not None and monthly_spent + amount > policy.monthly_limit:
            return _financial_deny("Payment would exceed the monthly financial limit", policy, amount, normalized_currency, transaction_kind, assurance, policy_evidence, "financial_limit_exceeded")
        if amount > policy.autonomy_limit:
            message = (
                "Payment amount exceeds the autonomous limit and requires scope escalation"
                if amount <= policy.step_up_limit
                else "Payment amount exceeds the normal step-up limit and requires explicit policy escalation"
            )
            return _financial_step_up(message, policy, amount, normalized_currency, transaction_kind, assurance, policy_evidence, "financial_limit_exceeded")

        return FinancialAuthorization(
            decision="allow_with_audit",
            status="ready",
            message="Financial policy allows the final transaction commit",
            policy=policy.model_copy(deep=True),
            amount=amount,
            currency=normalized_currency,
            transaction_kind=transaction_kind,
            assurance=assurance,
            evidence=policy_evidence,
        )

    def _require_instrument(self, instrument_id: str) -> PaymentInstrumentState:
        state = self._instruments.get(instrument_id)
        if state is None:
            raise PaymentInstrumentError("payment_instrument_missing", "payment instrument was not found")
        return state

    def _usage_totals(self, policy_id: str, *, now: datetime | None = None) -> tuple[Decimal, Decimal]:
        current = now or datetime.now(timezone.utc)
        records = self._usage.get(policy_id, [])
        daily = Decimal("0")
        monthly = Decimal("0")
        retained: list[tuple[datetime, Decimal]] = []
        for timestamp, amount in records:
            if timestamp.year == current.year and timestamp.month == current.month:
                monthly += amount
                retained.append((timestamp, amount))
                if timestamp.date() == current.date():
                    daily += amount
        self._usage[policy_id] = retained
        return daily, monthly


def parse_amount(value: object) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise PaymentInstrumentError("invalid_payment_amount", "payment amount must be a decimal value") from exc
    if not amount.is_finite() or amount < 0:
        raise PaymentInstrumentError("invalid_payment_amount", "payment amount must be a finite non-negative value")
    return amount.quantize(Decimal("0.01"))


def _target_matches_instrument(label: str, instrument: PaymentInstrumentRef) -> bool:
    normalized = " ".join(label.lower().split())
    if instrument.last4 and instrument.last4 not in normalized:
        return False
    if instrument.brand and instrument.brand.lower() not in normalized and not instrument.last4:
        return False
    if instrument.display_name and instrument.display_name.lower() not in normalized and not instrument.last4:
        return False
    return True


def _payment_deny(
    message: str,
    instrument: PaymentInstrumentRef,
    policy: FinancialPolicy,
    amount: Decimal,
    currency: str,
    transaction_kind: str,
    assurance: SafetyAssuranceLevel,
    evidence: tuple[SafetyEvidenceItem, ...],
    code: str,
) -> PaymentAuthorization:
    return PaymentAuthorization(
        decision="deny",
        status="blocked",
        message=message,
        instrument=instrument.model_copy(deep=True),
        policy=policy.model_copy(deep=True),
        amount=amount,
        currency=currency.upper(),
        transaction_kind=transaction_kind,
        assurance=assurance,
        evidence=evidence,
        mismatches=(SafetyMismatch(code=code, severity="deny", message=message),),  # type: ignore[arg-type]
    )


def _financial_deny(
    message: str,
    policy: FinancialPolicy,
    amount: Decimal,
    currency: str,
    transaction_kind: str,
    assurance: SafetyAssuranceLevel,
    evidence: tuple[SafetyEvidenceItem, ...],
    code: str,
) -> FinancialAuthorization:
    return FinancialAuthorization(
        decision="deny",
        status="blocked",
        message=message,
        policy=policy.model_copy(deep=True),
        amount=amount,
        currency=currency.upper(),
        transaction_kind=transaction_kind,
        assurance=assurance,
        evidence=evidence,
        mismatches=(SafetyMismatch(code=code, severity="deny", message=message),),  # type: ignore[arg-type]
    )


def _financial_step_up(
    message: str,
    policy: FinancialPolicy,
    amount: Decimal,
    currency: str,
    transaction_kind: str,
    assurance: SafetyAssuranceLevel,
    evidence: tuple[SafetyEvidenceItem, ...],
    code: str,
) -> FinancialAuthorization:
    return FinancialAuthorization(
        decision="require_step_up",
        status="step_up_required",
        message=message,
        policy=policy.model_copy(deep=True),
        amount=amount,
        currency=currency.upper(),
        transaction_kind=transaction_kind,
        assurance=assurance,
        evidence=evidence,
        mismatches=(SafetyMismatch(code=code, severity="step_up", message=message),),  # type: ignore[arg-type]
    )
