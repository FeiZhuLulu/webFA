from schemas.safety import SafetyReceipt
from browser.safety_audit import SafetyReceiptStore


def _receipt(receipt_id: str) -> SafetyReceipt:
    return SafetyReceipt(
        receipt_id=receipt_id,
        context_id="sctx_1",
        agent_id="agent-a",
        profile_id="default",
        origin="https://example.com",
        target_object_id="obj_1",
        operation="submit",
        p10_effect="external_write",
        safety_dimensions=["unknown_external_effect"],
        final_decision="allow_with_audit",
        before_revision=1,
        after_revision=2,
        result="executed",
        message="safe receipt",
    )


def test_receipt_store_is_bounded_and_returns_newest_first():
    store = SafetyReceiptStore(max_entries=2)
    store.append(_receipt("receipt_1"))
    store.append(_receipt("receipt_2"))
    store.append(_receipt("receipt_3"))

    assert [item.receipt_id for item in store.list()] == ["receipt_3", "receipt_2"]
    assert store.get("receipt_1") is None
    assert store.get("receipt_3") is not None
