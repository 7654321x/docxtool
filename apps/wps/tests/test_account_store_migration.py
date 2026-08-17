from __future__ import annotations

import sqlite3

import pytest

from apps.wps import account_store


def _create_legacy_account(path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            """CREATE TABLE local_account (
                singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                server_origin TEXT NOT NULL,
                username TEXT NOT NULL,
                user_id TEXT NOT NULL DEFAULT '',
                device_id TEXT NOT NULL DEFAULT '',
                password_cipher BLOB NOT NULL,
                session_token_cipher BLOB NOT NULL,
                device_key_cipher BLOB NOT NULL,
                session_expires_at INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL
            )"""
        )
        conn.execute(
            """INSERT INTO local_account VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "https://legacy.invalid",
                "User01",
                "wusr_1",
                "wdev_1",
                b"password",
                b"session",
                b"device",
                86400,
                1,
            ),
        )


def test_legacy_server_origin_migration_removes_column_and_preserves_account(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path = account_store.local_account_path()
    _create_legacy_account(path)

    conn = account_store._connect()
    try:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(local_account)")}
        account = conn.execute("SELECT username, user_id, device_id FROM local_account").fetchone()
    finally:
        conn.close()

    assert "server_origin" not in columns
    assert tuple(account) == ("User01", "wusr_1", "wdev_1")


def test_legacy_server_origin_migration_removes_stale_rebuild_table(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path = account_store.local_account_path()
    _create_legacy_account(path)
    with sqlite3.connect(str(path)) as conn:
        conn.execute("CREATE TABLE local_account_rebuilt (stale INTEGER)")

    conn = account_store._connect()
    conn.close()

    with sqlite3.connect(str(path)) as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='local_account_rebuilt'"
        ).fetchone() is None


def test_legacy_server_origin_migration_rolls_back_on_failure(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path = account_store.local_account_path()
    _create_legacy_account(path)
    original_create = account_store._create_local_account_table

    def create_with_failing_insert(conn, table_name="local_account"):
        original_create(conn, table_name)
        if table_name == "local_account_rebuilt":
            conn.execute(
                """CREATE TRIGGER reject_legacy_rebuild_insert
                   BEFORE INSERT ON local_account_rebuilt
                   BEGIN
                     SELECT RAISE(ABORT, 'reject legacy rebuild insert');
                   END"""
            )

    monkeypatch.setattr(account_store, "_create_local_account_table", create_with_failing_insert)

    with pytest.raises(sqlite3.IntegrityError, match="reject legacy rebuild insert"):
        account_store._connect()

    with sqlite3.connect(str(path)) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(local_account)")}
        account = conn.execute("SELECT server_origin, username FROM local_account").fetchone()

    assert "server_origin" in columns
    assert account == ("https://legacy.invalid", "User01")
