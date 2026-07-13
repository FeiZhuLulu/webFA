from __future__ import annotations

from collections import deque
from threading import RLock

from schemas.safety import SafetyReceipt


class SafetyReceiptStore:
    """Bounded, session-local store for secret-free safety receipts."""

    def __init__(
        self,
        max_entries: int = 500,
        *,
        profile_id: str = "default",
        session_id: str = "default",
        runtime_generation: str = "default",
    ) -> None:
        self._profile_id = profile_id
        self._session_id = session_id
        self._runtime_generation = runtime_generation
        self._entries: deque[SafetyReceipt] = deque(maxlen=max(1, max_entries))
        self._by_id: dict[str, SafetyReceipt] = {}
        self._connection_by_id: dict[str, str] = {}
        self._lock = RLock()

    def append(
        self,
        receipt: SafetyReceipt,
        *,
        connection_id: str = "default",
    ) -> SafetyReceipt:
        if (
            receipt.profile_id != self._profile_id
            or receipt.session_id != self._session_id
            or receipt.runtime_generation != self._runtime_generation
        ):
            raise ValueError("safety receipt is bound to another Browser Session generation")
        with self._lock:
            if len(self._entries) == self._entries.maxlen and self._entries:
                evicted = self._entries[0]
                self._by_id.pop(evicted.receipt_id, None)
                self._connection_by_id.pop(evicted.receipt_id, None)
            stored = receipt.model_copy(deep=True)
            self._entries.append(stored)
            self._by_id[stored.receipt_id] = stored
            self._connection_by_id[stored.receipt_id] = connection_id
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
