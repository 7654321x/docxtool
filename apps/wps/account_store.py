"""Single-account local storage protected by Windows DPAPI."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import time

CRYPTPROTECT_UI_FORBIDDEN = 0x1


class LocalAccountCorruptedError(RuntimeError):
    """The existing local account database cannot be read safely."""


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def local_account_path() -> Path:
    root = os.environ.get("LOCALAPPDATA")
    if not root:
        raise RuntimeError("WPS_LOCALAPPDATA_MISSING")
    return Path(root) / "DocxTool" / "wps" / "account.db"


def _crypt32():
    if sys.platform != "win32":
        raise RuntimeError("WPS_DPAPI_WINDOWS_REQUIRED")
    library = ctypes.WinDLL("crypt32", use_last_error=True)
    library.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    library.CryptProtectData.restype = wintypes.BOOL
    library.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    library.CryptUnprotectData.restype = wintypes.BOOL
    return library


def _kernel32():
    library = ctypes.WinDLL("kernel32", use_last_error=True)
    library.LocalFree.argtypes = [wintypes.HLOCAL]
    library.LocalFree.restype = wintypes.HLOCAL
    return library


def _input_blob(value: bytes):
    buffer = ctypes.create_string_buffer(value)
    blob = _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    return buffer, blob


def encrypt_secret(value: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("WPS_LOCAL_SECRET_REQUIRED")
    raw = value.encode("utf-8")
    _buffer, source = _input_blob(raw)
    target = _DataBlob()
    if not _crypt32().CryptProtectData(
        ctypes.byref(source),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(target),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        _kernel32().LocalFree(target.pbData)


def decrypt_secret(value: bytes) -> str:
    if not isinstance(value, bytes) or not value:
        raise ValueError("WPS_LOCAL_CIPHER_REQUIRED")
    _buffer, source = _input_blob(value)
    target = _DataBlob()
    if not _crypt32().CryptUnprotectData(
        ctypes.byref(source),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(target),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(target.pbData, target.cbData).decode("utf-8")
    finally:
        _kernel32().LocalFree(target.pbData)


def new_device_key() -> str:
    return secrets.token_urlsafe(32)


def _connect() -> sqlite3.Connection:
    path = local_account_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS local_account (
                singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                server_origin TEXT NOT NULL,
                username TEXT NOT NULL,
                 user_id TEXT NOT NULL DEFAULT '',
                 device_id TEXT NOT NULL DEFAULT '',
                 user_status TEXT NOT NULL DEFAULT '',
                 device_name TEXT NOT NULL DEFAULT '',
                 platform TEXT NOT NULL DEFAULT '',
                 device_status TEXT NOT NULL DEFAULT '',
                 password_cipher BLOB NOT NULL DEFAULT X'',
                 session_token_cipher BLOB NOT NULL DEFAULT X'',
                 device_key_cipher BLOB NOT NULL,
                 session_created_at INTEGER NOT NULL DEFAULT 0,
                 session_expires_at INTEGER NOT NULL DEFAULT 0,
                 features_json TEXT NOT NULL DEFAULT '{}',
                 config_version TEXT NOT NULL DEFAULT '',
                 heartbeat_interval_seconds INTEGER NOT NULL DEFAULT 0,
                 remember_password INTEGER NOT NULL DEFAULT 1,
                auto_login INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL
            )"""
        )
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(local_account)").fetchall()
        }
        if "remember_password" not in columns:
            conn.execute(
                "ALTER TABLE local_account ADD COLUMN "
                "remember_password INTEGER NOT NULL DEFAULT 1"
            )
        if "auto_login" not in columns:
            conn.execute(
                "ALTER TABLE local_account ADD COLUMN "
                "auto_login INTEGER NOT NULL DEFAULT 0"
            )
        for name, definition in (
            ("user_status", "TEXT NOT NULL DEFAULT ''"),
            ("device_name", "TEXT NOT NULL DEFAULT ''"),
            ("platform", "TEXT NOT NULL DEFAULT ''"),
            ("device_status", "TEXT NOT NULL DEFAULT ''"),
            ("session_created_at", "INTEGER NOT NULL DEFAULT 0"),
            ("features_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("config_version", "TEXT NOT NULL DEFAULT ''"),
            ("heartbeat_interval_seconds", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if name not in columns:
                conn.execute(
                    f"ALTER TABLE local_account ADD COLUMN {name} {definition}"
                )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS format_result_outbox (
                request_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                duration_ms INTEGER NOT NULL,
                error_code TEXT NOT NULL,
                document_name TEXT NOT NULL DEFAULT '',
                app_version TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )"""
        )
        outbox_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(format_result_outbox)").fetchall()
        }
        if "document_name" not in outbox_columns:
            conn.execute(
                "ALTER TABLE format_result_outbox "
                "ADD COLUMN document_name TEXT NOT NULL DEFAULT ''"
            )
    except sqlite3.Error:
        conn.close()
        raise
    return conn


def load_account() -> dict:
    if not local_account_path().is_file():
        return {}
    try:
        conn = _connect()
        try:
            row = conn.execute("SELECT * FROM local_account WHERE singleton_id=1").fetchone()
        finally:
            conn.close()
        if row is None:
            return {}
        remember_password = bool(row["remember_password"])
        password_cipher = bytes(row["password_cipher"])
        features = json.loads(str(row["features_json"] or "{}"))
        if not isinstance(features, dict):
            raise ValueError("WPS_LOCAL_FEATURES_INVALID")
        return {
            "server_origin": row["server_origin"],
            "username": row["username"],
            "user_id": row["user_id"],
            "device_id": row["device_id"],
            "user_status": row["user_status"],
            "device_name": row["device_name"],
            "platform": row["platform"],
            "device_status": row["device_status"],
            "password": decrypt_secret(password_cipher) if remember_password else "",
            "session_token": (
                decrypt_secret(bytes(row["session_token_cipher"]))
                if bytes(row["session_token_cipher"])
                else ""
            ),
            "device_key": decrypt_secret(bytes(row["device_key_cipher"])),
            "session_created_at": int(row["session_created_at"]),
            "session_expires_at": int(row["session_expires_at"]),
            "features": features,
            "config_version": row["config_version"],
            "heartbeat_interval_seconds": int(row["heartbeat_interval_seconds"]),
            "remember_password": remember_password,
            "auto_login": bool(row["auto_login"]),
        }
    except (sqlite3.Error, OSError, ValueError, TypeError, KeyError, IndexError) as exc:
        raise LocalAccountCorruptedError("WPS_LOCAL_ACCOUNT_CORRUPTED") from exc


def quarantine_corrupted_account() -> Path:
    path = local_account_path()
    quarantined = path.with_name(f"{path.name}.corrupted-{int(time.time())}")
    path.replace(quarantined)
    return quarantined


def save_account(account: dict) -> None:
    required = {
        "server_origin",
        "username",
        "user_id",
        "device_id",
        "session_token",
        "device_key",
        "session_expires_at",
    }
    if not isinstance(account, dict) or not required.issubset(account):
        raise ValueError("WPS_LOCAL_ACCOUNT_INVALID")
    remember_password = bool(account.get("remember_password", True))
    auto_login = bool(account.get("auto_login", False))
    if auto_login and not remember_password:
        raise ValueError("WPS_AUTO_LOGIN_REQUIRES_REMEMBER_PASSWORD")
    password = account.get("password", "")
    if remember_password and not password:
        raise ValueError("WPS_LOCAL_PASSWORD_REQUIRED")
    password_cipher = encrypt_secret(password) if remember_password else b""
    token_cipher = (
        encrypt_secret(account["session_token"]) if account["session_token"] else b""
    )
    device_cipher = encrypt_secret(account["device_key"])
    user_status = str(account.get("user_status") or "")
    device_name = str(account.get("device_name") or "")
    platform = str(account.get("platform") or "")
    device_status = str(account.get("device_status") or "")
    session_created_at = int(account.get("session_created_at") or 0)
    features = account.get("features", {})
    if not isinstance(features, dict):
        raise ValueError("WPS_LOCAL_FEATURES_INVALID")
    try:
        features_json = json.dumps(features, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("WPS_LOCAL_FEATURES_INVALID") from exc
    config_version = str(account.get("config_version") or "")
    heartbeat_interval_seconds = int(account.get("heartbeat_interval_seconds") or 0)
    if heartbeat_interval_seconds < 0:
        raise ValueError("WPS_LOCAL_HEARTBEAT_INTERVAL_INVALID")
    conn = _connect()
    try:
        conn.execute(
            """INSERT INTO local_account
               (singleton_id,server_origin,username,user_id,device_id,user_status,device_name,platform,device_status,password_cipher,session_token_cipher,device_key_cipher,session_created_at,session_expires_at,features_json,config_version,heartbeat_interval_seconds,remember_password,auto_login,updated_at)
               VALUES (1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(singleton_id) DO UPDATE SET
                 server_origin=excluded.server_origin,
                 username=excluded.username,
                 user_id=excluded.user_id,
                 device_id=excluded.device_id,
                 user_status=excluded.user_status,
                 device_name=excluded.device_name,
                 platform=excluded.platform,
                 device_status=excluded.device_status,
                 password_cipher=excluded.password_cipher,
                 session_token_cipher=excluded.session_token_cipher,
                 device_key_cipher=excluded.device_key_cipher,
                 session_created_at=excluded.session_created_at,
                 session_expires_at=excluded.session_expires_at,
                 features_json=excluded.features_json,
                 config_version=excluded.config_version,
                 heartbeat_interval_seconds=excluded.heartbeat_interval_seconds,
                 remember_password=excluded.remember_password,
                 auto_login=excluded.auto_login,
                 updated_at=excluded.updated_at""",
            (
                account["server_origin"],
                account["username"],
                account["user_id"],
                account["device_id"],
                user_status,
                device_name,
                platform,
                device_status,
                password_cipher,
                token_cipher,
                device_cipher,
                session_created_at,
                int(account["session_expires_at"]),
                features_json,
                config_version,
                heartbeat_interval_seconds,
                int(remember_password),
                int(auto_login),
                int(time.time()),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def update_preferences(*, remember_password: bool, auto_login: bool) -> dict:
    if auto_login and not remember_password:
        raise ValueError("WPS_AUTO_LOGIN_REQUIRES_REMEMBER_PASSWORD")
    account = load_account()
    if not account:
        raise RuntimeError("WPS_LOCAL_ACCOUNT_MISSING")
    if remember_password and not account.get("password"):
        raise ValueError("WPS_REMEMBER_PASSWORD_REQUIRES_LOGIN")
    account["remember_password"] = bool(remember_password)
    account["auto_login"] = bool(auto_login)
    if not remember_password:
        account["password"] = ""
    save_account(account)
    return account


def clear_account() -> int:
    if not local_account_path().is_file():
        return 0
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        deleted_count = int(
            conn.execute("SELECT COUNT(*) FROM format_result_outbox").fetchone()[0]
        )
        conn.execute("DELETE FROM local_account WHERE singleton_id=1")
        conn.execute("DELETE FROM format_result_outbox")
        conn.commit()
        return deleted_count
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def invalidate_session() -> dict:
    """Clear only invalid session credentials while preserving the account and outbox."""
    if not local_account_path().is_file():
        return {}
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT 1 FROM local_account WHERE singleton_id=1"
        ).fetchone()
        if row is None:
            conn.commit()
            return {}
        conn.execute(
            """UPDATE local_account
               SET session_token_cipher=X'',session_expires_at=0,auto_login=0,updated_at=?
               WHERE singleton_id=1""",
            (int(time.time()),),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return load_account()


def enqueue_format_result(payload: dict) -> bool:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT request_id,status,duration_ms,error_code,document_name,app_version "
            "FROM format_result_outbox WHERE request_id=?",
            (payload["request_id"],),
        ).fetchone()
        expected = {
            "request_id": payload["request_id"],
            "status": payload["status"],
            "duration_ms": int(payload["duration_ms"]),
            "error_code": payload["error_code"],
            "document_name": str(payload.get("document_name") or ""),
            "app_version": payload["app_version"],
        }
        if row is not None:
            if dict(row) != expected:
                raise RuntimeError("WPS_FORMAT_RESULT_QUEUE_CONFLICT")
            return True
        conn.execute(
            "INSERT INTO format_result_outbox "
            "(request_id,status,duration_ms,error_code,document_name,app_version,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                expected["request_id"],
                expected["status"],
                expected["duration_ms"],
                expected["error_code"],
                expected["document_name"],
                expected["app_version"],
                int(time.time()),
            ),
        )
        conn.commit()
        return False
    finally:
        conn.close()


def list_format_results() -> list:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT request_id,status,duration_ms,error_code,document_name,app_version "
            "FROM format_result_outbox ORDER BY created_at, rowid"
        ).fetchall()
        results = []
        for row in rows:
            result = dict(row)
            if not result["document_name"]:
                result.pop("document_name")
            results.append(result)
        return results
    finally:
        conn.close()


def delete_format_result(request_id: str) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM format_result_outbox WHERE request_id=?", (request_id,))
        conn.commit()
    finally:
        conn.close()


def count_format_results() -> int:
    conn = _connect()
    try:
        return int(conn.execute("SELECT COUNT(*) FROM format_result_outbox").fetchone()[0])
    finally:
        conn.close()
