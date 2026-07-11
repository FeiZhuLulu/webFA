from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Callable
from urllib.parse import urlparse
from uuid import uuid4

from browser.safety_templates import SafetyContractCompiler
from schemas.safety import (
    SafetyAssertionKey,
    SafetyAssertionSet,
    SafetyContextState,
    SafetyContract,
    SafetyDecision,
    SafetyDeclaration,
    SafetyDimensionType,
    SafetyEvidenceItem,
    SafetyEvidenceReport,
    SafetyMismatch,
    SafetyOperationEnvelope,
)


Clock = Callable[[], datetime]


@dataclass
class _ManagedSafetyContext:
    declaration: SafetyDeclaration
    contract: SafetyContract
    expires_at: datetime
    remaining_uses: int
    origin_scope: tuple[str, ...]
    assertions: dict[SafetyAssertionKey, bool] = field(default_factory=dict)
    authorization_source: str | None = None
    status: str = "assertion_required"
    last_decision: str = "inform"
    observed_dimensions: list[SafetyDimensionType] = field(default_factory=list)
    evidence: list[SafetyEvidenceItem] = field(default_factory=list)
    mismatches: list[SafetyMismatch] = field(default_factory=list)
    minimum_assurance: str = "agent_asserted"


class SafetyContextManager:
    """Session-local safety handshake and lifecycle manager.

    It does not interpret conversation text or webpage business meaning. It only
    compiles declared dimensions, records Agent assertions, and enforces binding,
    expiry, and use-count invariants.
    """

    def __init__(
        self,
        compiler: SafetyContractCompiler | None = None,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._compiler = compiler or SafetyContractCompiler()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._contexts: dict[str, _ManagedSafetyContext] = {}
        self._active_by_principal: dict[tuple[str, str], str] = {}
        self._lock = RLock()

    def evaluate(
        self,
        envelope: SafetyOperationEnvelope,
        *,
        agent_id: str,
        profile_id: str,
        current_origin: str,
        locale: str = "zh-CN",
    ) -> SafetyDecision:
        with self._lock:
            if envelope.declaration is not None:
                decision = self._declare(
                    envelope.declaration,
                    agent_id=agent_id,
                    profile_id=profile_id,
                    current_origin=current_origin,
                    locale=locale,
                )
                if envelope.assertions is not None and decision.context_id is not None:
                    return self._assert(
                        decision.context_id,
                        envelope.assertions,
                        agent_id=agent_id,
                        profile_id=profile_id,
                        current_origin=current_origin,
                    )
                return decision

            assert envelope.context_id is not None
            if envelope.assertions is not None:
                return self._assert(
                    envelope.context_id,
                    envelope.assertions,
                    agent_id=agent_id,
                    profile_id=profile_id,
                    current_origin=current_origin,
                )
            return self._evaluate_existing(
                envelope.context_id,
                agent_id=agent_id,
                profile_id=profile_id,
                current_origin=current_origin,
            )

    def current_state(
        self,
        *,
        agent_id: str,
        profile_id: str,
        current_origin: str,
    ) -> SafetyContextState | None:
        with self._lock:
            context_id = self._active_by_principal.get((agent_id, profile_id))
            if context_id is None:
                return None
            managed = self._contexts.get(context_id)
            if managed is None:
                return None
            self._refresh_lifecycle(managed)
            binding = self._binding_decision(
                managed,
                agent_id=agent_id,
                profile_id=profile_id,
                current_origin=current_origin,
            )
            if binding is not None:
                return binding.state
            return self._state(managed)

    def apply_evidence(
        self,
        context_id: str,
        report: SafetyEvidenceReport,
        *,
        agent_id: str,
        profile_id: str,
        current_origin: str,
        locale: str = "zh-CN",
    ) -> SafetyDecision:
        with self._lock:
            managed = self._contexts.get(context_id)
            if managed is None:
                return SafetyDecision(
                    decision="deny",
                    status="blocked",
                    context_id=context_id,
                    message="safety context was not found",
                    evidence_report=report,
                )
            self._refresh_lifecycle(managed)
            binding = self._binding_decision(
                managed,
                agent_id=agent_id,
                profile_id=profile_id,
                current_origin=current_origin,
            )
            if binding is not None:
                return binding.model_copy(update={"evidence_report": report})
            if managed.status in {"expired", "consumed", "blocked", "step_up_required", "takeover_required"}:
                return self._decision_for_status(managed).model_copy(update={"evidence_report": report})

            declared = {dimension.type for dimension in managed.declaration.dimensions}
            existing_observed = set(managed.observed_dimensions)
            for dimension in report.observed_dimensions:
                if dimension not in existing_observed:
                    managed.observed_dimensions.append(dimension)
                    existing_observed.add(dimension)

            existing_codes = {item.code for item in managed.evidence}
            for item in report.items:
                if item.code not in existing_codes:
                    managed.evidence.append(item)
                    existing_codes.add(item.code)

            mismatch_keys = {
                (item.code, item.observed_dimension)
                for item in managed.mismatches
            }
            for dimension in report.observed_dimensions:
                if dimension in declared:
                    continue
                severity = self._mismatch_severity(managed, dimension)
                key = ("missing_declared_dimension", dimension)
                if key in mismatch_keys:
                    continue
                evidence_codes = [
                    item.code
                    for item in report.items
                    if item.dimension == dimension
                ]
                managed.mismatches.append(
                    SafetyMismatch(
                        code="missing_declared_dimension",
                        severity=severity,
                        message=f"Runtime observed undeclared safety dimension: {dimension}",
                        observed_dimension=dimension,
                        evidence_codes=evidence_codes,
                    )
                )
                mismatch_keys.add(key)

            managed.minimum_assurance = _max_assurance(
                managed.minimum_assurance,
                report.minimum_assurance,
            )
            managed.contract = self._compiler.extend_with_observed_dimensions(
                managed.contract,
                managed.declaration,
                managed.observed_dimensions,
                locale=locale,
            )
            pending = self._pending_assertions(managed)
            if pending:
                managed.status = "assertion_required"
                managed.last_decision = "require_assertion"
            else:
                managed.status = "ready"
                managed.last_decision = "allow_with_audit"

            merged_report = SafetyEvidenceReport(
                p10_effect=report.p10_effect,
                observed_dimensions=list(managed.observed_dimensions),
                minimum_assurance=managed.minimum_assurance,  # type: ignore[arg-type]
                items=list(managed.evidence),
                mismatches=list(managed.mismatches),
            )
            return SafetyDecision(
                decision=managed.last_decision,
                status=managed.status,
                context_id=context_id,
                message=self._message_for(managed),
                contract=managed.contract.model_copy(update={"status": managed.status}),
                state=self._state(managed),
                evidence_report=merged_report,
            )

    def declaration_for(self, context_id: str) -> SafetyDeclaration | None:
        with self._lock:
            managed = self._contexts.get(context_id)
            return managed.declaration.model_copy(deep=True) if managed is not None else None

    def extend_origin_scope(
        self,
        context_id: str,
        origin: str,
        *,
        agent_id: str,
        profile_id: str,
    ) -> SafetyDecision:
        with self._lock:
            managed = self._contexts.get(context_id)
            if managed is None:
                return SafetyDecision(
                    decision="deny",
                    status="blocked",
                    context_id=context_id,
                    message="safety context was not found",
                )
            self._refresh_lifecycle(managed)
            principal = managed.declaration.principal
            if principal.agent_id != agent_id or principal.profile_id != profile_id:
                managed.status = "blocked"
                managed.last_decision = "deny"
                return self._decision_for_status(
                    managed,
                    message="safety context principal binding does not match the active Agent or profile",
                )
            if managed.status in {"expired", "consumed", "blocked", "takeover_required"}:
                return self._decision_for_status(managed)
            normalized = _normalize_origin(origin)
            if not normalized:
                return SafetyDecision(
                    decision="deny",
                    status="blocked",
                    context_id=context_id,
                    message="origin scope extension requires a valid origin",
                    contract=managed.contract.model_copy(update={"status": managed.status}),
                    state=self._state(managed),
                )
            if normalized not in managed.origin_scope:
                managed.origin_scope = (*managed.origin_scope, normalized)
            pending = self._pending_assertions(managed)
            managed.status = "assertion_required" if pending else "ready"
            managed.last_decision = "require_assertion" if pending else "allow_with_audit"
            return self._decision_for_status(
                managed,
                message="approved origin scope extension applied to the safety context",
            )

    def consume(
        self,
        context_id: str,
        *,
        agent_id: str,
        profile_id: str,
        current_origin: str,
    ) -> SafetyContextState | None:
        with self._lock:
            managed = self._contexts.get(context_id)
            if managed is None:
                return None
            self._refresh_lifecycle(managed)
            binding = self._binding_decision(
                managed,
                agent_id=agent_id,
                profile_id=profile_id,
                current_origin=current_origin,
            )
            if binding is not None:
                return binding.state
            if managed.status != "ready":
                return self._state(managed)
            managed.remaining_uses = max(0, managed.remaining_uses - 1)
            if managed.remaining_uses == 0:
                managed.status = "consumed"
            managed.last_decision = "allow_with_audit"
            return self._state(managed)

    def get_contract(self, context_id: str) -> SafetyContract | None:
        with self._lock:
            managed = self._contexts.get(context_id)
            if managed is None:
                return None
            self._refresh_lifecycle(managed)
            return managed.contract.model_copy(update={"status": managed.status})

    def _declare(
        self,
        declaration: SafetyDeclaration,
        *,
        agent_id: str,
        profile_id: str,
        current_origin: str,
        locale: str,
    ) -> SafetyDecision:
        if declaration.principal.agent_id != agent_id:
            return SafetyDecision(
                decision="deny",
                status="blocked",
                message="safety declaration agent_id does not match the active Agent",
            )
        if declaration.principal.profile_id != profile_id:
            return SafetyDecision(
                decision="deny",
                status="blocked",
                message="safety declaration profile_id does not match the active profile",
            )

        context_id = f"sctx_{uuid4().hex}"
        expires_at = self._resolve_expiry(declaration)
        origin_scope = tuple(
            dict.fromkeys(
                normalized
                for value in (declaration.origin_scope or ([current_origin] if current_origin else []))
                if (normalized := _normalize_origin(value))
            )
        )
        contract = self._compiler.compile(
            declaration,
            context_id=context_id,
            locale=locale,
        )
        status = contract.status
        decision_name = "require_assertion" if status == "assertion_required" else "allow_with_audit"

        if declaration.authorization_claim.status == "not_granted":
            status = "blocked"
            decision_name = "deny"

        managed = _ManagedSafetyContext(
            declaration=declaration,
            contract=contract,
            expires_at=expires_at,
            remaining_uses=declaration.max_uses,
            origin_scope=origin_scope,
            status=status,
            last_decision=decision_name,
        )
        self._contexts[context_id] = managed
        self._active_by_principal[(agent_id, profile_id)] = context_id
        self._refresh_lifecycle(managed)
        status = managed.status
        decision_name = self._decision_name_for_status(status)
        managed.last_decision = decision_name

        return SafetyDecision(
            decision=decision_name,
            status=status,
            context_id=context_id,
            message=self._message_for(managed),
            contract=contract.model_copy(update={"status": status}),
            state=self._state(managed),
        )

    def _assert(
        self,
        context_id: str,
        assertion_set: SafetyAssertionSet,
        *,
        agent_id: str,
        profile_id: str,
        current_origin: str,
    ) -> SafetyDecision:
        managed = self._contexts.get(context_id)
        if managed is None:
            return SafetyDecision(
                decision="deny",
                status="blocked",
                context_id=context_id,
                message="safety context was not found",
            )
        self._refresh_lifecycle(managed)
        binding = self._binding_decision(
            managed,
            agent_id=agent_id,
            profile_id=profile_id,
            current_origin=current_origin,
        )
        if binding is not None:
            return binding
        if managed.status in {"expired", "consumed", "blocked", "step_up_required", "takeover_required"}:
            return self._decision_for_status(managed)

        if managed.declaration.principal.trust_mode == "host_attested" and (
            assertion_set.host_attestation is None
            or (
                assertion_set.host_attestation.expires_at is not None
                and _as_utc(assertion_set.host_attestation.expires_at) <= self._now()
            )
        ):
            managed.status = "assertion_required"
            managed.last_decision = "require_assertion"
            return SafetyDecision(
                decision="require_assertion",
                status=managed.status,
                context_id=context_id,
                message="host_attested mode requires host_attestation",
                contract=managed.contract.model_copy(update={"status": managed.status}),
                state=self._state(managed),
            )

        managed.assertions.update(assertion_set.assertions)
        managed.authorization_source = assertion_set.authorization_source
        pending = self._pending_assertions(managed)
        if pending:
            managed.status = "assertion_required"
            managed.last_decision = "require_assertion"
        else:
            managed.status = "ready"
            managed.last_decision = "allow_with_audit"

        return SafetyDecision(
            decision=managed.last_decision,
            status=managed.status,
            context_id=context_id,
            message=self._message_for(managed),
            contract=managed.contract.model_copy(update={"status": managed.status}),
            state=self._state(managed),
        )

    def _evaluate_existing(
        self,
        context_id: str,
        *,
        agent_id: str,
        profile_id: str,
        current_origin: str,
    ) -> SafetyDecision:
        managed = self._contexts.get(context_id)
        if managed is None:
            return SafetyDecision(
                decision="deny",
                status="blocked",
                context_id=context_id,
                message="safety context was not found",
            )
        self._refresh_lifecycle(managed)
        binding = self._binding_decision(
            managed,
            agent_id=agent_id,
            profile_id=profile_id,
            current_origin=current_origin,
        )
        if binding is not None:
            return binding
        return self._decision_for_status(managed)

    def _binding_decision(
        self,
        managed: _ManagedSafetyContext,
        *,
        agent_id: str,
        profile_id: str,
        current_origin: str,
    ) -> SafetyDecision | None:
        principal = managed.declaration.principal
        if principal.agent_id != agent_id or principal.profile_id != profile_id:
            managed.status = "blocked"
            managed.last_decision = "deny"
            return self._decision_for_status(
                managed,
                message="safety context principal binding does not match the active Agent or profile",
            )
        if managed.origin_scope and current_origin not in managed.origin_scope:
            managed.status = "step_up_required"
            managed.last_decision = "require_step_up"
            return self._decision_for_status(
                managed,
                message="current origin is outside the safety context origin scope",
            )
        return None

    def _refresh_lifecycle(self, managed: _ManagedSafetyContext) -> None:
        if managed.status in {"consumed", "expired"}:
            return
        if self._now() >= managed.expires_at:
            managed.status = "expired"
            managed.last_decision = "deny"
        elif managed.remaining_uses <= 0:
            managed.status = "consumed"
            managed.last_decision = "deny"

    def _decision_for_status(
        self,
        managed: _ManagedSafetyContext,
        *,
        message: str | None = None,
    ) -> SafetyDecision:
        decision_name = self._decision_name_for_status(managed.status)
        managed.last_decision = decision_name
        return SafetyDecision(
            decision=decision_name,
            status=managed.status,
            context_id=managed.contract.context_id,
            message=message or self._message_for(managed),
            contract=managed.contract.model_copy(update={"status": managed.status}),
            state=self._state(managed),
        )

    @staticmethod
    def _decision_name_for_status(status: str) -> str:
        mapping = {
            "assertion_required": "require_assertion",
            "ready": "allow_with_audit",
            "step_up_required": "require_step_up",
            "takeover_required": "require_takeover",
            "blocked": "deny",
            "consumed": "deny",
            "expired": "deny",
            "undeclared": "inform",
        }
        return mapping[status]

    def _state(self, managed: _ManagedSafetyContext) -> SafetyContextState:
        return SafetyContextState(
            context_id=managed.contract.context_id,
            principal=managed.declaration.principal,
            active_dimensions=managed.contract.active_dimensions,
            observed_dimensions=list(managed.observed_dimensions),
            status=managed.status,
            pending_assertions=self._pending_assertions(managed),
            evidence=list(managed.evidence),
            mismatches=list(managed.mismatches),
            minimum_assurance=managed.minimum_assurance,  # type: ignore[arg-type]
            expires_at=managed.expires_at,
            remaining_uses=managed.remaining_uses,
            last_decision=managed.last_decision,
        )

    @staticmethod
    def _mismatch_severity(
        managed: _ManagedSafetyContext,
        dimension: SafetyDimensionType,
    ) -> str:
        principal = managed.declaration.principal
        if (
            dimension == "unknown_external_effect"
            and principal.account_owner == "agent_owned"
            and principal.trust_mode == "trusted_agent"
        ):
            return "audit"
        if dimension == "unknown_external_effect" and principal.account_owner == "user_owned":
            return "step_up"
        return "assertion"

    def _pending_assertions(self, managed: _ManagedSafetyContext) -> list[SafetyAssertionKey]:
        return [
            key
            for key in managed.contract.required_assertions
            if managed.assertions.get(key) is not True
        ]

    def _resolve_expiry(self, declaration: SafetyDeclaration) -> datetime:
        now = self._now()
        if declaration.expires_at is not None:
            value = declaration.expires_at
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        return now + timedelta(seconds=declaration.expires_in_seconds or 3600)

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _message_for(self, managed: _ManagedSafetyContext) -> str:
        if managed.status == "assertion_required":
            return "Agent assertions are required before the protected operation can execute"
        if managed.status == "ready":
            return "Safety contract obligations are satisfied; hard boundaries still apply"
        if managed.status == "step_up_required":
            return "The operation is outside the current safety context scope"
        if managed.status == "takeover_required":
            return "Human takeover is required"
        if managed.status == "expired":
            return "Safety context has expired"
        if managed.status == "consumed":
            return "Safety context has no remaining uses"
        if managed.status == "blocked":
            return "Safety context is blocked"
        return "Safety context is available"


_ASSURANCE_RANK = {
    "agent_asserted": 0,
    "runtime_observed": 1,
    "provider_verified": 2,
    "user_confirmed": 3,
}


def _max_assurance(left: str, right: str) -> str:
    return left if _ASSURANCE_RANK[left] >= _ASSURANCE_RANK[right] else right


def _normalize_origin(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
    if parsed.scheme == "file":
        return "file://"
    return ""


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
