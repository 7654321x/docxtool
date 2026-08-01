from __future__ import annotations

import sqlite3
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlparse

from docxtool.web.admin_auth import (
    admin_authorized,
    admin_request_context,
    admin_session_from_headers,
    create_admin_session,
    delete_admin_session,
    get_admin_session,
    legacy_admin_token_from,
    prune_expired_admin_sessions,
    validate_admin_csrf,
)


def _connect_factory(path: Path):
    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    return connect


def _init_db(connect) -> None:
    conn = connect()
    conn.execute(
        """
        CREATE TABLE admin_sessions(
            session_id TEXT PRIMARY KEY,
            csrf_token TEXT NOT NULL,
            user_agent TEXT,
            remote_ip TEXT,
            created_at INTEGER NOT NULL,
            last_seen_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def test_admin_session_lifecycle_refreshes_and_deletes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        connect = _connect_factory(Path(tmp) / "admin.db")
        _init_db(connect)
        lock = threading.Lock()
        tokens = iter(["session-a", "csrf-a", "csrf-b"])

        session = create_admin_session(
            "ua",
            "203.0.113.8",
            connect=connect,
            sql_lock=lock,
            ttl_seconds=60,
            now_func=lambda: 100,
            token_hex=lambda: next(tokens),
        )
        loaded = get_admin_session(
            session["session_id"],
            connect=connect,
            sql_lock=lock,
            ttl_seconds=60,
            now_func=lambda: 120,
        )
        delete_admin_session(session["session_id"], connect=connect, sql_lock=lock)
        missing = get_admin_session(
            session["session_id"],
            connect=connect,
            sql_lock=lock,
            ttl_seconds=60,
            now_func=lambda: 121,
        )

    assert session == {"session_id": "session-a", "csrf_token": "csrf-acsrf-b", "expires_at": 160}
    assert loaded["session_id"] == "session-a"
    assert loaded["expires_at"] == 160
    assert missing == {}


def test_prune_expired_admin_sessions_removes_only_expired_rows() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        connect = _connect_factory(Path(tmp) / "admin.db")
        _init_db(connect)
        conn = connect()
        conn.executemany(
            "INSERT INTO admin_sessions(session_id, csrf_token, created_at, last_seen_at, expires_at) VALUES(?,?,?,?,?)",
            [("old", "csrf", 1, 1, 9), ("new", "csrf", 1, 1, 11)],
        )
        prune_expired_admin_sessions(conn, now=10)
        rows = conn.execute("SELECT session_id FROM admin_sessions ORDER BY session_id").fetchall()
        conn.close()

    assert [row["session_id"] for row in rows] == ["new"]


def test_legacy_admin_token_sources_and_authorization() -> None:
    parsed = urlparse("/monitor?token=query-secret")

    assert legacy_admin_token_from(parsed, {}, "") == "query-secret"
    assert legacy_admin_token_from(urlparse("/monitor"), {"X-Admin-Token": "header-secret"}, "") == "header-secret"
    assert legacy_admin_token_from(urlparse("/monitor"), {}, "admin_token=cookie-secret") == "cookie-secret"
    assert admin_authorized(parsed, {}, "", admin_token="query-secret")
    assert not admin_authorized(parsed, {}, "", admin_token="other")


def test_admin_request_context_prefers_session_then_legacy_token() -> None:
    session = {"session_id": "session-a", "csrf_token": "csrf"}

    session_ctx = admin_request_context(
        urlparse("/monitor?token=legacy"),
        {"Cookie": "docxtool_admin_session=session-a"},
        "",
        cookie_name="docxtool_admin_session",
        admin_token="legacy",
        get_session=lambda value: session if value == "session-a" else {},
    )
    legacy_ctx = admin_request_context(
        urlparse("/monitor?token=legacy"),
        {},
        "",
        cookie_name="docxtool_admin_session",
        admin_token="legacy",
        get_session=lambda _value: {},
    )

    assert session_ctx == {"authorized": True, "session": session, "legacy_token": False}
    assert legacy_ctx == {"authorized": True, "session": {}, "legacy_token": True}


def test_admin_session_from_headers_and_csrf_validation() -> None:
    session = {"session_id": "session-a", "csrf_token": "csrf-token"}

    loaded = admin_session_from_headers(
        {"Cookie": "docxtool_admin_session=session-a"},
        "",
        cookie_name="docxtool_admin_session",
        get_session=lambda value: session if value == "session-a" else {},
    )
    valid = validate_admin_csrf(
        {"X-CSRF-Token": "csrf-token", "Cookie": "docxtool_admin_session=session-a"},
        "",
        cookie_name="docxtool_admin_session",
        csrf_header_name="X-CSRF-Token",
        get_session=lambda value: session if value == "session-a" else {},
    )
    invalid = validate_admin_csrf(
        {"X-CSRF-Token": "bad", "Cookie": "docxtool_admin_session=session-a"},
        "",
        cookie_name="docxtool_admin_session",
        csrf_header_name="X-CSRF-Token",
        get_session=lambda value: session if value == "session-a" else {},
    )

    assert loaded == session
    assert valid
    assert not invalid
