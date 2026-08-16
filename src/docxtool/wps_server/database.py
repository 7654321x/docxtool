"""SQLite schema and connection helpers for WPS plugin accounts."""

from __future__ import annotations

import logging
import sqlite3
import time
from typing import Callable

from .config import resolve_wps_database_path

SCHEMA_VERSION = 4
LOGGER = logging.getLogger("docx_tool")

_CORE_SCHEMA_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS wps_users (
        id TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        username_norm TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active'
            CHECK (status IN ('active', 'disabled')),
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        last_login_at INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS wps_devices (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        fingerprint_hash TEXT NOT NULL,
        device_name TEXT NOT NULL DEFAULT '',
        platform TEXT NOT NULL DEFAULT '',
        app_version TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'active'
            CHECK (status IN ('active', 'disabled')),
        created_at INTEGER NOT NULL,
        last_seen_at INTEGER NOT NULL DEFAULT 0,
        last_ip TEXT NOT NULL DEFAULT '',
        UNIQUE (user_id, fingerprint_hash),
        FOREIGN KEY (user_id) REFERENCES wps_users(id)
    )""",
    """CREATE TABLE IF NOT EXISTS wps_sessions (
        session_hash TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        device_id TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        last_seen_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        remote_ip TEXT NOT NULL DEFAULT '',
        app_version TEXT NOT NULL DEFAULT '',
        FOREIGN KEY (user_id) REFERENCES wps_users(id),
        FOREIGN KEY (device_id) REFERENCES wps_devices(id)
    )""",
    """CREATE TABLE IF NOT EXISTS wps_format_requests (
        request_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        device_id TEXT NOT NULL,
        command TEXT NOT NULL,
        status TEXT NOT NULL
            CHECK (status IN ('authorized', 'success', 'failed')),
        config_version TEXT NOT NULL,
        requested_at INTEGER NOT NULL,
        finished_at INTEGER NOT NULL DEFAULT 0,
        duration_ms INTEGER NOT NULL DEFAULT 0,
        error_code TEXT NOT NULL DEFAULT '',
        app_version TEXT NOT NULL DEFAULT '',
        FOREIGN KEY (user_id) REFERENCES wps_users(id),
        FOREIGN KEY (device_id) REFERENCES wps_devices(id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_wps_devices_user ON wps_devices(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_wps_devices_last_seen ON wps_devices(last_seen_at)",
    "CREATE INDEX IF NOT EXISTS idx_wps_sessions_user_device ON wps_sessions(user_id, device_id)",
    "CREATE INDEX IF NOT EXISTS idx_wps_sessions_expires ON wps_sessions(expires_at)",
    "CREATE INDEX IF NOT EXISTS idx_wps_requests_user_time ON wps_format_requests(user_id, requested_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_wps_requests_device_time ON wps_format_requests(device_id, requested_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_wps_requests_status_time ON wps_format_requests(status, requested_at DESC)",
)

_V2_SCHEMA_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS wps_admin_audit_logs (
        audit_id TEXT PRIMARY KEY,
        actor_type TEXT NOT NULL CHECK (actor_type IN ('session', 'legacy_token')),
        actor_session_id_short TEXT NOT NULL DEFAULT '',
        target_user_id TEXT NOT NULL,
        event TEXT NOT NULL,
        result TEXT NOT NULL CHECK (result IN ('success', 'denied')),
        error_code TEXT NOT NULL DEFAULT '',
        correlation_id TEXT NOT NULL DEFAULT '',
        created_at INTEGER NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_wps_admin_audit_target_time ON wps_admin_audit_logs(target_user_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_wps_admin_audit_event_time ON wps_admin_audit_logs(event, created_at DESC)",
)

_V3_SCHEMA_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS wps_notifications (
        notification_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        level TEXT NOT NULL CHECK (level IN ('info', 'warning', 'error')),
        created_at INTEGER NOT NULL,
        acknowledged_at INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES wps_users(id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_wps_notifications_user_pending_time "
    "ON wps_notifications(user_id, acknowledged_at, created_at DESC, notification_id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_wps_notifications_pending_time "
    "ON wps_notifications(acknowledged_at, created_at DESC, notification_id DESC)",
)

_V4_SCHEMA_STATEMENTS = (
    "ALTER TABLE wps_format_requests ADD COLUMN document_name TEXT NOT NULL DEFAULT ''",
)


def connect(path=None) -> sqlite3.Connection:
    db_path = resolve_wps_database_path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _execute_all(conn: sqlite3.Connection, statements: tuple[str, ...]) -> None:
    """Execute transactional schema statements without executescript's implicit commit."""
    for statement in statements:
        conn.execute(statement)


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """Create persistent WPS administrator audit storage and its query indexes."""
    _execute_all(conn, _V2_SCHEMA_STATEMENTS)


def _migrate_v2_to_v3(conn: sqlite3.Connection) -> None:
    """Create account-scoped WPS notification storage and its lookup indexes."""
    _execute_all(conn, _V3_SCHEMA_STATEMENTS)


def _migrate_v3_to_v4(conn: sqlite3.Connection) -> None:
    """Add the optional, path-free task filename used only by the WPS admin view."""
    columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(wps_format_requests)").fetchall()
    }
    if "document_name" not in columns:
        _execute_all(conn, _V4_SCHEMA_STATEMENTS)


def _upgrade_in_connection(conn: sqlite3.Connection, version: int) -> int:
    """Apply the strictly forward WPS schema chain inside the caller transaction."""
    if version == 0:
        _execute_all(conn, _CORE_SCHEMA_STATEMENTS)
        version = 1
    if version == 1:
        _migrate_v1_to_v2(conn)
        version = 2
    if version == 2:
        _migrate_v2_to_v3(conn)
        version = 3
    if version == 3:
        _migrate_v3_to_v4(conn)
        version = 4
    return version


def initialize_database(connect_func: Callable, sql_lock) -> None:
    """Create or forward-migrate the WPS database with rollback-safe lifecycle logs."""
    with sql_lock:
        conn = connect_func()
        started = time.monotonic()
        version = 0
        try:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise RuntimeError("WPS_DATABASE_VERSION_UNSUPPORTED")
            if version == SCHEMA_VERSION:
                return
            LOGGER.info(
                "wps.database.migration.start | from_version=%s to_version=%s",
                version,
                SCHEMA_VERSION,
            )
            conn.execute("BEGIN IMMEDIATE")
            final_version = _upgrade_in_connection(conn, version)
            if final_version != SCHEMA_VERSION:
                raise RuntimeError("WPS_DATABASE_MIGRATION_INCOMPLETE")
            conn.execute(f"PRAGMA user_version={final_version}")
            conn.commit()
            LOGGER.info(
                "wps.database.migration.success | from_version=%s to_version=%s duration_ms=%s",
                version,
                final_version,
                int((time.monotonic() - started) * 1000),
            )
        except Exception as exc:
            if conn.in_transaction:
                conn.rollback()
            error_code = (
                str(exc)
                if isinstance(exc, RuntimeError) and str(exc).startswith("WPS_DATABASE_")
                else "WPS_DATABASE_MIGRATION_FAILED"
            )
            LOGGER.exception(
                "wps.database.migration.error | from_version=%s to_version=%s error_code=%s duration_ms=%s",
                version,
                SCHEMA_VERSION,
                error_code,
                int((time.monotonic() - started) * 1000),
            )
            raise
        finally:
            conn.close()


def database_ready(connect_func: Callable, sql_lock) -> bool:
    try:
        with sql_lock:
            conn = connect_func()
            try:
                conn.execute("SELECT 1 FROM wps_users LIMIT 1").fetchone()
                conn.execute("SELECT document_name FROM wps_format_requests LIMIT 1").fetchone()
                conn.execute("SELECT 1 FROM wps_admin_audit_logs LIMIT 1").fetchone()
                conn.execute("SELECT 1 FROM wps_notifications LIMIT 1").fetchone()
            finally:
                conn.close()
        return True
    except Exception:
        return False
