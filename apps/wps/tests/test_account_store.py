import sqlite3

from apps.wps import account_store


def _account():
    return {
        "server_origin": "http://127.0.0.1:9527",
        "username": "User01",
        "user_id": "wusr_1",
        "device_id": "wdev_1",
        "password": "Pass01",
        "session_token": "session-token-001",
        "device_key": "device-key-001",
        "session_expires_at": 86400,
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

    account_store.clear_account()
    assert account_store.load_account() == {}


def test_local_account_ignores_a_legacy_display_name_column(tmp_path, monkeypatch):
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
        conn.execute(
            "UPDATE local_account SET display_name='Legacy Name' WHERE singleton_id=1"
        )
        conn.commit()
        assert conn.execute(
            "SELECT display_name FROM local_account WHERE singleton_id=1"
        ).fetchone()[0] == "Legacy Name"
    assert account_store.load_account() == _account()
