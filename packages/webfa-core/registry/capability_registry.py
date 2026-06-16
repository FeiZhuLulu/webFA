"""Capability registry: registers and validates capabilities required by transactions."""

from __future__ import annotations

from schemas.capability import Capability


# Phase 1: only mock capabilities exist.
MOCK_CAPABILITIES: list[Capability] = [
    Capability(id="mock.issue.read", provider="mock", description="Read a mock issue"),
    Capability(id="mock.repo.read", provider="mock", description="Read mock repo metadata"),
    Capability(id="mock.file.read", provider="mock", description="Read mock file content"),
    Capability(id="mock.branch.create", provider="mock", description="Create a mock branch"),
    Capability(id="mock.commit.create", provider="mock", description="Create a mock commit"),
    Capability(id="mock.pr.create", provider="mock", description="Create a mock pull request"),
]


class CapabilityRegistry:
    """In-memory registry of available capabilities."""

    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}
        for cap in MOCK_CAPABILITIES:
            self._capabilities[cap.id] = cap

    def list(self) -> list[Capability]:
        return list(self._capabilities.values())

    def get(self, capability_id: str) -> Capability | None:
        return self._capabilities.get(capability_id)

    def exists(self, capability_id: str) -> bool:
        return capability_id in self._capabilities

    def validate_required(self, required: list[str]) -> list[str]:
        """Return list of missing capability IDs."""
        return [cid for cid in required if not self.exists(cid)]
