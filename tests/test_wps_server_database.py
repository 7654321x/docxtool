import sqlite3
import threading

import pytest

from docxtool.web import app as server
from docxtool.wps_server import database
from docxtool.wps_server.config import (
    require_separate_database_paths,
    resolve_wps_admin_mutations_enabled,
)


def _factory(path):
    return lambda: database.connect(path)


def _downgrade_to_v1(path) -> None:
    """Create the exact pre-Phase-B shape needed to exercise the forward migration."""
    with sqlite3.connect(str(path)) as conn:
        conn.execute("DROP INDEX IF EXISTS idx_wps_notifications_user_pending_time")
        conn.execute("DROP INDEX IF EXISTS idx_wps_notifications_pending_time")
        conn.execute("DROP TABLE IF EXISTS wps_notifications")
        conn.execute("DROP INDEX IF EXISTS idx_wps_admin_audit_target_time")
        conn.execute("DROP INDEX IF EXISTS idx_wps_admin_audit_event_time")
        conn.execute("DROP TABLE IF EXISTS wps_admin_audit_logs")
        conn.execute("PRAGMA user_version=1")
        conn.commit()


def _downgrade_to_v2(path) -> None:
    """Restore the Phase-B shape needed to exercise the v2-to-v3 migration."""
    with sqlite3.connect(str(path)) as conn:
        conn.execute("DROP INDEX IF EXISTS idx_wps_notifications_user_pending_time")
        conn.execute("DROP INDEX IF EXISTS idx_wps_notifications_pending_time")
        conn.execute("DROP TABLE IF EXISTS wps_notifications")
        conn.execute("PRAGMA user_version=2")
        conn.commit()


def test_wps_database_creates_core_admin_audit_and_notification_tables(tmp_path):
    path = tmp_path / "wps_plugin.db"
    connect = _factory(path)
    database.initialize_database(connect, threading.Lock())

    with sqlite3.connect(str(path)) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        version = conn.execute("PRAGMA user_version").fetchone()[0]

    assert tables == {
        "wps_users",
        "wps_devices",
        "wps_sessions",
        "wps_format_requests",
        "wps_admin_audit_logs",
        "wps_notifications",
    }
    assert version == 4
    with sqlite3.connect(str(path)) as conn:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(wps_format_requests)")
        }
    assert "document_name" in columns


def test_wps_database_rejects_newer_schema(tmp_path):
    path = tmp_path / "wps_plugin.db"
    with sqlite3.connect(str(path)) as conn:
        conn.execute("PRAGMA user_version=5")

    try:
        database.initialize_database(_factory(path), threading.Lock())
    except RuntimeError as exc:
        assert str(exc) == "WPS_DATABASE_VERSION_UNSUPPORTED"
    else:
        raise AssertionError("newer WPS schema must fail fast")


def test_wps_database_migrates_v1_without_losing_existing_rows(tmp_path):
    path = tmp_path / "wps_plugin.db"
    connect = _factory(path)
    database.initialize_database(connect, threading.Lock())
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            """INSERT INTO wps_users
               (id,username,username_norm,password_hash,status,created_at,updated_at,last_login_at)
               VALUES ('wusr_legacy','Legacy01','legacy01','hash','active',1,1,1)"""
        )
        conn.commit()
    _downgrade_to_v1(path)

    database.initialize_database(connect, threading.Lock())

    with sqlite3.connect(str(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
        assert conn.execute("SELECT username FROM wps_users").fetchone()[0] == "Legacy01"
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='wps_admin_audit_logs'"
        ).fetchone()
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='wps_notifications'"
        ).fetchone()
        assert "document_name" in {
            row[1] for row in conn.execute("PRAGMA table_info(wps_format_requests)")
        }


