from __future__ import annotations

import os
from pathlib import Path

import pytest

from storage.credential_store import CredentialStore, CredentialStoreError


def test_credential_store_rejects_reference_escape(tmp_path: Path):
    base = tmp_path / "credentials"
    store = CredentialStore(base)

    with pytest.raises(ValueError, match="provider"):
        store.put("../escaped", "secret")
    with pytest.raises(ValueError, match="connection_id"):
        store.put("github", "secret", "../escaped")
    with pytest.raises(ValueError, match="provider:connection_id"):
        store.get("github")
    with pytest.raises(ValueError, match="provider:connection_id"):
        store.exists("github:default:extra")

    assert not (tmp_path / "escaped").exists()


def test_credential_store_reads_do_not_create_provider_directories(tmp_path: Path):
    base = tmp_path / "credentials"
    store = CredentialStore(base)

    assert store.exists("github:default") is False
    with pytest.raises(FileNotFoundError):
        store.get("github:default")

    assert not (base / "github").exists()


def test_credential_store_atomic_replace_preserves_previous_token(monkeypatch, tmp_path: Path):
    store = CredentialStore(tmp_path / "credentials")
    store.put("github", "previous-secret")

    def fail_replace(_source, _destination):
        raise OSError("forced replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError, match="forced replace failure"):
        store.put("github", "replacement-secret")

    assert store.get("github:default") == "previous-secret"
    assert list((tmp_path / "credentials" / "github").glob("*.tmp")) == []


def test_credential_store_rejects_symlink_and_identity_mismatch(tmp_path: Path):
    store = CredentialStore(tmp_path / "credentials")
    store.put("github", "secret")
    credential_path = tmp_path / "credentials" / "github" / "default.json"
    credential_path.write_text(
        '{"credential_ref":"github:other","token":"secret"}',
        encoding="utf-8",
    )

    with pytest.raises(CredentialStoreError, match="identity mismatch"):
        store.get("github:default")


def test_credential_store_bounds_token_size(tmp_path: Path):
    store = CredentialStore(tmp_path / "credentials")

    with pytest.raises(ValueError, match="non-empty"):
        store.put("github", "")
    with pytest.raises(ValueError, match="storage limit"):
        store.put("github", "x" * (16 * 1024 + 1))


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are not Windows ACLs")
def test_credential_store_uses_private_posix_permissions(tmp_path: Path):
    base = tmp_path / "credentials"
    store = CredentialStore(base)
    store.put("github", "secret")

    assert base.stat().st_mode & 0o777 == 0o700
    assert (base / "github").stat().st_mode & 0o777 == 0o700
    assert (base / "github" / "default.json").stat().st_mode & 0o777 == 0o600
