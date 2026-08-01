from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from docxtool.web.database_schema import initialize_web_database


def _connect_factory(db_path: Path):
    """传入数据库路径，返回带 Row 工厂的连接构造函数。"""

    def connect():
        """无需传入数据，返回测试用 SQLite 连接。"""
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    return connect


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    """传入连接和表名，返回当前测试库中的列名集合。"""
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def test_initialize_web_database_creates_core_tables_and_indexes(tmp_path: Path) -> None:
    db_path = tmp_path / "stats.db"
    seeded = []

    def seed_default_presets(conn: sqlite3.Connection) -> None:
        """传入初始化后的连接，记录 seed 调用并插入默认模板。"""
        seeded.append(True)
        conn.execute(
            """INSERT INTO presets(id, name, config_json, is_system, is_default)
               VALUES(?,?,?,?,?)""",
            ("official_document", "党政机关公文格式", "{}", 1, 1),
        )
        conn.commit()

    initialize_web_database(_connect_factory(db_path), threading.Lock(), seed_default_presets)

    conn = _connect_factory(db_path)()
    try:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        indexes = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        }
        preset = conn.execute("SELECT id,is_system,is_default FROM presets WHERE id=?", ("official_document",)).fetchone()
    finally:
        conn.close()

    assert seeded == [True]
    assert {"tasks", "daily_stats", "banned_ips", "settings", "presets", "users", "user_sessions"} <= tables
    assert {"idx_tasks_ip", "idx_tasks_created", "idx_presets_owner_visibility"} <= indexes
    assert dict(preset) == {"id": "official_document", "is_system": 1, "is_default": 1}


def test_initialize_web_database_migrates_legacy_presets_without_losing_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    conn = _connect_factory(db_path)()
    try:
        conn.execute(
            """CREATE TABLE presets (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                config_json TEXT NOT NULL,
                is_system INTEGER DEFAULT 0,
                is_default INTEGER DEFAULT 0,
                version INTEGER DEFAULT 1,
                created_at TEXT DEFAULT '',
                updated_at TEXT DEFAULT ''
            )"""
        )
        conn.execute(
            "INSERT INTO presets(id, name, config_json) VALUES(?,?,?)",
            ("legacy", "旧模板", "{}"),
        )
        conn.commit()
    finally:
        conn.close()

    def seed_default_presets(conn: sqlite3.Connection) -> None:
        """传入迁移后的连接，模拟旧逻辑在已有库中插入默认模板。"""
        conn.execute(
            "INSERT INTO presets(id, name, config_json, is_system, is_default) VALUES(?,?,?,?,?)",
            ("official_document", "党政机关公文格式", "{}", 1, 1),
        )
        conn.commit()

    initialize_web_database(_connect_factory(db_path), threading.Lock(), seed_default_presets)

    conn = _connect_factory(db_path)()
    try:
        columns = _table_columns(conn, "presets")
        rows = {
            row["id"]: (row["owner_id"], row["visibility"])
            for row in conn.execute("SELECT id, owner_id, visibility FROM presets").fetchall()
        }
    finally:
        conn.close()

    assert {"owner_id", "visibility"} <= columns
    assert rows["legacy"] == ("", "public")
    assert rows["official_document"] == ("", "public")


def test_initialize_web_database_adds_task_owner_column_for_existing_tasks(tmp_path: Path) -> None:
    db_path = tmp_path / "tasks.db"
    conn = _connect_factory(db_path)()
    try:
        conn.execute(
            """CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                ip TEXT NOT NULL,
                created_at TEXT DEFAULT ''
            )"""
        )
        conn.execute("INSERT INTO tasks(id, ip, created_at) VALUES(?,?,?)", ("t1", "127.0.0.1", "now"))
        conn.commit()
    finally:
        conn.close()

    def seed_default_presets(conn: sqlite3.Connection) -> None:
        """传入连接，测试任务表迁移时不需要写入额外数据。"""
        return None

    initialize_web_database(_connect_factory(db_path), threading.Lock(), seed_default_presets)

    conn = _connect_factory(db_path)()
    try:
        columns = _table_columns(conn, "tasks")
        row = conn.execute("SELECT id, owner_id FROM tasks WHERE id='t1'").fetchone()
    finally:
        conn.close()

    assert "owner_id" in columns
    assert dict(row) == {"id": "t1", "owner_id": ""}
