from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


AccountOwner = Literal["agent_owned", "user_owned", "shared", "unknown"]
ResourceOwner = Literal["agent", "user", "shared"]
TrustMode = Literal["trusted_agent", "host_attested", "guarded"]
AuthorizationStatus = Literal["explicit", "implicit", "unknown", "not_granted"]
SafetyDimensionType = Literal[
    "identity_context",
    "financial_commitment",
    "local_data_egress",
    "external_representation",
    "destructive_change",
    "authority_change",
    "recurring_commitment",
    "unknown_external_effect",
]
SafetyContextStatus = Literal[
    "undeclared",
    "assertion_required",
    "ready",
    "step_up_required",
    "takeover_required",
    "blocked",
    "consumed",
    "expired",
]
SafetyDecisionName = Literal[
    "inform",
    "require_assertion",
    "allow",
    "allow_with_audit",
    "require_step_up",
    "require_takeover",
    "deny",
]
SafetyAssuranceLevel = Literal[
    "agent_asserted",
    "runtime_observed",
    "provider_verified",
    "user_confirmed",
]
UnknownEffectPolicy = Literal[
    "allow_with_audit",
    "require_assertion",
    "require_step_up",
    "deny",
]
SafetyAssertionKey = Literal[
    "current_identity_matches_task",
    "user_authorized_use_of_user_identity",
    "no_unapproved_identity_switch",
    "user_explicitly_authorized_financial_commitment",
    "user_explicitly_authorized_purchase",
    "user_explicitly_authorized_payment",
    "actual_amount_within_authorized_scope",
    "merchant_and_subject_match_task",
    "no_unapproved_recurring_commitment",
    "user_authorized_specific_resources",
    "user_authorized_destination",
    "resource_use_matches_task",
    "user_authorized_external_communication",
    "identity_and_audience_match_task",
    "content_or_subject_is_within_scope",
    "user_authorized_destructive_effect",
    "resource_matches_task",
    "recovery_expectation_is_understood",
    "user_authorized_authority_change",
    "new_principal_and_scope_match_task",
    "user_explicitly_authorized_recurring_commitment",
    "interval_and_amount_match_scope",
    "cancellation_terms_are_within_scope",
    "user_reviewed_unknown_external_effect",
]
HardBoundaryName = Literal[
    "credential_secrecy",
    "authentication_takeover",
    "payment_challenge_takeover",
    "profile_binding",
    "local_resource_grant",
    "financial_policy",
    "payment_instrument_policy",
    "recurring_commitment_policy",
    "explicit_deny_policy",
]
PaymentInstrumentType = Literal[
    "merchant_saved",
    "system_wallet",
    "tokenized_wallet",
    "issuer_virtual_card",
    "prepaid_card_reference",
    "local_protected_card",
]
P10EffectName = Literal[
    "read",
    "navigation",
    "local_state_change",
    "external_write",
    "external_send",
    "download",
    "upload",
    "destructive",
    "permission_change",
    "unknown",
]
SafetyEvidenceSource = Literal[
    "agent_declaration",
    "p10_capability",
    "web_object",
    "runtime_page",
    "browser_host",
    "resource_broker",
    "financial_policy",
]
SafetyEvidenceKind = Literal[
    "p10_effect",
    "external_mutation",
    "upload_target",
    "protected_credential",
    "authentication_surface",
    "captcha_surface",
    "payment_surface",
    "payment_challenge",
    "payment_instrument",
    "financial_amount",
    "recurring_commitment",
    "identity_surface",
    "identity_policy",
    "resource_grant",
    "financial_policy",
]
SafetyMismatchCode = Literal[
    "missing_declared_dimension",
    "declared_effect_below_runtime",
    "protected_operation_without_context",
    "assurance_below_policy",
    "resource_grant_missing",
    "resource_grant_scope_mismatch",
    "profile_binding_mismatch",
    "profile_owner_mismatch",
    "profile_trust_mode_mismatch",
    "identity_switch_requires_step_up",
    "unknown_effect_policy_violation",
    "payment_instrument_missing",
    "payment_instrument_scope_mismatch",
    "financial_amount_mismatch",
    "financial_limit_exceeded",
    "financial_currency_mismatch",
    "transaction_type_not_allowed",
    "recurring_commitment_not_allowed",
]
SafetyMismatchSeverity = Literal["audit", "assertion", "step_up", "takeover", "deny"]
SafetyEvidenceScalar = str | int | float | bool
StepUpScopeScalar = str | int | float | bool
StepUpStatus = Literal["pending", "approved", "rejected", "expired", "consumed"]
StepUpReason = Literal[
    "financial_limit",
    "financial_assurance",
    "identity_switch",
    "profile_scope",
    "unknown_external_effect",
    "policy_escalation",
]


class StrictSafetyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SafetyTaskRef(StrictSafetyModel):
    intent: str = Field(min_length=1, max_length=200)
    subject: str = Field(default="", max_length=500)


class SafetyPrincipalRef(StrictSafetyModel):
    agent_id: str = Field(min_length=1, max_length=200)
    profile_id: str = Field(min_length=1, max_length=200)
    account_owner: AccountOwner = "unknown"
    trust_mode: TrustMode = "trusted_agent"


class SafetyAuthorizationClaim(StrictSafetyModel):
    status: AuthorizationStatus
    source_ref: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_explicit_source(self) -> "SafetyAuthorizationClaim":
        if self.status == "explicit" and not self.source_ref:
            raise ValueError("explicit authorization requires source_ref")
        return self


class HostAttestation(StrictSafetyModel):
    issuer: str = Field(min_length=1, max_length=200)
    subject: str = Field(min_length=1, max_length=500)
    issued_at: datetime
    expires_at: datetime | None = None
    proof: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_window(self) -> "HostAttestation":
        if self.expires_at is not None and self.expires_at <= self.issued_at:
            raise ValueError("host attestation expires_at must be after issued_at")
        return self


class IdentityContextDimension(StrictSafetyModel):
    type: Literal["identity_context"] = "identity_context"
    account_owner: AccountOwner
    action: Literal[
        "use_existing_account",
        "sign_in",
        "switch_account",
        "create_account",
        "authorize_third_party",
    ]


class FinancialCommitmentDimension(StrictSafetyModel):
    type: Literal["financial_commitment"] = "financial_commitment"
    kind: Literal[
        "one_time_purchase",
        "transfer",
        "refund",
        "bid",
        "donation",
        "paid_service",
        "cash_equivalent",
        "unknown_financial_commitment",
    ]
    currency: str = Field(min_length=3, max_length=3)
    estimated_amount: Decimal | None = Field(default=None, ge=Decimal("0"))
    maximum_amount: Decimal | None = Field(default=None, ge=Decimal("0"))
    merchant: str = Field(default="", max_length=500)
    item_summary: str = Field(default="", max_length=1000)
    quantity: int | None = Field(default=None, ge=1, le=1_000_000)
    payment_instrument_ref: str | None = Field(default=None, max_length=300)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        normalized = value.upper()
        if not normalized.isalpha():
            raise ValueError("currency must be a three-letter alphabetic code")
        return normalized

    @model_validator(mode="after")
    def validate_amounts(self) -> "FinancialCommitmentDimension":
        if (
            self.estimated_amount is not None
            and self.maximum_amount is not None
            and self.estimated_amount > self.maximum_amount
        ):
            raise ValueError("estimated_amount cannot exceed maximum_amount")
        return self


