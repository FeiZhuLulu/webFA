from browser.runtime import _bind_navigation_scope, _safe_step_up_get
from browser.step_up import StepUpError, StepUpManager


def _request(manager: StepUpManager):
    return manager.request(
        reason="financial_limit",
        context_id="sctx_1",
        agent_id="agent-a",
        profile_id="default",
        origin="https://shop.example",
        target_object_id="obj_pay",
        operation="provide_payment_instrument",
        message="amount exceeds autonomy limit",
        current_scope={"autonomy_limit": "100.00"},
        requested_scope={"amount": "279.00", "currency": "CNY"},
    )


def test_step_up_is_exact_scope_single_use():
    manager = StepUpManager()
    pending = _request(manager)
    approved = manager.approve(pending.request.step_up_id, decided_by="user")
    assert approved.status == "approved"

    authorized = manager.authorize(
        pending.request.step_up_id,
        context_id="sctx_1",
        agent_id="agent-a",
        profile_id="default",
        origin="https://shop.example",
        target_object_id="obj_pay",
        operation="provide_payment_instrument",
        requested_scope={"amount": "279.00", "currency": "CNY"},
    )
    assert authorized.status == "approved"

    consumed = manager.consume(pending.request.step_up_id)
    assert consumed.status == "consumed"
    assert consumed.remaining_uses == 0

    try:
        manager.authorize(
            pending.request.step_up_id,
            context_id="sctx_1",
            agent_id="agent-a",
            profile_id="default",
            origin="https://shop.example",
            target_object_id="obj_pay",
            operation="provide_payment_instrument",
            requested_scope={"amount": "279.00", "currency": "CNY"},
        )
    except StepUpError as exc:
        assert exc.code == "step_up_not_approved"
    else:
        raise AssertionError("consumed step-up must not be reusable")


def test_step_up_rejects_binding_and_scope_mismatch():
    manager = StepUpManager()
    pending = _request(manager)
    manager.approve(pending.request.step_up_id)

    for kwargs, code in [
        ({"agent_id": "agent-b"}, "step_up_binding_mismatch"),
        ({"requested_scope": {"amount": "500.00", "currency": "CNY"}}, "step_up_scope_mismatch"),
    ]:
        arguments = {
            "context_id": "sctx_1",
            "agent_id": "agent-a",
            "profile_id": "default",
            "origin": "https://shop.example",
            "target_object_id": "obj_pay",
            "operation": "provide_payment_instrument",
            "requested_scope": {"amount": "279.00", "currency": "CNY"},
            **kwargs,
        }
        try:
            manager.authorize(pending.request.step_up_id, **arguments)
        except StepUpError as exc:
            assert exc.code == code
        else:
            raise AssertionError("mismatched step-up must be rejected")


def test_step_up_rejects_document_or_object_version_change_after_approval():
    manager = StepUpManager()
    pending = manager.request(
        reason="financial_limit",
        context_id="sctx_1",
        agent_id="agent-a",
        profile_id="default",
        origin="https://shop.example",
        target_object_id="obj_pay",
        operation="activate",
        message="confirm exact page state",
        requested_scope={
            "amount": "279.00",
            "currency": "CNY",
            "document_id": "doc_1",
            "document_revision": 8,
            "object_version": 3,
        },
    )
    manager.approve(pending.request.step_up_id)

    for changed_scope in (
        {
            "amount": "279.00",
            "currency": "CNY",
            "document_id": "doc_1",
            "document_revision": 9,
            "object_version": 3,
        },
        {
            "amount": "279.00",
            "currency": "CNY",
            "document_id": "doc_1",
            "document_revision": 8,
            "object_version": 4,
        },
    ):
        try:
            manager.authorize(
                pending.request.step_up_id,
                context_id="sctx_1",
                agent_id="agent-a",
                profile_id="default",
                origin="https://shop.example",
                target_object_id="obj_pay",
                operation="activate",
                requested_scope=changed_scope,
            )
        except StepUpError as exc:
            assert exc.code == "step_up_scope_mismatch"
        else:
            raise AssertionError("step-up must be invalidated when the approved page state changes")


def test_step_up_approval_cannot_expand_original_scope():
    manager = StepUpManager()
    pending = _request(manager)

    try:
        manager.approve(
            pending.request.step_up_id,
            approved_scope={"amount": "500.00", "currency": "CNY"},
        )
    except StepUpError as exc:
        assert exc.code == "step_up_scope_mismatch"
    else:
        raise AssertionError("step-up approval must not expand the original request")


def test_navigation_scope_redacts_sensitive_url_but_binds_exact_fingerprint():
    first = _bind_navigation_scope(
        {"origin": "https://example.com"},
        "https://example.com/callback?code=secret-a&state=ok#access_token=hidden-a",
    )
    second = _bind_navigation_scope(
        {"origin": "https://example.com"},
        "https://example.com/callback?code=secret-b&state=ok#access_token=hidden-b",
    )

    assert "secret-a" not in str(first)
    assert "hidden-a" not in str(first)
    assert "[REDACTED]" in str(first["url"])
    assert first["url_fingerprint"] != second["url_fingerprint"]


def test_agent_safe_step_up_view_redacts_human_decision_metadata():
    manager = StepUpManager()
    pending = _request(manager)
    manager.approve(
        pending.request.step_up_id,
        decided_by="local-user-name",
        decision_note="private human note",
    )

    safe = _safe_step_up_get(manager, pending.request.step_up_id)
    full = manager.get(pending.request.step_up_id)

    assert safe is not None
    assert safe.decided_by is None
    assert safe.decision_note == ""
    assert full.decided_by == "local-user-name"
    assert full.decision_note == "private human note"


def test_step_up_reuses_pending_request_and_can_be_rejected():
    manager = StepUpManager()
    first = _request(manager)
    second = _request(manager)
    assert first.request.step_up_id == second.request.step_up_id

    rejected = manager.reject(first.request.step_up_id, decision_note="not approved")
    assert rejected.status == "rejected"
    assert rejected.remaining_uses == 0
