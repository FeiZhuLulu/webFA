from browser.profile_policy import ProfilePolicyStore
from schemas.safety import (
    ProfileOwnershipMetadata,
    SafetyDeclaration,
    SafetyEvidenceReport,
)


def _declaration(*, owner: str, action: str = "use_existing_account", trust_mode: str = "trusted_agent"):
    return SafetyDeclaration.model_validate(
        {
            "principal": {
                "agent_id": "agent-a",
                "profile_id": "default",
                "account_owner": owner,
                "trust_mode": trust_mode,
            },
            "task": {"intent": "identity_task", "subject": "account"},
            "dimensions": [
                {
                    "type": "identity_context",
                    "account_owner": owner,
                    "action": action,
                }
            ],
            "authorization_claim": {
                "status": "explicit",
                "source_ref": "user_turn_1",
            },
        }
    )


def test_agent_owned_unknown_effect_defaults_to_allow_with_audit_policy():
    store = ProfilePolicyStore()
    store.upsert(
        ProfileOwnershipMetadata(
            profile_id="default",
            owner="agent_owned",
            bound_agent_ids=["agent-a"],
            trust_mode="trusted_agent",
        )
    )

    result = store.evaluate(
        agent_id="agent-a",
        profile_id="default",
        current_origin="https://shop.example",
        declaration=SafetyDeclaration.model_validate(
            {
                "principal": {
                    "agent_id": "agent-a",
                    "profile_id": "default",
                    "account_owner": "agent_owned",
                    "trust_mode": "trusted_agent",
                },
                "task": {"intent": "submit", "subject": "agent resource"},
                "dimensions": [{"type": "unknown_external_effect", "summary": "submit"}],
                "authorization_claim": {
                    "status": "explicit",
                    "source_ref": "user_turn_1",
                },
            }
        ),
        evidence_report=SafetyEvidenceReport(
            observed_dimensions=["unknown_external_effect"],
            minimum_assurance="runtime_observed",
        ),
    )

    assert result.decision == "allow"
    assert result.mismatches == ()


def test_user_owned_identity_switch_requires_step_up():
    store = ProfilePolicyStore()
    store.upsert(
        ProfileOwnershipMetadata(
            profile_id="default",
            owner="user_owned",
            bound_agent_ids=["agent-a"],
            trust_mode="trusted_agent",
        )
    )

    result = store.evaluate(
        agent_id="agent-a",
        profile_id="default",
        current_origin="https://accounts.example",
        declaration=_declaration(owner="user_owned", action="switch_account"),
        evidence_report=SafetyEvidenceReport(
            observed_dimensions=["identity_context"],
            minimum_assurance="runtime_observed",
        ),
    )

    assert result.decision == "require_step_up"
    assert result.status == "step_up_required"
    assert result.mismatches[0].code == "identity_switch_requires_step_up"


def test_profile_binding_owner_and_trust_mode_are_hard_boundaries():
    store = ProfilePolicyStore()
    store.upsert(
        ProfileOwnershipMetadata(
            profile_id="default",
            owner="user_owned",
            bound_agent_ids=["agent-a"],
            trust_mode="guarded",
        )
    )

    wrong_agent = store.evaluate(
        agent_id="agent-b",
        profile_id="default",
        current_origin="https://example.com",
        declaration=None,
        evidence_report=None,
    )
    wrong_owner = store.evaluate(
        agent_id="agent-a",
        profile_id="default",
        current_origin="https://example.com",
        declaration=_declaration(owner="agent_owned", trust_mode="guarded"),
        evidence_report=None,
    )
    wrong_trust = store.evaluate(
        agent_id="agent-a",
        profile_id="default",
        current_origin="https://example.com",
        declaration=_declaration(owner="user_owned", trust_mode="trusted_agent"),
        evidence_report=None,
    )

    assert wrong_agent.decision == "deny"
    assert wrong_agent.mismatches[0].code == "profile_binding_mismatch"
    assert wrong_owner.decision == "deny"
    assert wrong_owner.mismatches[0].code == "profile_owner_mismatch"
    assert wrong_trust.decision == "deny"
    assert wrong_trust.mismatches[0].code == "profile_trust_mode_mismatch"
