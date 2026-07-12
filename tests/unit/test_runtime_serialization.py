from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Lock
import time

import pytest

from browser.human_control import HumanControlError, HumanInputEvent
from browser.runtime import BrowserRuntime, _SelectedPaymentInstrument, _monitor_safe_url
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


def test_human_control_disconnect_releases_stuck_pointer_and_keys(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    runtime = BrowserRuntime(driver_factory=lambda: None)  # type: ignore[arg-type]
    dispatched: list[HumanInputEvent] = []
    worker_calls: list[str] = []

    def fake_call(name: str, *args):
        if name == "monitor_snapshot":
            return {"session_id": "default", "tab_id": "tab_1"}
        if name == "dispatch_human_input":
            dispatched.append(args[0])
            return None
        if name == "end_human_control":
            worker_calls.append(name)
            return None
        raise AssertionError(f"unexpected worker call: {name}")

    runtime._call = fake_call  # type: ignore[method-assign]
    runtime._thread = object()  # type: ignore[assignment]
    lease = runtime._human_control.acquire(
        connection_id="connection-1",
        session_id="default",
        profile_id="default",
        tab_id="tab_1",
        reason="authentication",
        active_agent_id=None,
        ttl_seconds=60,
    )
    try:
        runtime.send_human_input(
            connection_id="connection-1",
            lease_id=lease.lease_id,
            event=HumanInputEvent(
                type="mouse_down",
                x=20,
                y=30,
                button="left",
                buttons=1,
            ),
        )
        runtime.send_human_input(
            connection_id="connection-1",
            lease_id=lease.lease_id,
            event=HumanInputEvent(
                type="key_down",
                key="Control",
                code="ControlLeft",
                modifiers=("control",),
            ),
        )

        runtime.release_human_control_connection("connection-1")
    finally:
        runtime._thread = None
        runtime.close()

    assert [event.type for event in dispatched] == [
        "mouse_down",
        "key_down",
        "mouse_up",
        "key_up",
    ]
    assert dispatched[-2].button == "left"
    assert dispatched[-2].buttons == 0
    assert dispatched[-1].key == "Control"
    assert worker_calls == ["end_human_control"]


def test_human_control_input_rejects_current_tab_mismatch(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    runtime = BrowserRuntime(driver_factory=lambda: None)  # type: ignore[arg-type]
    lease = runtime._human_control.acquire(
        connection_id="connection-1",
        session_id="default",
        profile_id="default",
        tab_id="tab_1",
        reason="authentication",
        active_agent_id="agent-a",
        ttl_seconds=60,
    )

    def fake_call(name: str, *_args):
        if name == "monitor_snapshot":
            return {"session_id": "default", "tab_id": "tab_2"}
        raise AssertionError(f"unexpected worker call: {name}")

    runtime._call = fake_call  # type: ignore[method-assign]
    try:
        with pytest.raises(HumanControlError) as exc_info:
            runtime.send_human_input(
                connection_id="connection-1",
                lease_id=lease.lease_id,
                event=HumanInputEvent(type="insert_text", text="hidden"),
            )
    finally:
        runtime._human_control.release(
            lease_id=lease.lease_id,
            connection_id="connection-1",
            status="aborted",
        )
        runtime.close()

    assert exc_info.value.code == "human_control_tab_mismatch"


def test_monitor_safe_url_redacts_query_fragment_and_sensitive_path_values() -> None:
    safe = _monitor_safe_url(
        "https://example.com/reset/abcdefghijklmnopqrstuvwxyz012345?token=query-secret#fragment-secret"
    )
    email = _monitor_safe_url("https://example.com/users/alice%40example.com/profile")
    composite = _monitor_safe_url(
        "https://example.com/reset-password/abcdefghijklmnopqrstuvwxyz012345"
    )

    assert safe == "https://example.com/reset/[REDACTED]"
    assert "query-secret" not in safe
    assert "fragment-secret" not in safe
    assert email == "https://example.com/users/[REDACTED]/profile"
    assert composite == "https://example.com/reset-password/[REDACTED]"


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
