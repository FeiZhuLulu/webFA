from __future__ import annotations

from dataclasses import dataclass


class AuthorityBindingError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class RuntimeAuthorityScope:
    """Trusted Runtime binding for short-lived authority objects.

    The Agent never supplies session_id, runtime_generation, or connection_id in
    a tool payload. The Runtime derives them from the authenticated transport and
    the selected BrowserSessionRuntime.
    """

    agent_id: str
    connection_id: str
    profile_id: str
    session_id: str
    runtime_generation: str

    def __post_init__(self) -> None:
        for name, value in (
            ("agent_id", self.agent_id),
            ("connection_id", self.connection_id),
            ("profile_id", self.profile_id),
            ("session_id", self.session_id),
            ("runtime_generation", self.runtime_generation),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} is required")

    def fingerprint(self) -> tuple[str, str, str, str, str]:
        return (
            self.agent_id,
            self.connection_id,
            self.profile_id,
            self.session_id,
            self.runtime_generation,
        )

    def require_same(
        self,
        other: "RuntimeAuthorityScope",
        *,
        code: str = "authority_binding_mismatch",
        message: str = "authority object is bound to another Runtime scope",
    ) -> None:
        if self.fingerprint() != other.fingerprint():
            raise AuthorityBindingError(code, message)


def normalize_connection_id(connection_id: str | None, *, agent_id: str) -> str:
    value = (connection_id or "").strip()
    return value or f"compat:{agent_id}"
