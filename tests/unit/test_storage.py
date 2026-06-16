from pathlib import Path

from sqlalchemy import inspect

from storage.db import init_db, reset_engine_for_tests
from storage.file_store import ensure_webfa_data_dir


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
    }.issubset(tables)
