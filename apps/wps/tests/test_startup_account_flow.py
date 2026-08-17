import sqlite3
import time

import pytest

from apps.wps import account_store
from apps.wps import main as wps_main


def _create_account_row(path, *, password=b"password", token=b"token", device=b"device"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            """CREATE TABLE local_account (
                singleton_id INTEGER PRIMARY KEY,
                server_origin TEXT NOT NULL,
                username TEXT NOT NULL,
                user_id TEXT NOT NULL,
                device_id TEXT NOT NULL,
                password_cipher BLOB NOT NULL,
                session_token_cipher BLOB NOT NULL,
                device_key_cipher BLOB NOT NULL,
                session_expires_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )"""
        )
        conn.execute(
            "INSERT INTO local_account VALUES (1,?,?,?,?,?,?,?,?,?)",
            ("https://example.test", "User01", "wusr_1", "wdev_1", password, token, device, 9999999999, 1),
        )


def _expect_corruption_recovery(tmp_path, monkeypatch, api):
    login_account = {"username": "Recovered"}
    monkeypatch.setattr(wps_main, "show_login_register_window", lambda **_kwargs: login_account)
    assert wps_main.resolve_startup_account(api) == login_account
    assert not account_store.local_account_path().exists()
    assert list(account_store.local_account_path().parent.glob("account.db.corrupted-*"))


@pytest.mark.parametrize("session_expires_at", [50, 200])
def test_saved_account_always_opens_login_window_and_reuses_identity(
    monkeypatch,
    session_expires_at,
):
    account = {
        "username": "User01",
        "device_key": "device-key-001",
        "session_expires_at": session_expires_at,
    }
    observed = {}
    monkeypatch.setattr(account_store, "load_account", lambda: account)
    monkeypatch.setattr(wps_main.windows_startup, "is_enabled", lambda: False)
    monkeypatch.setattr(
        wps_main,
        "show_login_register_window",
        lambda **kwargs: observed.update(kwargs) or {"username": "User01"},
    )

    assert wps_main.resolve_startup_account("api") == {"username": "User01"}
    assert observed == {
        "api": "api",
        "account_store": account_store,
        "initial_username": "User01",
        "device_key": "device-key-001",
        "initial_password": "",
        "remember_password": False,
        "auto_login": False,
        "initial_message": "",
        "startup_enabled": False,
    }


def test_missing_saved_account_opens_blank_login_window(monkeypatch):
    observed = {}
    monkeypatch.setattr(account_store, "load_account", lambda: {})
    monkeypatch.setattr(wps_main.windows_startup, "is_enabled", lambda: False)
    monkeypatch.setattr(
        wps_main,
        "show_login_register_window",
        lambda **kwargs: observed.update(kwargs) or {},
    )

    assert wps_main.resolve_startup_account("api") == {}
    assert observed == {
        "api": "api",
        "account_store": account_store,
        "initial_username": "",
        "device_key": "",
        "initial_password": "",
        "remember_password": False,
        "auto_login": False,
        "initial_message": "",
        "startup_enabled": False,
    }


def test_force_login_opens_window_even_when_auto_login_is_enabled(monkeypatch):
    account = _auto_account(expires_at=int(time.time()) + 3600)
    observed = {}
    monkeypatch.setattr(account_store, "load_account", lambda: account)
    monkeypatch.setattr(
        wps_main,
        "show_login_register_window",
        lambda **kwargs: observed.update(kwargs) or {"username": "User01"},
    )

    assert wps_main.resolve_startup_account(object(), force_login=True) == {
        "username": "User01"
    }
    assert observed["auto_login"] is True


def _auto_account(*, expires_at):
    return {
        "username": "User01",
        "user_id": "wusr_1",
        "device_id": "wdev_1",
        "password": "Pass01",
        "session_token": "old-token",
        "device_key": "device-key-001",
        "session_expires_at": expires_at,
        "remember_password": True,
        "auto_login": True,
    }


