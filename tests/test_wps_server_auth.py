from concurrent.futures import ThreadPoolExecutor
import logging
import sqlite3
import threading

import pytest

from docxtool.auth.passwords import verify_password
from docxtool.wps_server import database
from docxtool.wps_server import service as service_module
from docxtool.wps_server.auth import WpsAuthError, authenticated_session, bearer_token
from docxtool.wps_server.service import WpsServiceError, heartbeat, login_user, register_user
from docxtool.wps_server.validation import WpsValidationError, validate_password, validate_username


def _setup(tmp_path):
    path = tmp_path / "wps_plugin.db"

    def connect():
        return database.connect(path)

    lock = threading.Lock()
    database.initialize_database(connect, lock)
    return path, connect, lock


def _device():
    return {
        "device_key": "device-key-001",
        "device_name": "测试电脑",
        "platform": "windows",
        "app_version": "5.1",
    }


def _register(connect, lock, now=1000):
    return register_user(
        {"username": "User01", "password": "Pass01", "device": _device()},
        connect_func=connect,
        sql_lock=lock,
        client_ip="127.0.0.1",
        now_func=lambda: now,
        config_version="test-config",
    )


def test_register_session_is_exactly_24_hours_and_username_is_case_insensitive(tmp_path):
    _path, connect, lock = _setup(tmp_path)
    result = _register(connect, lock)

    assert result["session_expires_at"] - result["session_created_at"] == 86400
    assert set(result["user"]) == {"id", "username", "status"}
    with pytest.raises(WpsServiceError) as exc_info:
        register_user(
            {"username": "user01", "password": "Pass02", "device": _device()},
            connect_func=connect,
            sql_lock=lock,
            client_ip="127.0.0.1",
            now_func=lambda: 1001,
            config_version="test-config",
        )
    assert exc_info.value.code == "USERNAME_TAKEN"


def test_registration_rejects_the_removed_display_name_field(tmp_path):
    _path, connect, lock = _setup(tmp_path)

    with pytest.raises(WpsValidationError) as exc_info:
        register_user(
            {
                "username": "User01",
                "password": "Pass01",
                "display_name": "用户一",
                "device": _device(),
            },
            connect_func=connect,
            sql_lock=lock,
            client_ip="127.0.0.1",
            now_func=lambda: 1000,
            config_version="test-config",
        )

    assert exc_info.value.code == "WPS_UNKNOWN_FIELD"


def test_registration_and_login_accept_a_legacy_display_name_column(tmp_path):
    _path, connect, lock = _setup(tmp_path)
    with lock:
        conn = connect()
        try:
            conn.execute(
                "ALTER TABLE wps_users ADD COLUMN display_name TEXT NOT NULL DEFAULT ''"
            )
            conn.commit()
        finally:
            conn.close()

    registered = _register(connect, lock)
    logged_in = login_user(
        {"username": "User01", "password": "Pass01", "device": _device()},
        connect_func=connect,
        sql_lock=lock,
        client_ip="127.0.0.1",
        now_func=lambda: 1100,
        config_version="test-config",
    )

    assert registered["user"]["username"] == "User01"
    assert logged_in["user"]["username"] == "User01"
    assert "display_name" not in logged_in["user"]


@pytest.mark.parametrize(
    ("validator", "value", "code"),
    [
        (validate_username, "A1b", "USERNAME_LENGTH_INVALID"),
        (validate_username, "User_1", "USERNAME_CHARSET_INVALID"),
        (validate_username, "UserOnly", "USERNAME_COMPOSITION_INVALID"),
        (validate_password, "A1b", "PASSWORD_LENGTH_INVALID"),
        (validate_password, "Pass_1", "PASSWORD_CHARSET_INVALID"),
        (validate_password, "123456", "PASSWORD_COMPOSITION_INVALID"),
    ],
)
def test_wps_account_rules_are_enforced_by_server_validators(validator, value, code):
    with pytest.raises(WpsValidationError) as exc_info:
        validator(value)
    assert exc_info.value.code == code


def test_concurrent_case_insensitive_registration_creates_one_user(tmp_path):
    path, connect, lock = _setup(tmp_path)

    def register(username):
        try:
            register_user(
                {"username": username, "password": "Pass01", "device": _device()},
                connect_func=connect,
                sql_lock=lock,
                client_ip="127.0.0.1",
                now_func=lambda: 1000,
                config_version="test-config",
            )
            return "created"
        except WpsServiceError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(register, ("User01", "user01")))

    assert sorted(results) == ["USERNAME_TAKEN", "created"]
    with sqlite3.connect(str(path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM wps_users").fetchone()[0] == 1


def test_login_reuses_device_and_invalid_credentials_share_one_error(tmp_path):
    path, connect, lock = _setup(tmp_path)
    _register(connect, lock)

    for username, password in (("Missing1", "Pass01"), ("User01", "Wrong01"), ("bad", "bad")):
        with pytest.raises(WpsServiceError) as exc_info:
            login_user(
                {"username": username, "password": password, "device": _device()},
                connect_func=connect,
                sql_lock=lock,
                client_ip="127.0.0.1",
                now_func=lambda: 1100,
                config_version="test-config",
            )
        assert exc_info.value.code == "INVALID_CREDENTIALS"

    login_user(
        {"username": "user01", "password": "Pass01", "device": _device()},
        connect_func=connect,
        sql_lock=lock,
        client_ip="127.0.0.1",
        now_func=lambda: 1200,
        config_version="test-config",
    )
    with sqlite3.connect(str(path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM wps_devices").fetchone()[0] == 1


def test_missing_account_uses_a_valid_argon2_dummy_hash():
    valid, _needs_rehash = verify_password(
        service_module._DUMMY_PASSWORD_HASH,
        service_module._DUMMY_PASSWORD,
    )
    assert valid is True


def test_bearer_rejects_non_ascii_before_hashing():
    with pytest.raises(WpsAuthError) as exc_info:
        bearer_token({"Authorization": "Bearer " + ("é" * 43)})
    assert exc_info.value.code == "SESSION_REQUIRED"


def test_heartbeat_updates_activity_without_extending_expiry(tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger="docx_tool")
    path, connect, lock = _setup(tmp_path)
    registered = _register(connect, lock, now=2000)
    headers = {"Authorization": f"Bearer {registered['session_token']}"}
    principal = authenticated_session(headers, connect_func=connect, sql_lock=lock, now_func=lambda: 2500)

    result = heartbeat(
        principal,
        {"device_id": registered["device"]["id"], "app_version": "5.1"},
        connect_func=connect,
        sql_lock=lock,
        client_ip="127.0.0.2",
        now_func=lambda: 2500,
        config_version="test-config",
    )

    assert result["session_expires_at"] == 2000 + 86400
    with sqlite3.connect(str(path)) as conn:
        row = conn.execute("SELECT last_seen_at,expires_at FROM wps_sessions").fetchone()
    assert row == (2500, 2000 + 86400)

    with pytest.raises(WpsAuthError) as exc_info:
        authenticated_session(headers, connect_func=connect, sql_lock=lock, now_func=lambda: 2000 + 86400)
    assert exc_info.value.code == "SESSION_EXPIRED"
    assert "wps.auth.session.expired" in caplog.text
