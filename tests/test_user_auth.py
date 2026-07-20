import sqlite3
import uuid

import pytest

from docxtool.auth import hash_password, normalize_username, validate_password, validate_username, verify_password
from docxtool.web import app as server


def test_username_normalization_and_password_validation():
    assert normalize_username("  Ａlice  ") == "alice"
    assert validate_username("  Ａlice  ") == ("Alice", "alice")
    assert validate_password("12345678") == "12345678"
    with pytest.raises(ValueError):
        validate_password(" short ")


def test_api_auth_paths_normalize_to_handler_routes():
    assert server._route_path("/api/auth/me") == "/auth/me"
    assert server._route_path("/api/auth/register") == "/auth/register"
    assert server._route_path("/api/auth/login") == "/auth/login"
    assert server._route_path("/api/auth/logout") == "/auth/logout"


def test_argon2id_hash_is_not_plaintext():
    encoded = hash_password("correct horse battery staple")
    assert encoded.startswith("$argon2id$")
    assert "correct horse" not in encoded
    assert verify_password(encoded, "correct horse battery staple")[0]
    assert not verify_password(encoded, "wrong password")[0]


def test_user_cookie_can_be_persistent_or_session_only():
    persistent = server._user_cookie_header("token", persistent=True)
    session_only = server._user_cookie_header("token", persistent=False)
    assert f"Max-Age={server.USER_SESSION_MAX_AGE}" in persistent
    assert "Max-Age=" not in session_only
    assert "HttpOnly" in persistent
    assert "SameSite=Lax" in session_only


def test_user_session_stores_only_token_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_DB_PATH", str(tmp_path / "auth.db"))
    server._sql_init()
    user_id = f"usr_{uuid.uuid4().hex}"
    now = server._now_unix()
    with server._SQL_LOCK:
        conn = server._sql()
        conn.execute("INSERT INTO users(id,username,username_norm,password_hash,display_name,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                     (user_id, "Alice", "alice", hash_password("password-123"), "Alice", now, now))
        conn.commit()
        conn.close()
    session = server._create_user_session(user_id, "test", "127.0.0.1")
    with sqlite3.connect(server._DB_PATH) as conn:
        stored = conn.execute("SELECT session_hash FROM user_sessions").fetchone()[0]
    assert session["token"] != stored
    assert stored == server._user_session_hash(session["token"])


def test_invalid_user_session_falls_back_to_anonymous_and_is_marked_for_clear(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_DB_PATH", str(tmp_path / "invalid-session.db"))
    server._sql_init()
    principal = server._principal({"Cookie": f"{server.USER_SESSION_COOKIE}=invalid-session-token-value-1234567890"})
    assert principal["authenticated"] is False
    assert principal["invalid_user_session"] is True
    assert principal["owner_id"].startswith("usr_")
    clear_cookie = server._user_cookie_header("", clear=True)
    assert f"{server.USER_SESSION_COOKIE}=" in clear_cookie
    assert "Max-Age=0" in clear_cookie


def test_task_owner_isolation_at_sql_boundary(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_DB_PATH", str(tmp_path / "tasks.db"))
    server._sql_init()
    task_id = str(uuid.uuid4())
    owner_a = f"usr_{uuid.uuid4().hex}"
    owner_b = f"usr_{uuid.uuid4().hex}"
    server.record_task_queued(task_id, "127.0.0.1", "", "a.docx", owner_id=owner_a)
    with server.TASKS_LOCK:
        server.TASKS.pop(task_id, None)
    assert server._public_task_state(task_id, owner_a)["id"] == task_id
    assert server._public_task_state(task_id, owner_b) == {}
