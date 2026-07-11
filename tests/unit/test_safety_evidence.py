from __future__ import annotations

from browser.runtime import _is_final_financial_commit
from browser.safety_context import SafetyContextManager
from browser.safety_evidence import RuntimeEvidenceResolver
from schemas.safety import SafetyOperationEnvelope
from schemas.web import WebObject, WebObjectRelations, WebObjectSecurity, WebOperationRequest, WebState


def _state(*objects: WebObject, url: str = "https://shop.example/checkout") -> WebState:
    return WebState(
        document_id="doc_1",
        document_revision=2,
        url=url,
        title="Checkout",
        objects=list(objects),
        object_count=len(objects),
    )


def test_external_submit_is_minimum_unknown_external_effect() -> None:
    form = WebObject(
        id="form_order",
        category="container",
        role="form",
        name="Order form",
        text="Submit order",
        capabilities=["submit"],
        origin="https://shop.example",
    )
    report = RuntimeEvidenceResolver().resolve(
        target=form,
        operation="submit",
        state=_state(form),
    )

    assert report.p10_effect == "external_write"
    assert "unknown_external_effect" in report.observed_dimensions
    assert any(item.code == "runtime:external_write" for item in report.items)


def test_agent_owned_unknown_effect_extends_context_without_new_assertions() -> None:
    manager = SafetyContextManager()
    declaration = {
        "principal": {
            "agent_id": "agent-a",
            "profile_id": "default",
            "account_owner": "agent_owned",
            "trust_mode": "trusted_agent",
        },
        "task": {"intent": "submit_agent_form", "subject": "agent-owned resource"},
        "dimensions": [
            {
                "type": "identity_context",
                "account_owner": "agent_owned",
                "action": "use_existing_account",
            }
        ],
        "authorization_claim": {"status": "explicit", "source_ref": "turn-1"},
    }
    created = manager.evaluate(
        SafetyOperationEnvelope.model_validate({"declaration": declaration}),
        agent_id="agent-a",
        profile_id="default",
        current_origin="https://shop.example",
    )
    assert created.context_id

    form = WebObject(
        id="form_order",
        category="container",
        role="form",
        name="Order form",
        capabilities=["submit"],
        origin="https://shop.example",
    )
    report = RuntimeEvidenceResolver().resolve(target=form, operation="submit", state=_state(form))
    decision = manager.apply_evidence(
        created.context_id,
        report,
        agent_id="agent-a",
        profile_id="default",
        current_origin="https://shop.example",
    )

    assert decision.decision == "require_assertion"
    assert decision.state is not None
    assert "unknown_external_effect" in decision.state.active_dimensions
    assert any(item.severity == "audit" for item in decision.state.mismatches)
    assert "user_reviewed_unknown_external_effect" not in decision.state.pending_assertions


def test_upload_target_observes_local_data_egress() -> None:
    upload = WebObject(
        id="upload_1",
        category="interactive",
        role="upload_target",
        name="Attachment",
        capabilities=["upload"],
        origin="https://jobs.example",
    )
    report = RuntimeEvidenceResolver().resolve(
        target=upload,
        operation="upload",
        state=_state(upload, url="https://jobs.example/apply"),
    )

    assert report.p10_effect == "upload"
    assert report.observed_dimensions == ["local_data_egress"]
    assert any(item.kind == "upload_target" for item in report.items)


def test_protected_payment_field_observes_financial_commitment() -> None:
    card = WebObject(
        id="card_1",
        category="interactive",
        role="textbox",
        name="Card number",
        capabilities=["request_human_takeover"],
        origin="https://shop.example",
        security=WebObjectSecurity(protected_input=True, protected_kind="payment_card"),
    )
    report = RuntimeEvidenceResolver().resolve(
        target=card,
        operation="request_human_takeover",
        state=_state(card),
    )

    assert "financial_commitment" in report.observed_dimensions
    assert any(item.kind == "payment_surface" for item in report.items)


def test_activate_submit_control_is_treated_as_external_mutation() -> None:
    button = WebObject(
        id="button_submit",
        category="interactive",
        role="button",
        name="Send",
        capabilities=["activate"],
        origin="https://mail.example",
        relations=WebObjectRelations(form="form_mail"),
    )
    form = WebObject(
        id="form_mail",
        category="container",
        role="form",
        name="Message",
        capabilities=["submit"],
        origin="https://mail.example",
        relations=WebObjectRelations(children=[button.id], submit_control=button.id),
    )
    report = RuntimeEvidenceResolver().resolve(
        target=button,
        operation="activate",
        state=_state(form, button, url="https://mail.example/compose"),
    )

    assert "unknown_external_effect" in report.observed_dimensions
    assert any(item.code == "runtime:form_submit_activation" for item in report.items)


def test_payment_button_is_final_commit_but_payment_option_is_selection() -> None:
    button = WebObject(
        id="pay_button",
        category="interactive",
        role="button",
        name="Pay now with Visa ending in 4821",
        capabilities=["provide_payment_instrument"],
        origin="https://shop.example",
    )
    option = WebObject(
        id="pay_option",
        category="interactive",
        role="radio",
        name="Pay with Visa ending in 4821",
        capabilities=["provide_payment_instrument"],
        origin="https://shop.example",
    )
    total = WebObject(
        id="total",
        category="content",
        role="text",
        name="Order total",
        text="Order total: CNY 279.00",
        capabilities=[],
        origin="https://shop.example",
    )

    button_report = RuntimeEvidenceResolver().resolve(
        target=button,
        operation="provide_payment_instrument",
        state=_state(total, button, option),
    )
    option_report = RuntimeEvidenceResolver().resolve(
        target=option,
        operation="provide_payment_instrument",
        state=_state(total, button, option),
    )

    assert any(item.code == "runtime:financial_commit_control" for item in button_report.items)
    assert all(item.code != "runtime:financial_commit_control" for item in option_report.items)


def test_page_total_alone_does_not_turn_unrelated_form_into_financial_commit() -> None:
    coupon_button = WebObject(
        id="coupon_button",
        category="interactive",
        role="button",
        name="Apply coupon",
        capabilities=["activate"],
        origin="https://shop.example",
        relations=WebObjectRelations(form="coupon_form"),
    )
    coupon_form = WebObject(
        id="coupon_form",
        category="container",
        role="form",
        name="Coupon form",
        text="Discount code",
        capabilities=["submit"],
        origin="https://shop.example",
        relations=WebObjectRelations(children=[coupon_button.id], submit_control=coupon_button.id),
    )
    total = WebObject(
        id="total",
        category="content",
        role="text",
        name="Order total",
        text="Order total: CNY 279.00",
        capabilities=[],
        origin="https://shop.example",
    )
    report = RuntimeEvidenceResolver().resolve(
        target=coupon_button,
        operation="activate",
        state=_state(total, coupon_form, coupon_button),
    )

    assert "financial_commitment" in report.observed_dimensions
    assert not _is_final_financial_commit(
        WebOperationRequest(target=coupon_button.id, operation="activate"),
        report,
    )


def test_file_url_local_submit_does_not_create_external_effect() -> None:
    form = WebObject(
        id="local_form",
        category="container",
        role="form",
        name="Local validation",
        capabilities=["submit"],
        origin="",
    )
    report = RuntimeEvidenceResolver().resolve(
        target=form,
        operation="submit",
        state=_state(form, url="file:///tmp/test.html"),
    )
    assert report.observed_dimensions == []
