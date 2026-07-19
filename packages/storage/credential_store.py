"""Bounded local credential-file storage for legacy Provider connections."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from storage.file_store import ensure_webfa_data_dir


class CredentialStoreNotImplemented(RuntimeError):
    pass


class CredentialStoreError(RuntimeError):
    pass


_REFERENCE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_MAX_TOKEN_BYTES = 16 * 1024


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
        self._base_dir = base_dir.resolve()
        self._base_dir.mkdir(parents=True, exist_ok=True)
        _make_private(self._base_dir, directory=True)

    def _path_for(self, credential_ref: str, *, create_parent: bool = False) -> Path:
        provider, connection_id = _parse_credential_ref(credential_ref)
        provider_dir = self._base_dir / provider
        if provider_dir.is_symlink():
            raise CredentialStoreError("Credential Provider directory must not be a symbolic link")
        if create_parent:
            provider_dir.mkdir(parents=False, exist_ok=True)
            _make_private(provider_dir, directory=True)
        resolved_provider_dir = provider_dir.resolve(strict=False)
        if resolved_provider_dir.parent != self._base_dir:
            raise CredentialStoreError("Credential reference escapes the credential store")
        path = resolved_provider_dir / f"{connection_id}.json"
        if path.is_symlink():
            raise CredentialStoreError("Credential file must not be a symbolic link")
        return path

    def put(self, provider: str, token: str, connection_id: str = "default") -> str:
        """Store a token and return credential_ref."""
        _validate_reference_segment(provider, "provider")
        _validate_reference_segment(connection_id, "connection_id")
        if not isinstance(token, str) or not token:
            raise ValueError("Credential token must be a non-empty string")
        if len(token.encode("utf-8")) > _MAX_TOKEN_BYTES:
            raise ValueError("Credential token exceeds the storage limit")
        credential_ref = f"{provider}:{connection_id}"
        path = self._path_for(credential_ref, create_parent=True)
        data = {"credential_ref": credential_ref, "token": token}
        serialized = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{connection_id}-",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
                descriptor = -1
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            _make_private(temporary_path, directory=False)
            os.replace(temporary_path, path)
            _make_private(path, directory=False)
            _fsync_directory(path.parent)
        except Exception:
            if descriptor >= 0:
                os.close(descriptor)
            temporary_path.unlink(missing_ok=True)
            raise
        return credential_ref

    def get(self, credential_ref: str) -> str:
        """Retrieve a token by credential_ref. Raises if not found."""
        path = self._path_for(credential_ref)
        if not path.is_file():
            raise FileNotFoundError(f"Credential not found: {credential_ref}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CredentialStoreError(f"Credential file is unreadable: {credential_ref}") from exc
        if not isinstance(data, dict) or data.get("credential_ref") != credential_ref:
            raise CredentialStoreError(f"Credential file identity mismatch: {credential_ref}")
        token = data.get("token")
        if not isinstance(token, str) or not token:
            raise CredentialStoreError(f"Credential file has no usable token: {credential_ref}")
        if len(token.encode("utf-8")) > _MAX_TOKEN_BYTES:
            raise CredentialStoreError(f"Credential file exceeds the token limit: {credential_ref}")
        return token

    def delete(self, credential_ref: str) -> bool:
        """Delete a credential. Returns True if deleted."""
        path = self._path_for(credential_ref)
        if path.exists():
            path.unlink()
            return True
        return False

    def exists(self, credential_ref: str) -> bool:
        return self._path_for(credential_ref).is_file()


def _parse_credential_ref(credential_ref: str) -> tuple[str, str]:
    if not isinstance(credential_ref, str) or credential_ref.count(":") != 1:
        raise ValueError("Credential reference must use provider:connection_id")
    provider, connection_id = credential_ref.split(":", 1)
    _validate_reference_segment(provider, "provider")
    _validate_reference_segment(connection_id, "connection_id")
    return provider, connection_id


def _validate_reference_segment(value: str, label: str) -> None:
    if not isinstance(value, str) or _REFERENCE_SEGMENT.fullmatch(value) is None:
        raise ValueError(f"Invalid credential {label}")


def _make_private(path: Path, *, directory: bool) -> None:
    if os.name != "nt":
        path.chmod(0o700 if directory else 0o600)


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
