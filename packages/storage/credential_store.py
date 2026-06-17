"""Credential Store: secure token storage for provider connections."""

from __future__ import annotations

import json
import os
from pathlib import Path

from storage.file_store import ensure_webfa_data_dir


class CredentialStoreNotImplemented(RuntimeError):
    pass


class CredentialStore:
    """File-based credential store.

    Stores tokens in credentials/ directory as JSON files.
    Each file: {provider}/{connection_id}.json
    Only stores the token, never logs or exposes it.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        if base_dir is None:
            paths = ensure_webfa_data_dir()
            base_dir = paths["credentials"]
        self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, credential_ref: str) -> Path:
        # credential_ref format: "provider:connection_id" e.g. "github:default"
        parts = credential_ref.split(":", 1)
        if len(parts) == 2:
            provider, conn_id = parts
        else:
            provider, conn_id = parts[0], "default"
        provider_dir = self._base_dir / provider
        provider_dir.mkdir(parents=True, exist_ok=True)
        return provider_dir / f"{conn_id}.json"

    def put(self, provider: str, token: str, connection_id: str = "default") -> str:
        """Store a token and return credential_ref."""
        credential_ref = f"{provider}:{connection_id}"
        path = self._path_for(credential_ref)
        data = {"credential_ref": credential_ref, "token": token}
        path.write_text(json.dumps(data), encoding="utf-8")
        return credential_ref

    def get(self, credential_ref: str) -> str:
        """Retrieve a token by credential_ref. Raises if not found."""
        path = self._path_for(credential_ref)
        if not path.exists():
            raise FileNotFoundError(f"Credential not found: {credential_ref}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return data["token"]

    def delete(self, credential_ref: str) -> bool:
        """Delete a credential. Returns True if deleted."""
        path = self._path_for(credential_ref)
        if path.exists():
            path.unlink()
            return True
        return False

    def exists(self, credential_ref: str) -> bool:
        return self._path_for(credential_ref).exists()
