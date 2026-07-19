import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from storage.db import get_engine, init_db, reset_engine_for_tests, session_scope
from storage.file_store import ensure_webfa_data_dir
from storage.models import BrowserSessionRecord


ROOT = Path(__file__).resolve().parents[2]


def test_webfa_data_dir_initializes(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    paths = ensure_webfa_data_dir()

    assert paths["config"].exists()
    assert paths["db"].name == "webfa.db"
    for dirname in ["credentials", "proofs", "audits", "artifacts", "logs", "tmp"]:
        assert paths[dirname].is_dir()


def test_sqlite_initializes_minimum_tables(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    db_path = init_db()

    assert db_path.exists()

    from storage.db import get_engine

    tables = set(inspect(get_engine()).get_table_names())
    assert {
        "provider_connections",
        "transactions",
        "workspaces",
        "plans",
        "approvals",
        "executions",
        "execution_steps",
        "proofs",
        "audit_events",
        "browser_profiles",
        "browser_profile_agent_bindings",
        "browser_sessions",
        "browser_profile_runtime_events",
        "storage_migrations",
    }.issubset(tables)


def test_sqlite_enforces_profile_session_foreign_keys(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()
    init_db()

    with get_engine().connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1

    with pytest.raises(IntegrityError):
        with session_scope() as session:
            session.add(
                BrowserSessionRecord(
                    id="session_orphan",
                    profile_id="missing_profile",
                    runtime_generation="generation_test",
                )
            )

    with get_engine().connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM browser_sessions WHERE id = 'session_orphan'")
        ).scalar_one() == 0


def test_engine_initialization_is_singleton_across_threads(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with ThreadPoolExecutor(max_workers=24) as executor:
        engines = list(executor.map(lambda _index: get_engine(), range(96)))

    assert len({id(engine) for engine in engines}) == 1


def test_sqlite_upgrade_from_pre_p12_database_preserves_existing_rows(monkeypatch, tmp_path: Path):
    home = tmp_path / "WebFA"
    home.mkdir()
    db_path = home / "webfa.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE provider_connections (
                id VARCHAR(64) NOT NULL PRIMARY KEY,
                provider VARCHAR(64) NOT NULL UNIQUE,
                auth_mode VARCHAR(64),
                credential_ref VARCHAR(256),
                scopes_json JSON,
                resource_scope_json JSON,
                status VARCHAR(32) NOT NULL,
                last_verified_at DATETIME,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO provider_connections (
                id, provider, auth_mode, status, created_at, updated_at
            ) VALUES (
                'provider-existing', 'github', 'token', 'connected',
                '2026-01-01 00:00:00', '2026-01-01 00:00:00'
            )
            """
        )

    monkeypatch.setenv("WEBFA_HOME", str(home))
    reset_engine_for_tests()
    assert init_db() == db_path
    assert init_db() == db_path

    from storage.db import get_engine

    engine = get_engine()
    tables = set(inspect(engine).get_table_names())
    assert {
        "browser_profiles",
        "browser_profile_agent_bindings",
        "browser_sessions",
        "browser_profile_runtime_events",
        "storage_migrations",
    }.issubset(tables)
    with engine.connect() as connection:
        github = connection.execute(
            text("SELECT id, status, auth_mode FROM provider_connections WHERE provider = 'github'")
        ).one()
        migrations = connection.execute(
            text("SELECT migration_id FROM storage_migrations ORDER BY migration_id")
        ).scalars().all()
    assert github == ("provider-existing", "connected", "token")
    assert migrations == ["p12_001_profile_catalog"]


def test_storage_migration_record_rolls_back_when_seed_fails(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    import storage.db as storage_db

    def fail_seed(_session):
        raise RuntimeError("forced seed failure")

    monkeypatch.setattr(storage_db, "_seed_provider_placeholders", fail_seed)

    with pytest.raises(RuntimeError, match="forced seed failure"):
        init_db()

    with get_engine().connect() as connection:
        migration_count = connection.execute(
            text(
                "SELECT COUNT(*) FROM storage_migrations "
                "WHERE migration_id = 'p12_001_profile_catalog'"
            )
        ).scalar_one()
        provider_count = connection.execute(
            text("SELECT COUNT(*) FROM provider_connections")
        ).scalar_one()

    assert migration_count == 0
    assert provider_count == 0


def test_sqlite_initialization_is_serialized_across_processes(monkeypatch, tmp_path: Path):
    home = tmp_path / "WebFA"
    env = os.environ.copy()
    env["WEBFA_HOME"] = str(home)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), str(ROOT / "packages"), str(ROOT / "packages" / "webfa-core")]
    )
    command = [sys.executable, "-c", "from storage.db import init_db; init_db()"]
    processes = [
        subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(12)
    ]
    results = []
    try:
        for process in processes:
            stdout, stderr = process.communicate(timeout=60)
            results.append((process.returncode, stdout, stderr))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()

    failures = [stderr for returncode, _stdout, stderr in results if returncode != 0]
    assert failures == []

    monkeypatch.setenv("WEBFA_HOME", str(home))
    reset_engine_for_tests()
    from storage.db import get_engine

    with get_engine().connect() as connection:
        migration_count = connection.execute(
            text("SELECT COUNT(*) FROM storage_migrations WHERE migration_id = 'p12_001_profile_catalog'")
        ).scalar_one()
        provider_count = connection.execute(text("SELECT COUNT(*) FROM provider_connections")).scalar_one()
    assert migration_count == 1
    assert provider_count == 2
