from __future__ import annotations

import errno
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Iterator

from sqlalchemy import Engine, create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from storage.file_store import ensure_webfa_data_dir
from storage.models import Base, ProviderConnection, StorageMigrationRecord, Transaction

_ENGINE: Engine | None = None
_SESSION_FACTORY: sessionmaker[Session] | None = None
_ENGINE_INIT_LOCK = threading.Lock()
_STORAGE_INIT_THREAD_LOCK = threading.Lock()


def get_database_path() -> Path:
    return ensure_webfa_data_dir()["db"]


def get_database_url() -> str:
    return f"sqlite:///{get_database_path()}"


def get_engine() -> Engine:
    global _ENGINE, _SESSION_FACTORY
    if _ENGINE is not None:
        return _ENGINE
    with _ENGINE_INIT_LOCK:
        if _ENGINE is not None:
            return _ENGINE
        engine = create_engine(
            get_database_url(),
            future=True,
            connect_args={"check_same_thread": False},
        )
        event.listen(engine, "connect", _configure_sqlite_connection)
        _ENGINE = engine
        _SESSION_FACTORY = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    return _ENGINE


def reset_engine_for_tests() -> None:
    global _ENGINE, _SESSION_FACTORY
    with _ENGINE_INIT_LOCK:
        if _ENGINE is not None:
            _ENGINE.dispose()
        _ENGINE = None
        _SESSION_FACTORY = None


def init_db() -> Path:
    paths = ensure_webfa_data_dir()
    with _storage_init_lock(paths["tmp"] / "storage-init.lock"):
        engine = get_engine()
        Base.metadata.create_all(engine)
        with session_scope() as session:
            _record_storage_migration(session, "p12_001_profile_catalog")
            _seed_provider_placeholders(session)
    return paths["db"]


def record_storage_migration(migration_id: str) -> None:
    with session_scope() as session:
        _record_storage_migration(session, migration_id)


def _record_storage_migration(session: Session, migration_id: str) -> None:
    if session.get(StorageMigrationRecord, migration_id) is None:
        session.add(StorageMigrationRecord(migration_id=migration_id))


def seed_provider_placeholders() -> None:
    with session_scope() as session:
        _seed_provider_placeholders(session)


def _seed_provider_placeholders(session: Session) -> None:
    existing = {row.provider for row in session.scalars(select(ProviderConnection)).all()}
    for provider in ["github", "huggingface"]:
        if provider not in existing:
            session.add(ProviderConnection(provider=provider, status="disconnected", auth_mode=None))


def upsert_transactions(definitions: list[dict]) -> None:
    with session_scope() as session:
        for definition in definitions:
            transaction = session.get(Transaction, definition["id"])
            if transaction is None:
                transaction = Transaction(
                    id=definition["id"],
                    provider=definition["provider"],
                    name=definition.get("name", definition["id"]),
                    risk=definition.get("risk", "unknown"),
                    definition_json=definition,
                    enabled=True,
                )
                session.add(transaction)
            else:
                transaction.provider = definition["provider"]
                transaction.name = definition.get("name", definition["id"])
                transaction.risk = definition.get("risk", "unknown")
                transaction.definition_json = definition
                transaction.enabled = True


@contextmanager
def session_scope() -> Iterator[Session]:
    if _SESSION_FACTORY is None:
        get_engine()
    assert _SESSION_FACTORY is not None
    session = _SESSION_FACTORY()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
    """Apply integrity settings to every pooled SQLite connection."""

    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


@contextmanager
def _storage_init_lock(lock_path: Path, timeout_seconds: float = 30.0) -> Iterator[None]:
    """Serialize additive schema initialization across threads and processes."""

    with _STORAGE_INIT_THREAD_LOCK:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = lock_path.open("a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            deadline = time.monotonic() + timeout_seconds
            while True:
                try:
                    _try_lock_file(handle)
                    break
                except (BlockingIOError, OSError) as exc:
                    if not _lock_is_busy(exc):
                        raise RuntimeError("failed acquiring WebFA storage initialization lock") from exc
                    if time.monotonic() >= deadline:
                        raise RuntimeError("timed out acquiring WebFA storage initialization lock") from exc
                    time.sleep(0.05)
            try:
                yield
            finally:
                _unlock_file(handle)
        finally:
            handle.close()


def _try_lock_file(handle: IO[bytes]) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(handle: IO[bytes]) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _lock_is_busy(exc: OSError) -> bool:
    return isinstance(exc, BlockingIOError) or exc.errno in {
        errno.EACCES,
        errno.EAGAIN,
        getattr(errno, "EDEADLK", -1),
    }