class LocalDataEgressDimension(StrictSafetyModel):
    type: Literal["local_data_egress"] = "local_data_egress"
    source_owner: ResourceOwner
    resource_refs: list[str] = Field(min_length=1, max_length=100)
    destination_origin: str = Field(min_length=1, max_length=1000)
    purpose: str = Field(min_length=1, max_length=500)

    @field_validator("resource_refs")
    @classmethod
    def validate_resource_refs(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("resource_refs cannot contain empty values")
        if len(set(value)) != len(value):
            raise ValueError("resource_refs must be unique")
        return value


class ExternalRepresentationDimension(StrictSafetyModel):
    type: Literal["external_representation"] = "external_representation"
    kind: Literal[
        "email",
        "direct_message",
        "public_post",
        "comment",
        "application",
        "form_submission",
        "support_request",
        "legal_or_policy_acknowledgement",
    ]
    identity_owner: AccountOwner
    audience: str = Field(default="", max_length=500)
    subject: str = Field(default="", max_length=1000)


class DestructiveChangeDimension(StrictSafetyModel):
    type: Literal["destructive_change"] = "destructive_change"
    resource_owner: AccountOwner
    resource_ref: str = Field(min_length=1, max_length=500)
    reversible: bool
    recovery_window_seconds: int | None = Field(default=None, ge=0, le=31_536_000)


class AuthorityChangeDimension(StrictSafetyModel):
    type: Literal["authority_change"] = "authority_change"
    kind: Literal[
        "add_member",
        "change_role",
        "grant_admin",
        "create_credential",
        "authorize_application",
        "change_security_setting",
        "change_recovery_method",
        "make_public",
    ]
    principal: str = Field(default="", max_length=500)
    scope: str = Field(default="", max_length=1000)


class RecurringCommitmentDimension(StrictSafetyModel):
    type: Literal["recurring_commitment"] = "recurring_commitment"
    kind: Literal[
        "subscription",
        "automatic_renewal",
        "installment_plan",
        "recurring_donation",
        "recurring_service",
    ]
    interval: str = Field(min_length=1, max_length=200)
    currency: str = Field(min_length=3, max_length=3)
    amount_per_interval: Decimal | None = Field(default=None, ge=Decimal("0"))
    minimum_term: str = Field(default="", max_length=500)
    cancellation_terms_known: bool = False

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        normalized = value.upper()
        if not normalized.isalpha():
            raise ValueError("currency must be a three-letter alphabetic code")
        return normalized


class UnknownExternalEffectDimension(StrictSafetyModel):
    type: Literal["unknown_external_effect"] = "unknown_external_effect"
    summary: str = Field(default="", max_length=1000)


SafetyDimension = Annotated[
    IdentityContextDimension
    | FinancialCommitmentDimension
    | LocalDataEgressDimension
    | ExternalRepresentationDimension
    | DestructiveChangeDimension
    | AuthorityChangeDimension
    | RecurringCommitmentDimension
    | UnknownExternalEffectDimension,
    Field(discriminator="type"),
]


class SafetyDeclaration(StrictSafetyModel):
    principal: SafetyPrincipalRef
    task: SafetyTaskRef
    dimensions: list[SafetyDimension] = Field(min_length=1, max_length=8)
    authorization_claim: SafetyAuthorizationClaim
    origin_scope: list[str] = Field(default_factory=list, max_length=100)
    expires_at: datetime | None = None
    expires_in_seconds: int | None = Field(default=None, ge=1, le=86_400)
    max_uses: int = Field(default=1, ge=1, le=10_000)

    @model_validator(mode="after")
    def validate_shape(self) -> "SafetyDeclaration":
        dimension_types = [dimension.type for dimension in self.dimensions]
        if len(set(dimension_types)) != len(dimension_types):
            raise ValueError("safety dimensions must be unique by type")
        if self.expires_at is not None and self.expires_in_seconds is not None:
            raise ValueError("use either expires_at or expires_in_seconds, not both")
        return self


class SafetyAssertionSet(StrictSafetyModel):
    assertions: dict[SafetyAssertionKey, bool] = Field(min_length=1, max_length=100)
    authorization_source: str = Field(min_length=1, max_length=500)
    host_attestation: HostAttestation | None = None


class SafetyOperationEnvelope(StrictSafetyModel):
    context_id: str | None = Field(default=None, min_length=1, max_length=200)
    declaration: SafetyDeclaration | None = None
    assertions: SafetyAssertionSet | None = None
    step_up_id: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_shape(self) -> "SafetyOperationEnvelope":
        if self.context_id is None and self.declaration is None:
            raise ValueError("safety envelope requires context_id or declaration")
        if self.context_id is not None and self.declaration is not None:
            raise ValueError("safety envelope cannot contain both context_id and declaration")
        if self.assertions is not None and self.context_id is None and self.declaration is None:
            raise ValueError("assertions require context_id or declaration")
        return self


class SafetyEvidenceItem(StrictSafetyModel):
    code: str = Field(min_length=1, max_length=200)
    kind: SafetyEvidenceKind
    source: SafetyEvidenceSource
    assurance: SafetyAssuranceLevel = "runtime_observed"
    dimension: SafetyDimensionType | None = None
    summary: str = Field(default="", max_length=1000)
    object_id: str | None = Field(default=None, max_length=200)
    origin: str = Field(default="", max_length=1000)
    details: dict[str, SafetyEvidenceScalar] = Field(default_factory=dict, max_length=50)


class SafetyMismatch(StrictSafetyModel):
    code: SafetyMismatchCode
    severity: SafetyMismatchSeverity
    message: str = Field(min_length=1, max_length=1000)
    declared_dimension: SafetyDimensionType | None = None
    observed_dimension: SafetyDimensionType | None = None
    evidence_codes: list[str] = Field(default_factory=list, max_length=100)


class SafetyEvidenceReport(StrictSafetyModel):
    p10_effect: P10EffectName = "unknown"
    observed_dimensions: list[SafetyDimensionType] = Field(default_factory=list)
    minimum_assurance: SafetyAssuranceLevel = "agent_asserted"
    items: list[SafetyEvidenceItem] = Field(default_factory=list, max_length=100)
    mismatches: list[SafetyMismatch] = Field(default_factory=list, max_length=100)


class SafetyContract(StrictSafetyModel):
    context_id: str = Field(min_length=1, max_length=200)
    status: SafetyContextStatus
    template_versions: list[str] = Field(default_factory=list)
    active_dimensions: list[SafetyDimensionType] = Field(default_factory=list)
    required_assertions: list[SafetyAssertionKey] = Field(default_factory=list)
    instruction: str = ""
    hard_boundaries: list[HardBoundaryName] = Field(default_factory=list)


class SafetyContextState(StrictSafetyModel):
    context_id: str = Field(min_length=1, max_length=200)
    principal: SafetyPrincipalRef
    active_dimensions: list[SafetyDimensionType]
    observed_dimensions: list[SafetyDimensionType] = Field(default_factory=list)
    status: SafetyContextStatus
    pending_assertions: list[SafetyAssertionKey] = Field(default_factory=list)
    evidence: list[SafetyEvidenceItem] = Field(default_factory=list)
    mismatches: list[SafetyMismatch] = Field(default_factory=list)
    minimum_assurance: SafetyAssuranceLevel = "agent_asserted"
    expires_at: datetime
    remaining_uses: int = Field(ge=0)
    last_decision: SafetyDecisionName = "inform"


class StepUpRequest(StrictSafetyModel):
    step_up_id: str = Field(min_length=1, max_length=200)
    reason: StepUpReason
    context_id: str | None = Field(default=None, max_length=200)
    agent_id: str = Field(min_length=1, max_length=200)
    profile_id: str = Field(min_length=1, max_length=200)
    origin: str = Field(default="", max_length=1000)
    target_object_id: str = Field(min_length=1, max_length=200)
    operation: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=1000)
    current_scope: dict[str, StepUpScopeScalar] = Field(default_factory=dict, max_length=50)
    requested_scope: dict[str, StepUpScopeScalar] = Field(default_factory=dict, max_length=50)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime


