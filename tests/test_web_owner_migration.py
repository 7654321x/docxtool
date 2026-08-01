from __future__ import annotations

import sqlite3
import tempfile
import threading
from pathlib import Path

from docxtool.web.owner_migration import (
    is_anonymous_owner_id,
    migrate_anonymous_owner,
    migrate_anonymous_resources,
)


ANON_ID = "usr_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
USER_ID = "usr_real_user"


def _connect_factory(path: Path):
    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    return connect


def _init_db(connect) -> None:
    conn = connect()
    conn.execute("CREATE TABLE tasks(id TEXT PRIMARY KEY, owner_id TEXT)")
    conn.execute(
        """
        CREATE TABLE presets(
            id TEXT PRIMARY KEY,
            name TEXT,
            owner_id TEXT,
            visibility TEXT,
            created_at INTEGER
        )
        """
    )
    conn.commit()
    conn.close()


def _seed_rows(connect) -> None:
    conn = connect()
    conn.executemany(
        "INSERT INTO tasks(id, owner_id) VALUES(?,?)",
        [("task-anon", ANON_ID), ("task-user", USER_ID), ("task-other", "usr_other")],
    )
    conn.executemany(
        "INSERT INTO presets(id, name, owner_id, visibility, created_at) VALUES(?,?,?,?,?)",
        [
            ("existing", "常用模板", USER_ID, "private", 1),
            ("anon-conflict", "常用模板", ANON_ID, "private", 2),
            ("anon-unique", "匿名模板", ANON_ID, "private", 3),
            ("anon-public", "公开模板", ANON_ID, "public", 4),
        ],
    )
    conn.commit()
    conn.close()


def test_is_anonymous_owner_id_validates_shape() -> None:
    assert is_anonymous_owner_id(ANON_ID)
    assert not is_anonymous_owner_id("usr_not_hex")
    assert not is_anonymous_owner_id(USER_ID)


def test_migrate_anonymous_owner_moves_tasks_and_private_presets() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        connect = _connect_factory(Path(tmp) / "owner.db")
        _init_db(connect)
        _seed_rows(connect)
        conn = connect()
        migrate_anonymous_owner(conn, ANON_ID, USER_ID)
        conn.commit()
        tasks = conn.execute("SELECT id, owner_id FROM tasks ORDER BY id").fetchall()
        presets = conn.execute("SELECT id, name, owner_id FROM presets ORDER BY id").fetchall()
        conn.close()

    task_map = {row["id"]: row["owner_id"] for row in tasks}
    preset_map = {row["id"]: (row["name"], row["owner_id"]) for row in presets}
    assert task_map["task-anon"] == USER_ID
    assert task_map["task-user"] == USER_ID
    assert preset_map["anon-conflict"] == ("常用模板（导入 2）", USER_ID)
    assert preset_map["anon-unique"] == ("匿名模板", USER_ID)
    assert preset_map["anon-public"] == ("公开模板", ANON_ID)


def test_invalid_anonymous_owner_does_not_move_rows() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        connect = _connect_factory(Path(tmp) / "owner.db")
        _init_db(connect)
        _seed_rows(connect)
        conn = connect()
        migrate_anonymous_owner(conn, "invalid", USER_ID)
        conn.commit()
        task_owner = conn.execute("SELECT owner_id FROM tasks WHERE id='task-anon'").fetchone()[0]
        preset_owner = conn.execute("SELECT owner_id FROM presets WHERE id='anon-unique'").fetchone()[0]
        conn.close()

    assert task_owner == ANON_ID
    assert preset_owner == ANON_ID


def test_migrate_anonymous_resources_opens_transaction() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        connect = _connect_factory(Path(tmp) / "owner.db")
        _init_db(connect)
        _seed_rows(connect)

        migrate_anonymous_resources(ANON_ID, USER_ID, connect=connect, sql_lock=threading.Lock())

        conn = connect()
        owner = conn.execute("SELECT owner_id FROM tasks WHERE id='task-anon'").fetchone()[0]
        conn.close()

    assert owner == USER_ID
