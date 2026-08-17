import sqlite3

import pytest

from apps.wps import account_store


def _account():
    return {
        "username": "User01",
        "user_id": "wusr_1",
        "device_id": "wdev_1",
        "user_status": "active",
        "device_name": "测试电脑",
        "platform": "windows",
        "device_status": "active",
        "password": "Pass01",
        "session_token": "session-token-001",
        "device_key": "device-key-001",
        "session_created_at": 3600,
        "session_expires_at": 86400,
        "features": {"controlled": [{"command": "apply", "enabled": True}]},
        "config_version": "config-1",
        "heartbeat_interval_seconds": 600,
        "remember_password": True,
        "auto_login": False,
    }


def test_local_account_round_trip_uses_dpapi_ciphertext(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    account_store.save_account(_account())

    with sqlite3.connect(str(account_store.local_account_path())) as conn:
        row = conn.execute(
            "SELECT password_cipher,session_token_cipher,device_key_cipher FROM local_account"
        ).fetchone()

    assert b"Pass01" not in row[0]
    assert b"session-token-001" not in row[1]
    assert b"device-key-001" not in row[2]
    assert account_store.load_account() == _account()


def test_format_result_outbox_is_durable_idempotent_and_conflict_checked(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    payload = {
        "request_id": "request-1",
        "status": "success",
        "duration_ms": 120,
        "error_code": "",
        "app_version": "5.2.1",
    }

    assert account_store.enqueue_format_result(payload) is False
    assert account_store.enqueue_format_result(payload) is True
    assert account_store.count_format_results() == 1
    assert account_store.list_format_results() == [payload]
    with pytest.raises(RuntimeError, match="WPS_FORMAT_RESULT_QUEUE_CONFLICT"):
        account_store.enqueue_format_result({**payload, "status": "failed"})

    assert account_store.clear_account() == 1
    assert account_store.load_account() == {}
    assert account_store.count_format_results() == 0


def test_format_result_outbox_migrates_and_preserves_document_name(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path = account_store.local_account_path()
    path.parent.mkdir(parents=True)
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            """CREATE TABLE format_result_outbox (
                request_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                duration_ms INTEGER NOT NULL,
                error_code TEXT NOT NULL,
                app_version TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )"""
        )
        conn.execute(
            """INSERT INTO format_result_outbox
               (request_id,status,duration_ms,error_code,app_version,created_at)
               VALUES ('legacy-request','success',12,'','5.1',1)"""
        )
        conn.commit()

    assert account_store.list_format_results() == [
        {
            "request_id": "legacy-request",
            "status": "success",
            "duration_ms": 12,
            "error_code": "",
            "app_version": "5.1",
        }
    ]
    payload = {
        "request_id": "request-with-name",
        "status": "success",
        "duration_ms": 120,
        "error_code": "",
        "document_name": "会议纪要.docx",
        "app_version": "5.2.1",
    }
    assert account_store.enqueue_format_result(payload) is False
    assert account_store.list_format_results()[-1] == payload


def test_clear_account_rolls_back_account_and_outbox_together(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    account_store.save_account(_account())
    account_store.enqueue_format_result(
        {
            "request_id": "request-rollback",
            "status": "success",
            "duration_ms": 120,
            "error_code": "",
            "app_version": "5.2.1",
        }
    )
    with sqlite3.connect(str(account_store.local_account_path())) as conn:
        conn.execute(
            """CREATE TRIGGER reject_outbox_delete
               BEFORE DELETE ON format_result_outbox
               BEGIN
                 SELECT RAISE(ABORT, 'reject outbox delete');
               END"""
        )

    with pytest.raises(sqlite3.IntegrityError, match="reject outbox delete"):
        account_store.clear_account()

    assert account_store.load_account() == _account()
    assert account_store.count_format_results() == 1


def test_clear_account_returns_zero_when_database_does_not_exist(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert account_store.clear_account() == 0
    assert account_store.local_account_path().exists() is False


def test_local_account_migrates_away_legacy_origin_and_display_columns(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path = account_store.local_account_path()
    path.parent.mkdir(parents=True)
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            """CREATE TABLE local_account (
                singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                server_origin TEXT NOT NULL,
                username TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                user_id TEXT NOT NULL DEFAULT '',
                device_id TEXT NOT NULL DEFAULT '',
                password_cipher BLOB NOT NULL,
                session_token_cipher BLOB NOT NULL,
                device_key_cipher BLOB NOT NULL,
                session_expires_at INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL
            )"""
        )

    account_store.save_account(_account())

    with sqlite3.connect(str(path)) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(local_account)")}
        assert "server_origin" not in columns
        assert "display_name" not in columns
    assert account_store.load_account() == _account()


def test_not_remembering_password_clears_existing_cipher(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    account_store.save_account(_account())
    account_store.save_account(
        {**_account(), "password": "", "remember_password": False}
    )

    with sqlite3.connect(str(account_store.local_account_path())) as conn:
        row = conn.execute(
            "SELECT password_cipher,remember_password,auto_login FROM local_account"
        ).fetchone()

    assert row == (b"", 0, 0)
    loaded = account_store.load_account()
    assert loaded["password"] == ""
    assert loaded["remember_password"] is False


def test_auto_login_preferences_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    account_store.save_account(
        {**_account(), "remember_password": True, "auto_login": True}
    )

    loaded = account_store.load_account()
    assert loaded["remember_password"] is True
    assert loaded["auto_login"] is True


def test_auto_login_requires_remembered_password(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    with pytest.raises(
        ValueError, match="WPS_AUTO_LOGIN_REQUIRES_REMEMBER_PASSWORD"
    ):
        account_store.save_account(
            {**_account(), "remember_password": False, "auto_login": True}
        )


def test_previous_schema_migrates_to_remember_without_auto_login(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path = account_store.local_account_path()
    path.parent.mkdir(parents=True)
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
            "INSERT INTO local_account VALUES (1,?,?,?,?,?,?,?,?,?)",
            (
                "https://legacy.invalid",
                _account()["username"],
                _account()["user_id"],
                _account()["device_id"],
                account_store.encrypt_secret(_account()["password"]),
                account_store.encrypt_secret(_account()["session_token"]),
                account_store.encrypt_secret(_account()["device_key"]),
                _account()["session_expires_at"],
                1,
            ),
        )

    assert account_store.load_account() == {
        **_account(),
        "user_status": "",
        "device_name": "",
        "platform": "",
        "device_status": "",
        "session_created_at": 0,
        "features": {},
        "config_version": "",
        "heartbeat_interval_seconds": 0,
    }


def test_preferences_can_disable_auto_login_without_authentication(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    account_store.save_account(
        {**_account(), "remember_password": True, "auto_login": True}
    )

    updated = account_store.update_preferences(
        remember_password=True,
        auto_login=False,
    )

    assert updated["auto_login"] is False
    assert updated["password"] == "Pass01"


def test_preferences_clear_password_when_remember_is_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    account_store.save_account(_account())

    updated = account_store.update_preferences(
        remember_password=False,
        auto_login=False,
    )

    assert updated["password"] == ""
    assert account_store.load_account()["password"] == ""


def test_invalidate_session_preserves_account_snapshot_and_outbox(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    account_store.save_account({**_account(), "auto_login": True})
    account_store.enqueue_format_result(
        {
            "request_id": "request-reauth",
            "status": "success",
            "duration_ms": 120,
            "error_code": "",
            "app_version": "5.2.1",
        }
    )

    invalidated = account_store.invalidate_session()

    assert invalidated["username"] == "User01"
    assert invalidated["session_token"] == ""
    assert invalidated["session_expires_at"] == 0
    assert invalidated["auto_login"] is False
    assert invalidated["features"] == _account()["features"]
    assert account_store.count_format_results() == 1