class StepUpRequestState(StrictSafetyModel):
    request: StepUpRequest
    status: StepUpStatus = "pending"
    approved_scope: dict[str, StepUpScopeScalar] = Field(default_factory=dict, max_length=50)
    decided_by: str | None = Field(default=None, max_length=200)
    decision_note: str = Field(default="", max_length=1000)
    decided_at: datetime | None = None
    remaining_uses: int = Field(default=1, ge=0, le=100)


class SafetyDecision(StrictSafetyModel):
    decision: SafetyDecisionName
    status: SafetyContextStatus
    context_id: str | None = None
    message: str = ""
    contract: SafetyContract | None = None
    state: SafetyContextState | None = None
    evidence_report: SafetyEvidenceReport | None = None
    step_up: StepUpRequestState | None = None


class SafetyReceipt(StrictSafetyModel):
    receipt_id: str = Field(min_length=1, max_length=200)
    context_id: str = Field(min_length=1, max_length=200)
    agent_id: str = Field(min_length=1, max_length=200)
    profile_id: str = Field(min_length=1, max_length=200)
    origin: str = ""
    target_object_id: str = ""
    operation: str = Field(min_length=1, max_length=200)
    p10_effect: P10EffectName = "unknown"
    safety_dimensions: list[SafetyDimensionType] = Field(default_factory=list)
    assertion_refs: list[str] = Field(default_factory=list)
    hard_boundary_decision: SafetyDecisionName = "allow"
    final_decision: SafetyDecisionName
    before_revision: int = Field(default=0, ge=0)
    after_revision: int = Field(default=0, ge=0)
    result: Literal["executed", "not_executed", "takeover", "denied", "failed"]
    message: str = Field(default="", max_length=1000)
    authority_source: str | None = Field(default=None, max_length=500)
    step_up_id: str | None = Field(default=None, max_length=200)
    metadata: dict[str, StepUpScopeScalar] = Field(default_factory=dict, max_length=50)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_revision_order(self) -> "SafetyReceipt":
        if self.after_revision < self.before_revision:
            raise ValueError("after_revision cannot be smaller than before_revision")
        return self


