import sqlite3
import threading

import pytest

from docxtool.web import app as server
from docxtool.wps_server import database
from docxtool.wps_server.config import require_separate_database_paths


def _factory(path):
    return lambda: database.connect(path)


def test_wps_database_creates_only_four_core_tables(tmp_path):
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
    }
    assert version == 1


def test_wps_database_rejects_newer_schema(tmp_path):
    path = tmp_path / "wps_plugin.db"
    with sqlite3.connect(str(path)) as conn:
        conn.execute("PRAGMA user_version=2")

    try:
        database.initialize_database(_factory(path), threading.Lock())
    except RuntimeError as exc:
        assert str(exc) == "WPS_DATABASE_VERSION_UNSUPPORTED"
    else:
        raise AssertionError("newer WPS schema must fail fast")


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
