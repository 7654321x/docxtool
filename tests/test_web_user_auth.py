from __future__ import annotations

import base64
import sqlite3
import tempfile
import threading
from pathlib import Path

from docxtool.web.user_auth import (
    auth_csrf_allowed,
    auth_origin_allowed,
    create_user_session,
    delete_user_session,
    principal_from_headers,
    user_cookie_header,
    user_session_from_headers,
    user_session_hash,
)


COOKIE_NAME = "docxtool_user_session"


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
        CREATE TABLE users(
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            display_name TEXT,
            status TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE user_sessions(
            session_hash TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            csrf_token TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            last_seen_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            user_agent TEXT,
            remote_ip TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO users(id, username, display_name, status) VALUES(?,?,?,?)",
        ("usr_active", "alice", "Alice", "active"),
    )
    conn.execute(
        "INSERT INTO users(id, username, display_name, status) VALUES(?,?,?,?)",
        ("usr_disabled", "bob", "Bob", "disabled"),
    )
    conn.commit()
    conn.close()


def _token_bytes_factory(*chunks: bytes):
    values = iter(chunks)

    def token_bytes(_size: int) -> bytes:
        return next(values)

    return token_bytes


def _expected_token(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def test_user_cookie_header_and_hash_are_stable() -> None:
    persistent = user_cookie_header("token", cookie_name=COOKIE_NAME, max_age=60, secure=True, persistent=True)
    session_only = user_cookie_header("token", cookie_name=COOKIE_NAME, max_age=60, secure=False, persistent=False)
    cleared = user_cookie_header("", cookie_name=COOKIE_NAME, max_age=60, secure=False, clear=True)

    assert "Max-Age=60" in persistent
    assert "Secure" in persistent
    assert "Max-Age=" not in session_only
    assert f"{COOKIE_NAME}=" in cleared
    assert "Max-Age=0" in cleared
    assert user_session_hash("abc") == user_session_hash("abc")
    assert user_session_hash("abc") != "abc"


def test_user_session_lifecycle_refreshes_and_deletes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        connect = _connect_factory(Path(tmp) / "users.db")
        _init_db(connect)
        lock = threading.Lock()
        token_raw = b"a" * 32
        csrf_raw = b"b" * 32

        session = create_user_session(
            "usr_active",
            "ua",
            "203.0.113.9",
            connect=connect,
            sql_lock=lock,
            max_age=100,
            now_func=lambda: 1000,
            token_bytes=_token_bytes_factory(token_raw, csrf_raw),
        )
        loaded = user_session_from_headers(
            {"Cookie": f"{COOKIE_NAME}={session['token']}"},
            cookie_name=COOKIE_NAME,
            connect=connect,
            sql_lock=lock,
            refresh_seconds=10,
            now_func=lambda: 1020,
        )
        delete_user_session(
            {"Cookie": f"{COOKIE_NAME}={session['token']}"},
            cookie_name=COOKIE_NAME,
            connect=connect,
            sql_lock=lock,
            refresh_seconds=10,
            now_func=lambda: 1021,
        )
        missing = user_session_from_headers(
            {"Cookie": f"{COOKIE_NAME}={session['token']}"},
            cookie_name=COOKIE_NAME,
            connect=connect,
            sql_lock=lock,
            refresh_seconds=10,
            now_func=lambda: 1022,
        )
        conn = connect()
        row = conn.execute("SELECT session_hash, last_seen_at FROM user_sessions").fetchone()
        conn.close()

    assert session == {"token": _expected_token(token_raw), "csrf_token": _expected_token(csrf_raw), "expires_at": 1100}
    assert loaded["user_id"] == "usr_active"
    assert loaded["csrf_token"] == _expected_token(csrf_raw)
    assert row is None
    assert missing == {}


def test_inactive_or_invalid_session_returns_empty() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        connect = _connect_factory(Path(tmp) / "users.db")
        _init_db(connect)
        lock = threading.Lock()
        token = _expected_token(b"c" * 32)
        conn = connect()
        conn.execute(
            "INSERT INTO user_sessions(session_hash,user_id,csrf_token,created_at,last_seen_at,expires_at) VALUES(?,?,?,?,?,?)",
            (user_session_hash(token), "usr_disabled", "csrf", 1, 1, 9999),
        )
        conn.commit()
        conn.close()

        loaded = user_session_from_headers(
            {"Cookie": f"{COOKIE_NAME}={token}"},
            cookie_name=COOKIE_NAME,
            connect=connect,
            sql_lock=lock,
            refresh_seconds=10,
            now_func=lambda: 10,
        )

    assert loaded == {}


def test_principal_falls_back_to_anonymous_and_marks_invalid_user_session() -> None:
    principal = principal_from_headers(
        {"Cookie": f"{COOKIE_NAME}=invalid-token-value-with-enough-length"},
        user_cookie_name=COOKIE_NAME,
        anonymous_cookie_name="docxtool_anon",
        get_user_session=lambda _headers: {},
        get_anonymous_user=lambda _headers, _cookie: ({"owner_id": "usr_anon"}, "anon-cookie"),
    )

    assert principal["authenticated"] is False
    assert principal["owner_id"] == "usr_anon"
    assert principal["invalid_user_session"] is True
    assert principal["cookie"] == "anon-cookie"


def test_auth_origin_and_csrf_helpers() -> None:
    assert auth_origin_allowed({"Origin": "https://example.test"}, lambda _headers: True)
    assert auth_csrf_allowed({"X-CSRF-Token": "csrf"}, {"authenticated": True, "csrf_token": "csrf"}, csrf_header_name="X-CSRF-Token")
    assert not auth_csrf_allowed({"X-CSRF-Token": "bad"}, {"authenticated": True, "csrf_token": "csrf"}, csrf_header_name="X-CSRF-Token")
    assert not auth_csrf_allowed({"X-CSRF-Token": "csrf"}, {"authenticated": False, "csrf_token": "csrf"}, csrf_header_name="X-CSRF-Token")
