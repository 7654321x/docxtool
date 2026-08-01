from __future__ import annotations

import sqlite3
import tempfile
import threading
from collections import OrderedDict
from pathlib import Path

import pytest

from docxtool.web.rate_limits import (
    allow,
    auth_rate_allow,
    ban_ip,
    banned_ips,
    ip_activity,
    ip_upload_count,
    is_ip_banned,
    limit_settings,
    save_limit_settings,
    settings_get,
    settings_set,
    unban_ip,
    upload_limit_exceeded,
)


def _connect_factory(path: Path):
    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    return connect


def _init_db(connect) -> None:
    conn = connect()
    conn.executescript(
        """
        CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE banned_ips(ip TEXT PRIMARY KEY, reason TEXT, created_at TEXT);
        CREATE TABLE tasks(
            id TEXT PRIMARY KEY,
            ip TEXT,
            filename TEXT,
            status TEXT,
            created_at TEXT,
            done_at TEXT
        );
        """
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def db_tools():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "stats.db"
        connect = _connect_factory(path)
        _init_db(connect)
        yield connect, threading.Lock()


def test_allow_uses_time_window() -> None:
    rate_limit: dict[str, float] = {}
    lock = threading.Lock()

    assert allow("203.0.113.8", rate_limit=rate_limit, rate_lock=lock, rate_window=2, now=10)
    assert not allow("203.0.113.8", rate_limit=rate_limit, rate_lock=lock, rate_window=2, now=11)
    assert allow("203.0.113.8", rate_limit=rate_limit, rate_lock=lock, rate_window=2, now=13)


def test_auth_rate_allow_prunes_window_and_old_buckets() -> None:
    buckets: OrderedDict[str, list[float]] = OrderedDict()
    lock = threading.Lock()

    assert auth_rate_allow("login", "user", 10, 2, auth_rate_limit=buckets, rate_lock=lock, now=100) == (True, 0)
    assert auth_rate_allow("login", "user", 10, 2, auth_rate_limit=buckets, rate_lock=lock, now=101) == (True, 0)
    allowed, retry = auth_rate_allow("login", "user", 10, 2, auth_rate_limit=buckets, rate_lock=lock, now=102)
    assert not allowed
    assert retry == 8
    assert auth_rate_allow("login", "user", 10, 2, auth_rate_limit=buckets, rate_lock=lock, now=111) == (True, 0)


def test_settings_and_upload_limit_are_persisted(db_tools) -> None:
    connect, lock = db_tools

    assert settings_get("missing", "fallback", connect=connect, sql_lock=lock) == "fallback"
    settings_set("custom", "value", connect=connect, sql_lock=lock)
    assert settings_get("custom", "", connect=connect, sql_lock=lock) == "value"

    assert limit_settings(connect=connect, sql_lock=lock, default_window_seconds=3600, default_count=10) == {
        "enabled": False,
        "window_seconds": 3600,
        "count": 10,
    }
    save_limit_settings(True, 1800, 2, connect=connect, sql_lock=lock)
    assert limit_settings(connect=connect, sql_lock=lock, default_window_seconds=3600, default_count=10) == {
        "enabled": True,
        "window_seconds": 1800,
        "count": 2,
    }


def test_ban_unban_and_activity_queries(db_tools) -> None:
    connect, lock = db_tools
    conn = connect()
    conn.executemany(
        "INSERT INTO tasks(id, ip, filename, status, created_at, done_at) VALUES(?,?,?,?,?,?)",
        [
            ("t1", "203.0.113.8", "a.docx", "done", "2026-01-01 10:00:00", "2026-01-01 10:01:00"),
            ("t2", "203.0.113.8", "b.docx", "error", "2026-01-01 11:00:00", "2026-01-01 11:01:00"),
            ("t3", "198.51.100.2", "c.docx", "done", "2026-01-01 12:00:00", "2026-01-01 12:01:00"),
        ],
    )
    conn.commit()
    conn.close()

    assert not is_ip_banned("203.0.113.8", connect=connect, sql_lock=lock)
    ban_ip("203.0.113.8", "manual test", connect=connect, sql_lock=lock)
    assert is_ip_banned("203.0.113.8", connect=connect, sql_lock=lock)
    assert banned_ips(connect=connect, sql_lock=lock)[0]["reason"] == "manual test"
    with pytest.raises(ValueError):
        ban_ip("not-an-ip", connect=connect, sql_lock=lock)

    assert [row["filename"] for row in ip_activity("203.0.113.8", connect=connect, sql_lock=lock)] == ["b.docx", "a.docx"]
    assert ip_upload_count("203.0.113.8", connect=connect, sql_lock=lock) == 2

    unban_ip("203.0.113.8", connect=connect, sql_lock=lock)
    assert not is_ip_banned("203.0.113.8", connect=connect, sql_lock=lock)


def test_upload_limit_exceeded_respects_enabled_flag(db_tools) -> None:
    connect, lock = db_tools
    conn = connect()
    conn.executemany(
        "INSERT INTO tasks(id, ip, filename, status, created_at, done_at) VALUES(?,?,?,?,datetime('now','localtime'),datetime('now','localtime'))",
        [
            ("t1", "203.0.113.8", "a.docx", "done"),
            ("t2", "203.0.113.8", "b.docx", "done"),
        ],
    )
    conn.commit()
    conn.close()

    assert not upload_limit_exceeded(
        "203.0.113.8",
        connect=connect,
        sql_lock=lock,
        default_window_seconds=3600,
        default_count=1,
    )
    save_limit_settings(True, 3600, 1, connect=connect, sql_lock=lock)
    assert upload_limit_exceeded(
        "203.0.113.8",
        connect=connect,
        sql_lock=lock,
        default_window_seconds=3600,
        default_count=1,
    )
