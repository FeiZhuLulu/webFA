from __future__ import annotations


class CredentialStoreNotImplemented(RuntimeError):
    pass


class CredentialStore:
    """Placeholder for system credential manager integration.

    v0.1 does not persist real tokens. Future implementations should use Keychain,
    Windows Credential Manager, Secret Service/libsecret, or an encrypted fallback.
    """

    def put(self, provider: str, secret: str) -> str:  # pragma: no cover - intentionally unavailable
        raise CredentialStoreNotImplemented("Credential storage is not implemented in v0.1")

    def get(self, credential_ref: str) -> str:  # pragma: no cover - intentionally unavailable
        raise CredentialStoreNotImplemented("Credential retrieval is not implemented in v0.1")