def test_wps_database_v1_migration_failure_rolls_back(tmp_path, monkeypatch, caplog):
    path = tmp_path / "wps_plugin.db"
    connect = _factory(path)
    database.initialize_database(connect, threading.Lock())
    _downgrade_to_v1(path)
    caplog.set_level("INFO", logger="docx_tool")
    monkeypatch.setattr(
        database,
        "_migrate_v1_to_v2",
        lambda _conn: (_ for _ in ()).throw(RuntimeError("forced migration failure")),
    )

    with pytest.raises(RuntimeError, match="forced migration failure"):
        database.initialize_database(connect, threading.Lock())

    with sqlite3.connect(str(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='wps_admin_audit_logs'"
        ).fetchone() is None
    assert "wps.database.migration.start" in caplog.text
    assert "wps.database.migration.error" in caplog.text


def test_wps_database_v2_to_v3_migration_is_rollback_safe(tmp_path, monkeypatch):
    path = tmp_path / "wps_plugin.db"
    connect = _factory(path)
    database.initialize_database(connect, threading.Lock())
    _downgrade_to_v2(path)
    monkeypatch.setattr(
        database,
        "_migrate_v2_to_v3",
        lambda _conn: (_ for _ in ()).throw(RuntimeError("forced v3 migration failure")),
    )

    with pytest.raises(RuntimeError, match="forced v3 migration failure"):
        database.initialize_database(connect, threading.Lock())

    with sqlite3.connect(str(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='wps_notifications'"
        ).fetchone() is None


def _create_v3_database(path) -> None:
    """Build the exact v3 shape without relying on SQLite DROP COLUMN support."""
    conn = database.connect(path)
    try:
        database._execute_all(conn, database._CORE_SCHEMA_STATEMENTS)
        database._migrate_v1_to_v2(conn)
        database._migrate_v2_to_v3(conn)
        conn.execute("PRAGMA user_version=3")
        conn.commit()
    finally:
        conn.close()


def test_wps_database_v3_to_v4_adds_document_name(tmp_path):
    path = tmp_path / "wps_plugin.db"
    _create_v3_database(path)

    database.initialize_database(_factory(path), threading.Lock())

    with sqlite3.connect(str(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(wps_format_requests)")
        }
    assert "document_name" in columns


def test_wps_database_v3_to_v4_migration_is_rollback_safe(tmp_path, monkeypatch):
    path = tmp_path / "wps_plugin.db"
    _create_v3_database(path)
    monkeypatch.setattr(
        database,
        "_migrate_v3_to_v4",
        lambda _conn: (_ for _ in ()).throw(RuntimeError("forced v4 migration failure")),
    )

    with pytest.raises(RuntimeError, match="forced v4 migration failure"):
        database.initialize_database(_factory(path), threading.Lock())

    with sqlite3.connect(str(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(wps_format_requests)")
        }
    assert "document_name" not in columns


def test_wps_admin_mutation_gate_is_disabled_by_default_and_rejects_invalid_values(monkeypatch):
    monkeypatch.delenv("WPS_ADMIN_MUTATIONS_ENABLED", raising=False)
    assert resolve_wps_admin_mutations_enabled() is False
    assert resolve_wps_admin_mutations_enabled("true") is True
    assert resolve_wps_admin_mutations_enabled("OFF") is False
    with pytest.raises(RuntimeError, match="WPS_ADMIN_MUTATIONS_ENABLED_INVALID"):
        resolve_wps_admin_mutations_enabled("sometimes")


def test_web_and_wps_database_paths_must_be_different(tmp_path):
    database_path = tmp_path / "shared.db"

    with pytest.raises(RuntimeError, match="WPS_DATABASE_PATH_CONFLICT"):
        require_separate_database_paths(database_path, database_path.parent / "." / "shared.db")


def test_sql_init_rejects_database_path_conflict_before_initialization(tmp_path, monkeypatch):
    database_path = tmp_path / "shared.db"
    calls = []
    monkeypatch.setattr(server, "_DB_PATH", database_path)
    monkeypatch.setattr(server, "_WPS_DB_PATH", database_path)
    monkeypatch.setattr(server, "_web_sql_init", lambda: calls.append("web"))
    monkeypatch.setattr(server, "_wps_initialize_database", lambda *_args: calls.append("wps"))

    with pytest.raises(RuntimeError, match="WPS_DATABASE_PATH_CONFLICT"):
        server._sql_init()

    assert calls == []
