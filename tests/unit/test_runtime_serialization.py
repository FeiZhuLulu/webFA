from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Lock
import time

from browser.runtime import BrowserRuntime, _SelectedPaymentInstrument
from schemas.web import WebObject, WebObjectState, WebOperationRequest, WebOperationResult, WebState


def test_formal_web_operations_are_serialized_across_safety_and_execution(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    runtime = BrowserRuntime(driver_factory=lambda: None)  # type: ignore[arg-type]
    state_lock = Lock()
    active = 0
    maximum_active = 0

    def fake_act(request: WebOperationRequest, agent_id: str | None = None) -> WebOperationResult:
        nonlocal active, maximum_active
        with state_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.05)
        with state_lock:
            active -= 1
        return WebOperationResult(
            ok=True,
            target=request.target,
            operation=request.operation,
            document_revision=1,
            state=WebState(
                document_id="doc_test",
                document_revision=1,
                url="https://example.com",
                title="Test",
            ),
        )

    runtime._act_web_inner = fake_act  # type: ignore[method-assign]
    request = WebOperationRequest(target="obj_1", operation="activate")
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: runtime.act_web(request, agent_id="agent-a"), range(2)))
    finally:
        runtime.close()

    assert all(result.ok for result in results)
    assert maximum_active == 1


def test_selected_payment_is_bound_to_exact_document_and_transaction(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    runtime = BrowserRuntime(driver_factory=lambda: None)  # type: ignore[arg-type]
    payment_option = WebObject(
        id="obj_pay",
        category="interactive",
        role="radio",
        name="Pay with Visa ending in 4821",
        capabilities=["provide_payment_instrument"],
        origin="https://shop.example",
        state=WebObjectState(checked=True),
    )
    state = WebState(
        document_id="doc_checkout",
        document_revision=4,
        url="https://shop.example/checkout",
        title="Checkout",
        objects=[payment_option],
        object_count=1,
    )
    try:
        missing = runtime._selected_payment_error(
            instrument_id="pay_1",
            agent_id="agent-a",
            profile_id="default",
            state=state,
            amount=Decimal("279.00"),
            currency="CNY",
            transaction_kind="one_time_purchase",
            recurring=False,
        )
        runtime._selected_payment = _SelectedPaymentInstrument(
            agent_id="agent-a",
            profile_id="default",
            document_id="doc_checkout",
            origin="https://shop.example",
            target_object_id="obj_pay",
            instrument_id="pay_1",
            amount=Decimal("279.00"),
            currency="CNY",
            transaction_kind="one_time_purchase",
            recurring=False,
            assurance="runtime_observed",
        )
        exact = runtime._selected_payment_error(
            instrument_id="pay_1",
            agent_id="agent-a",
            profile_id="default",
            state=state,
            amount=Decimal("279.00"),
            currency="CNY",
            transaction_kind="one_time_purchase",
            recurring=False,
        )
        changed_document = runtime._selected_payment_error(
            instrument_id="pay_1",
            agent_id="agent-a",
            profile_id="default",
            state=state.model_copy(update={"document_id": "doc_reloaded"}),
            amount=Decimal("279.00"),
            currency="CNY",
            transaction_kind="one_time_purchase",
            recurring=False,
        )
    finally:
        runtime.close()

    assert missing is not None
    assert exact is None
    assert changed_document is not None