def test_auto_login_opens_window_with_prefilled_fields(monkeypatch):
    account = _auto_account(expires_at=int(time.time()) + 3600)
    observed = {}
    monkeypatch.setattr(account_store, "load_account", lambda: account)
    monkeypatch.setattr(
        wps_main,
        "show_login_register_window",
        lambda **kwargs: observed.update(kwargs) or {"username": "User01"},
    )

    assert wps_main.resolve_startup_account(object()) == {"username": "User01"}
    assert observed["initial_username"] == "User01"
    assert observed["initial_password"] == "Pass01"
    assert observed["auto_login"] is True


def test_auto_login_does_not_call_api_before_window_submission(monkeypatch):
    account = _auto_account(expires_at=0)
    saved = []
    observed = {}

    class Api:
        origin = "https://example.test"

        def login(self, payload):
            assert payload["username"] == "User01"
            return {
                "user": {"id": "wusr_1", "username": "User01"},
                "device": {"id": "wdev_1"},
                "session_token": "new-token",
                "session_expires_at": 9999999999,
            }

    monkeypatch.setattr(account_store, "load_account", lambda: account)
    monkeypatch.setattr(account_store, "save_account", lambda value: saved.append(value))
    monkeypatch.setattr(
        wps_main,
        "show_login_register_window",
        lambda **kwargs: observed.update(kwargs) or {"username": "User01"},
    )

    resolved = wps_main.resolve_startup_account(Api())
    assert resolved == {"username": "User01"}
    assert observed["auto_login"] is True
    assert saved == []


def test_auto_login_rejection_is_handled_by_the_login_window(monkeypatch):
    account = _auto_account(expires_at=0)
    observed = {}

    monkeypatch.setattr(account_store, "load_account", lambda: account)
    monkeypatch.setattr(
        wps_main,
        "show_login_register_window",
        lambda **kwargs: observed.update(kwargs) or {"username": "User01"},
    )

    assert wps_main.resolve_startup_account(object()) == {"username": "User01"}
    assert observed["initial_username"] == "User01"
    assert observed["initial_password"] == "Pass01"
    assert observed["initial_message"] == ""


def test_auto_login_network_failure_stays_in_login_window(monkeypatch):
    account = _auto_account(expires_at=0)
    observed = {}

    monkeypatch.setattr(account_store, "load_account", lambda: account)
    monkeypatch.setattr(
        wps_main,
        "show_login_register_window",
        lambda **kwargs: observed.update(kwargs) or {},
    )
    assert wps_main.resolve_startup_account(object()) == {}
    assert observed["auto_login"] is True


def test_corrupt_sqlite_is_quarantined_and_login_reopens(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path = account_store.local_account_path()
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not a sqlite database")

    _expect_corruption_recovery(tmp_path, monkeypatch, object())


@pytest.mark.parametrize("field", ["password_cipher", "session_token_cipher", "device_key_cipher"])
def test_invalid_cipher_is_quarantined_and_login_reopens(tmp_path, monkeypatch, field):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path = account_store.local_account_path()
    values = {"password_cipher": b"password", "session_token_cipher": b"token", "device_key_cipher": b"device"}
    values[field] = b"invalid-cipher"
    _create_account_row(path, password=values["password_cipher"], token=values["session_token_cipher"], device=values["device_key_cipher"])
    monkeypatch.setattr(account_store, "decrypt_secret", lambda value: (_ for _ in ()).throw(OSError("CryptUnprotectData failed")) if value == b"invalid-cipher" else value.decode())

    _expect_corruption_recovery(tmp_path, monkeypatch, object())


def test_dpapi_unprotect_failure_is_quarantined_and_login_reopens(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    _create_account_row(account_store.local_account_path())
    monkeypatch.setattr(account_store, "decrypt_secret", lambda _value: (_ for _ in ()).throw(OSError("CryptUnprotectData failed")))

    _expect_corruption_recovery(tmp_path, monkeypatch, object())


def test_corrupt_store_quarantine_failure_is_not_hidden(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path = account_store.local_account_path()
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not a sqlite database")
    monkeypatch.setattr(
        account_store,
        "quarantine_corrupted_account",
        lambda: (_ for _ in ()).throw(OSError("quarantine failed")),
    )

    with pytest.raises(RuntimeError, match="WPS_LOCAL_ACCOUNT_QUARANTINE_FAILED"):
        wps_main.resolve_startup_account(object())
