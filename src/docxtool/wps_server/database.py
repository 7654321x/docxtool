"""SQLite schema and connection helpers for WPS plugin accounts."""

from __future__ import annotations

import sqlite3
from typing import Callable

from .config import resolve_wps_database_path

SCHEMA_VERSION = 1


def connect(path=None) -> sqlite3.Connection:
    db_path = resolve_wps_database_path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def initialize_database(connect_func: Callable, sql_lock) -> None:
    with sql_lock:
        conn = connect_func()
        try:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise RuntimeError("WPS_DATABASE_VERSION_UNSUPPORTED")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS wps_users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    username_norm TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'disabled')),
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    last_login_at INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS wps_devices (
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
                );
                CREATE TABLE IF NOT EXISTS wps_sessions (
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
                );
                CREATE TABLE IF NOT EXISTS wps_format_requests (
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
                );
                CREATE INDEX IF NOT EXISTS idx_wps_devices_user
                    ON wps_devices(user_id);
                CREATE INDEX IF NOT EXISTS idx_wps_devices_last_seen
                    ON wps_devices(last_seen_at);
                CREATE INDEX IF NOT EXISTS idx_wps_sessions_user_device
                    ON wps_sessions(user_id, device_id);
                CREATE INDEX IF NOT EXISTS idx_wps_sessions_expires
                    ON wps_sessions(expires_at);
                CREATE INDEX IF NOT EXISTS idx_wps_requests_user_time
                    ON wps_format_requests(user_id, requested_at DESC);
                CREATE INDEX IF NOT EXISTS idx_wps_requests_device_time
                    ON wps_format_requests(device_id, requested_at DESC);
                CREATE INDEX IF NOT EXISTS idx_wps_requests_status_time
                    ON wps_format_requests(status, requested_at DESC);
                """
            )
            conn.execute("PRAGMA user_version=1")
            conn.commit()
        finally:
            conn.close()


def database_ready(connect_func: Callable, sql_lock) -> bool:
    try:
        with sql_lock:
            conn = connect_func()
            try:
                conn.execute("SELECT 1 FROM wps_users LIMIT 1").fetchone()
            finally:
                conn.close()
        return True
    except Exception:
        return False