class ProfileOwnershipMetadata(StrictSafetyModel):
    profile_id: str = Field(min_length=1, max_length=200)
    owner: AccountOwner
    bound_agent_ids: list[str] = Field(default_factory=list, max_length=100)
    allowed_origins: list[str] = Field(default_factory=list, max_length=100)
    safety_policy_id: str | None = Field(default=None, max_length=200)
    financial_policy_id: str | None = Field(default=None, max_length=200)
    trust_mode: TrustMode = "trusted_agent"
    unknown_external_effect_policy: UnknownEffectPolicy | None = None

    @model_validator(mode="after")
    def apply_unknown_effect_default(self) -> "ProfileOwnershipMetadata":
        if self.unknown_external_effect_policy is None:
            self.unknown_external_effect_policy = (
                "allow_with_audit" if self.owner == "agent_owned" else "require_step_up"
            )
        return self


class FinancialPolicy(StrictSafetyModel):
    policy_id: str = Field(min_length=1, max_length=200)
    currency: str = Field(min_length=3, max_length=3)
    autonomy_limit: Decimal = Field(ge=Decimal("0"))
    step_up_limit: Decimal = Field(ge=Decimal("0"))
    absolute_limit: Decimal = Field(ge=Decimal("0"))
    daily_limit: Decimal | None = Field(default=None, ge=Decimal("0"))
    monthly_limit: Decimal | None = Field(default=None, ge=Decimal("0"))
    subscriptions_allowed: bool = False
    transfers_allowed: bool = False
    cash_equivalents_allowed: bool = False
    minimum_assurance: SafetyAssuranceLevel = "agent_asserted"

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        normalized = value.upper()
        if not normalized.isalpha():
            raise ValueError("currency must be a three-letter alphabetic code")
        return normalized

    @model_validator(mode="after")
    def validate_limits(self) -> "FinancialPolicy":
        if not self.autonomy_limit <= self.step_up_limit <= self.absolute_limit:
            raise ValueError("financial limits must satisfy autonomy <= step_up <= absolute")
        if (
            self.daily_limit is not None
            and self.monthly_limit is not None
            and self.daily_limit > self.monthly_limit
        ):
            raise ValueError("daily_limit cannot exceed monthly_limit")
        return self


class PaymentInstrumentRef(StrictSafetyModel):
    instrument_id: str = Field(min_length=1, max_length=200)
    owner: ResourceOwner
    profile_id: str = Field(min_length=1, max_length=200)
    type: PaymentInstrumentType
    brand: str = Field(default="", max_length=100)
    last4: str = Field(default="", max_length=4)
    currency: str = Field(min_length=3, max_length=3)
    policy_id: str = Field(min_length=1, max_length=200)
    bound_agent_ids: list[str] = Field(default_factory=list, max_length=100)
    allowed_origins: list[str] = Field(default_factory=list, max_length=100)
    display_name: str = Field(default="", max_length=300)

    @field_validator("last4")
    @classmethod
    def validate_last4(cls, value: str) -> str:
        if value and (len(value) != 4 or not value.isdigit()):
            raise ValueError("last4 must contain exactly four digits")
        return value

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        normalized = value.upper()
        if not normalized.isalpha():
            raise ValueError("currency must be a three-letter alphabetic code")
        return normalized

    @field_validator("bound_agent_ids", "allowed_origins")
    @classmethod
    def validate_unique_values(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("binding and origin lists cannot contain empty values")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("binding and origin lists must contain unique values")
        return cleaned


class PaymentInstrumentState(StrictSafetyModel):
    instrument: PaymentInstrumentRef
    status: Literal["active", "revoked"] = "active"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FinancialUsageState(StrictSafetyModel):
    policy_id: str = Field(min_length=1, max_length=200)
    currency: str = Field(min_length=3, max_length=3)
    daily_spent: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    monthly_spent: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class LocalResourceGrant(StrictSafetyModel):
    resource_ref: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=500)
    owner: ResourceOwner
    purpose: str = Field(min_length=1, max_length=500)
    allowed_origins: list[str] = Field(min_length=1, max_length=100)
    bound_agent_ids: list[str] = Field(default_factory=list, max_length=100)
    bound_profile_ids: list[str] = Field(default_factory=list, max_length=100)
    expires_at: datetime | None = None
    max_uses: int = Field(default=1, ge=1, le=10_000)

    @field_validator("allowed_origins")
    @classmethod
    def validate_origins(cls, value: list[str]) -> list[str]:
        if any(not origin.strip() for origin in value):
            raise ValueError("allowed_origins cannot contain empty values")
        if len(set(value)) != len(value):
            raise ValueError("allowed_origins must be unique")
        return value


class LocalResourceGrantState(StrictSafetyModel):
    grant: LocalResourceGrant
    status: Literal["active", "consumed", "expired", "revoked"] = "active"
    remaining_uses: int = Field(ge=0)
    size_bytes: int = Field(ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
