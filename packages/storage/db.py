from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from storage.file_store import ensure_webfa_data_dir
from storage.models import Base, ProviderConnection, Transaction

_ENGINE: Engine | None = None
_SESSION_FACTORY: sessionmaker[Session] | None = None


def get_database_path() -> Path:
    return ensure_webfa_data_dir()["db"]


def get_database_url() -> str:
    return f"sqlite:///{get_database_path()}"


def get_engine() -> Engine:
    global _ENGINE, _SESSION_FACTORY
    if _ENGINE is None:
        _ENGINE = create_engine(get_database_url(), future=True, connect_args={"check_same_thread": False})
        _SESSION_FACTORY = sessionmaker(bind=_ENGINE, expire_on_commit=False, future=True)
    return _ENGINE


def reset_engine_for_tests() -> None:
    global _ENGINE, _SESSION_FACTORY
    if _ENGINE is not None:
        _ENGINE.dispose()
    _ENGINE = None
    _SESSION_FACTORY = None


def init_db() -> Path:
    paths = ensure_webfa_data_dir()
    engine = get_engine()
    Base.metadata.create_all(engine)
    seed_provider_placeholders()
    return paths["db"]


def seed_provider_placeholders() -> None:
    with session_scope() as session:
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
