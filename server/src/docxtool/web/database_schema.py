"""Web SQLite schema initialization and lightweight migrations."""

from __future__ import annotations

from collections.abc import Callable
from threading import Lock


TASKS_EXTRA_COLUMNS = {
    "log_filename": "TEXT DEFAULT ''",
    "log_path": "TEXT DEFAULT ''",
    "output_dir": "TEXT DEFAULT ''",
    "output_filename": "TEXT DEFAULT ''",
    "output_path": "TEXT DEFAULT ''",
    "started_at": "TEXT DEFAULT ''",
    "finished_at": "TEXT DEFAULT ''",
    "client_ip": "TEXT DEFAULT ''",
    "error_code": "TEXT DEFAULT ''",
    "error_message": "TEXT DEFAULT ''",
    "progress": "INTEGER DEFAULT 0",
    "message": "TEXT DEFAULT ''",
    "processing_options": "TEXT DEFAULT ''",
    "preset_id": "TEXT DEFAULT ''",
    "original_filename": "TEXT DEFAULT ''",
    "safe_download_filename": "TEXT DEFAULT ''",
    "input_size": "INTEGER DEFAULT 0",
    "owner_id": "TEXT DEFAULT ''",
}

PRESETS_EXTRA_COLUMNS = {
    "is_system": "INTEGER DEFAULT 0",
    "is_default": "INTEGER DEFAULT 0",
    "version": "INTEGER DEFAULT 1",
    "created_at": "TEXT DEFAULT (datetime('now','localtime'))",
    "updated_at": "TEXT DEFAULT (datetime('now','localtime'))",
    "owner_id": "TEXT DEFAULT ''",
    "visibility": "TEXT DEFAULT 'public'",
}


def initialize_web_database(connect: Callable, sql_lock: Lock, seed_default_presets: Callable) -> None:
    """传入连接工厂、线程锁和默认模板种子函数，完成 Web 数据库建表、迁移和初始化。"""
    with sql_lock:
        conn = connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, ip TEXT NOT NULL, ua TEXT DEFAULT '',
                    filename TEXT DEFAULT '', file_size INTEGER DEFAULT 0,
                    doc_type TEXT DEFAULT '', paragraphs INTEGER DEFAULT 0,
                    headings INTEGER DEFAULT 0, body INTEGER DEFAULT 0,
                    duration_ms INTEGER DEFAULT 0, status TEXT DEFAULT 'pending',
                    error TEXT DEFAULT '',
                    log_filename TEXT DEFAULT '', log_path TEXT DEFAULT '',
                    output_dir TEXT DEFAULT '', output_filename TEXT DEFAULT '',
                    output_path TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now','localtime')),
                    started_at TEXT DEFAULT '',
                    finished_at TEXT DEFAULT '',
                    client_ip TEXT DEFAULT '',
                    error_code TEXT DEFAULT '',
                    error_message TEXT DEFAULT '',
                    progress INTEGER DEFAULT 0,
                    message TEXT DEFAULT '',
                    processing_options TEXT DEFAULT '',
                    preset_id TEXT DEFAULT '',
                    original_filename TEXT DEFAULT '',
                    safe_download_filename TEXT DEFAULT '',
                    input_size INTEGER DEFAULT 0,
                    done_at TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS daily_stats (
                    date TEXT PRIMARY KEY, total INTEGER DEFAULT 0,
                    done INTEGER DEFAULT 0, error INTEGER DEFAULT 0,
                    total_bytes INTEGER DEFAULT 0, total_ms INTEGER DEFAULT 0,
                    unique_ips INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS banned_ips (
                    ip TEXT PRIMARY KEY,
                    reason TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now','localtime'))
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS presets (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    config_json TEXT NOT NULL,
                    is_system INTEGER DEFAULT 0,
                    is_default INTEGER DEFAULT 0,
                    owner_id TEXT DEFAULT '',
                    visibility TEXT DEFAULT 'public',
                    version INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT (datetime('now','localtime')),
                    updated_at TEXT DEFAULT (datetime('now','localtime'))
                );
                CREATE TABLE IF NOT EXISTS admin_sessions (
                    session_id TEXT PRIMARY KEY,
                    csrf_token TEXT NOT NULL,
                    user_agent TEXT DEFAULT '',
                    remote_ip TEXT DEFAULT '',
                    created_at INTEGER NOT NULL,
                    last_seen_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, username TEXT NOT NULL, username_norm TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL, display_name TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active', created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL, last_login_at INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS user_sessions (
                    session_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, csrf_token TEXT NOT NULL,
                    created_at INTEGER NOT NULL, last_seen_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL, user_agent TEXT NOT NULL DEFAULT '', remote_ip TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_ip ON tasks(ip);
                CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);
                CREATE INDEX IF NOT EXISTS idx_tasks_ip_created ON tasks(ip, created_at);
                CREATE INDEX IF NOT EXISTS idx_admin_sessions_expires ON admin_sessions(expires_at);
                """
            )
            _add_missing_columns(conn, "tasks", TASKS_EXTRA_COLUMNS)
            _add_missing_columns(conn, "presets", PRESETS_EXTRA_COLUMNS)
            _normalize_existing_preset_rows(conn)
            _create_compatibility_indexes(conn)
            conn.commit()
            seed_default_presets(conn)
        finally:
            conn.close()


def _add_missing_columns(conn, table_name: str, columns: dict[str, str]) -> None:
    """传入连接、表名和列定义映射，为旧库补齐缺失列并返回 None。"""
    existing = _table_columns(conn, table_name)
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {name} {definition}")


def _table_columns(conn, table_name: str) -> set[str]:
    """传入 SQLite 连接和表名，返回该表当前列名集合。"""
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _normalize_existing_preset_rows(conn) -> None:
    """传入 SQLite 连接，归一旧 presets 行的 owner_id 和 visibility 默认值。"""
    conn.execute("UPDATE presets SET owner_id='' WHERE owner_id IS NULL")
    conn.execute("UPDATE presets SET visibility='public' WHERE visibility IS NULL OR visibility=''")


def _create_compatibility_indexes(conn) -> None:
    """传入 SQLite 连接，创建迁移后查询路径需要的兼容索引。"""
    conn.execute("CREATE INDEX IF NOT EXISTS idx_presets_owner_visibility ON presets(owner_id, visibility)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_owner_created ON tasks(owner_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_user_sessions_expires ON user_sessions(expires_at)")
