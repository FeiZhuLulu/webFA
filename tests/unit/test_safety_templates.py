from __future__ import annotations

from browser.safety_templates import SafetyContractCompiler, SafetyTemplateRegistry
from schemas.safety import SafetyDeclaration


def _declaration(*dimensions: dict, owner: str = "agent_owned") -> SafetyDeclaration:
    return SafetyDeclaration.model_validate(
        {
            "principal": {
                "agent_id": "agent-1",
                "profile_id": "profile-1",
                "account_owner": owner,
            },
            "task": {"intent": "test_task", "subject": "subject"},
            "dimensions": list(dimensions),
            "authorization_claim": {
                "status": "explicit",
                "source_ref": "user_turn_1",
            },
        }
    )


def test_registry_defines_all_eight_generic_dimensions() -> None:
    registry = SafetyTemplateRegistry()
    assert [item.dimension for item in registry.list()] == [
        "identity_context",
        "financial_commitment",
        "local_data_egress",
        "external_representation",
        "destructive_change",
        "authority_change",
        "recurring_commitment",
        "unknown_external_effect",
    ]
    assert all(item.version == 1 for item in registry.list())


def test_financial_contract_is_site_independent_and_deterministic() -> None:
    compiler = SafetyContractCompiler()
    first = _declaration(
        {
            "type": "financial_commitment",
            "kind": "one_time_purchase",
            "currency": "CNY",
            "maximum_amount": "300",
            "merchant": "merchant-a",
        }
    )
    second = first.model_copy(
        update={
            "task": first.task.model_copy(update={"subject": "different product"}),
            "dimensions": [
                first.dimensions[0].model_copy(update={"merchant": "merchant-b"})
            ],
        }
    )

    contract_a = compiler.compile(first, context_id="sctx_a")
    contract_b = compiler.compile(second, context_id="sctx_b")

    assert contract_a.template_versions == ["financial_commitment.v1"]
    assert contract_a.required_assertions == contract_b.required_assertions
    assert contract_a.hard_boundaries == contract_b.hard_boundaries
    assert "user_explicitly_authorized_purchase" in contract_a.required_assertions
    assert "no_unapproved_recurring_commitment" in contract_a.required_assertions

    corpus = " ".join(
        template.instruction_for("en")
        for template in SafetyTemplateRegistry().list()
    ).lower()
    for site_name in ("taobao", "jd.com", "amazon", "gmail", "github"):
        assert site_name not in corpus


def test_agent_owned_unknown_effect_defaults_to_ready_allow_path() -> None:
    contract = SafetyContractCompiler().compile(
        _declaration({"type": "unknown_external_effect", "summary": "unclassified mutation"}),
        context_id="sctx_unknown",
    )

    assert contract.status == "ready"
    assert contract.required_assertions == []
    assert contract.active_dimensions == ["unknown_external_effect"]


def test_user_owned_unknown_effect_requires_assertion() -> None:
    contract = SafetyContractCompiler().compile(
        _declaration(
            {"type": "unknown_external_effect", "summary": "unclassified mutation"},
            owner="user_owned",
        ),
        context_id="sctx_unknown_user",
    )

    assert contract.status == "assertion_required"
    assert contract.required_assertions == ["user_reviewed_unknown_external_effect"]


def test_composed_contract_deduplicates_boundaries_in_canonical_order() -> None:
    contract = SafetyContractCompiler().compile(
        _declaration(
            {
                "type": "financial_commitment",
                "kind": "one_time_purchase",
                "currency": "CNY",
                "maximum_amount": "300",
            },
            {
                "type": "identity_context",
                "account_owner": "agent_owned",
                "action": "use_existing_account",
            },
        ),
        context_id="sctx_composed",
    )

    assert contract.active_dimensions == ["identity_context", "financial_commitment"]
    assert contract.template_versions == ["identity_context.v1", "financial_commitment.v1"]
    assert len(contract.hard_boundaries) == len(set(contract.hard_boundaries))
    assert contract.instruction.startswith("WebFA 不判断用户意图")
