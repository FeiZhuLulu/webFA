from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from schemas.safety import (
    ProfileOwnershipMetadata,
    SafetyDeclaration,
    SafetyDecisionName,
    SafetyEvidenceItem,
    SafetyEvidenceReport,
    SafetyMismatch,
)


@dataclass(frozen=True)
class ProfilePolicyEvaluation:
    decision: SafetyDecisionName = "allow"
    status: str = "ready"
    message: str = "Profile policy allows the operation"
    evidence: tuple[SafetyEvidenceItem, ...] = ()
    mismatches: tuple[SafetyMismatch, ...] = ()


class ProfilePolicyStore:
    """Session-local profile ownership and Agent binding policy.

    P11 stores policy metadata for the current Browser Profile. It does not
    create multiple isolated browser profiles; that remains P12.
    """

    def __init__(self) -> None:
        self._profiles: dict[str, ProfileOwnershipMetadata] = {
            "default": ProfileOwnershipMetadata(
                profile_id="default",
                owner="shared",
                trust_mode="trusted_agent",
            )
        }

    def get(self, profile_id: str = "default") -> ProfileOwnershipMetadata:
        metadata = self._profiles.get(profile_id)
        if metadata is None:
            metadata = ProfileOwnershipMetadata(
                profile_id=profile_id,
                owner="shared",
                trust_mode="trusted_agent",
            )
            self._profiles[profile_id] = metadata
        return metadata.model_copy(deep=True)

    def upsert(self, metadata: ProfileOwnershipMetadata) -> ProfileOwnershipMetadata:
        self._profiles[metadata.profile_id] = metadata.model_copy(deep=True)
        return self.get(metadata.profile_id)

    def list(self) -> list[ProfileOwnershipMetadata]:
        return [self.get(profile_id) for profile_id in sorted(self._profiles)]

    def evaluate(
        self,
        *,
        agent_id: str,
        profile_id: str,
        current_origin: str,
        declaration: SafetyDeclaration | None,
        evidence_report: SafetyEvidenceReport | None,
    ) -> ProfilePolicyEvaluation:
        metadata = self.get(profile_id)
        evidence = (
            SafetyEvidenceItem(
                code="profile:active_policy",
                kind="identity_policy",
                source="browser_host",
                assurance="provider_verified",
                dimension="identity_context",
                summary="WebFA applied the active Profile ownership and Agent binding policy",
                origin=current_origin,
                details={
                    "profile_id": metadata.profile_id,
                    "owner": metadata.owner,
                    "trust_mode": metadata.trust_mode,
                    "unknown_effect_policy": metadata.unknown_external_effect_policy or "require_step_up",
                },
            ),
        )

        if metadata.bound_agent_ids and agent_id not in metadata.bound_agent_ids:
            return _blocked(
                "The active Agent is not bound to this Browser Profile",
                "profile_binding_mismatch",
                evidence,
            )
        if metadata.allowed_origins and current_origin not in metadata.allowed_origins:
            return _blocked(
                "The current origin is outside the active Browser Profile policy",
                "profile_binding_mismatch",
                evidence,
            )

        if declaration is not None:
            principal = declaration.principal
            if principal.account_owner != metadata.owner:
                return _blocked(
                    "SafetyDeclaration account_owner does not match the active Browser Profile owner",
                    "profile_owner_mismatch",
                    evidence,
                )
            if principal.trust_mode != metadata.trust_mode:
                return _blocked(
                    "SafetyDeclaration trust_mode does not match the active Browser Profile policy",
                    "profile_trust_mode_mismatch",
                    evidence,
                )

            identity_dimensions = [
                dimension
                for dimension in declaration.dimensions
                if dimension.type == "identity_context"
            ]
            for dimension in identity_dimensions:
                if dimension.action == "use_existing_account" and dimension.account_owner != metadata.owner:
                    return _blocked(
                        "The declared account owner does not match the active Browser Profile owner",
                        "profile_owner_mismatch",
                        evidence,
                    )
                if dimension.action in {
                    "sign_in",
                    "switch_account",
                    "create_account",
                    "authorize_third_party",
                } and metadata.owner == "user_owned":
                    return _step_up(
                        "Identity changes in a user-owned Browser Profile require scope escalation",
                        "identity_switch_requires_step_up",
                        evidence,
                    )

        observed = set(evidence_report.observed_dimensions if evidence_report is not None else [])
        specifically_classified = observed.intersection(
            {
                "financial_commitment",
                "local_data_egress",
                "external_representation",
                "destructive_change",
                "authority_change",
                "recurring_commitment",
            }
        )
        if "unknown_external_effect" in observed and not specifically_classified:
            policy = metadata.unknown_external_effect_policy or "require_step_up"
            if policy == "deny":
                return _blocked(
                    "The active Browser Profile denies unknown external effects",
                    "unknown_effect_policy_violation",
                    evidence,
                )
            if policy == "require_step_up":
                return _step_up(
                    "Unknown external effects require scope escalation for this Browser Profile",
                    "unknown_effect_policy_violation",
                    evidence,
                )
            if policy == "require_assertion":
                declared_unknown = bool(
                    declaration is not None
                    and any(
                        dimension.type == "unknown_external_effect"
                        for dimension in declaration.dimensions
                    )
                )
                if not declared_unknown:
                    return ProfilePolicyEvaluation(
                        decision="require_assertion",
                        status="assertion_required",
                        message="The active Browser Profile requires an Agent assertion for unknown external effects",
                        evidence=evidence,
                        mismatches=(
                            SafetyMismatch(
                                code="unknown_effect_policy_violation",
                                severity="assertion",
                                message="Profile policy requires explicit Agent review of the unknown external effect",
                            ),
                        ),
                    )

        if metadata.trust_mode == "guarded" and observed.intersection(
            {
                "destructive_change",
                "authority_change",
                "unknown_external_effect",
            }
        ):
            return _step_up(
                "Guarded Profile policy requires scope escalation for the observed external effect",
                "unknown_effect_policy_violation",
                evidence,
            )

        return ProfilePolicyEvaluation(evidence=evidence)


def _blocked(
    message: str,
    code: str,
    evidence: tuple[SafetyEvidenceItem, ...],
) -> ProfilePolicyEvaluation:
    return ProfilePolicyEvaluation(
        decision="deny",
        status="blocked",
        message=message,
        evidence=evidence,
        mismatches=(
            SafetyMismatch(code=code, severity="deny", message=message),  # type: ignore[arg-type]
        ),
    )


def _step_up(
    message: str,
    code: str,
    evidence: tuple[SafetyEvidenceItem, ...],
) -> ProfilePolicyEvaluation:
    return ProfilePolicyEvaluation(
        decision="require_step_up",
        status="step_up_required",
        message=message,
        evidence=evidence,
        mismatches=(
            SafetyMismatch(code=code, severity="step_up", message=message),  # type: ignore[arg-type]
        ),
    )


def normalize_origin(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return value.strip()
