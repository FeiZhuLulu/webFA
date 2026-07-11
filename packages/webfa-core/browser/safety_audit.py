from __future__ import annotations

from collections import deque
from threading import RLock

from schemas.safety import SafetyReceipt


class SafetyReceiptStore:
    """Bounded, session-local store for secret-free safety receipts."""

    def __init__(self, max_entries: int = 500) -> None:
        self._entries: deque[SafetyReceipt] = deque(maxlen=max(1, max_entries))
        self._by_id: dict[str, SafetyReceipt] = {}
        self._lock = RLock()

    def append(self, receipt: SafetyReceipt) -> SafetyReceipt:
        with self._lock:
            if len(self._entries) == self._entries.maxlen and self._entries:
                evicted = self._entries[0]
                self._by_id.pop(evicted.receipt_id, None)
            stored = receipt.model_copy(deep=True)
            self._entries.append(stored)
            self._by_id[stored.receipt_id] = stored
            return stored.model_copy(deep=True)

    def list(self, *, limit: int = 100) -> list[SafetyReceipt]:
        with self._lock:
            count = max(1, min(limit, 500))
            values = list(self._entries)[-count:]
            values.reverse()
            return [item.model_copy(deep=True) for item in values]

    def get(self, receipt_id: str) -> SafetyReceipt | None:
        with self._lock:
            item = self._by_id.get(receipt_id)
            return item.model_copy(deep=True) if item is not None else None
