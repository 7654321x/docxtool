"""Single-account local storage protected by Windows DPAPI."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import time

CRYPTPROTECT_UI_FORBIDDEN = 0x1


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
    conn.execute(
        """CREATE TABLE IF NOT EXISTS local_account (
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
    return conn


def load_account() -> dict:
    if not local_account_path().is_file():
        return {}
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM local_account WHERE singleton_id=1").fetchone()
    finally:
        conn.close()
    if row is None:
        return {}
    return {
        "server_origin": row["server_origin"],
        "username": row["username"],
        "user_id": row["user_id"],
        "device_id": row["device_id"],
        "password": decrypt_secret(bytes(row["password_cipher"])),
        "session_token": decrypt_secret(bytes(row["session_token_cipher"])),
        "device_key": decrypt_secret(bytes(row["device_key_cipher"])),
        "session_expires_at": int(row["session_expires_at"]),
    }


def save_account(account: dict) -> None:
    required = {
        "server_origin",
        "username",
        "user_id",
        "device_id",
        "password",
        "session_token",
        "device_key",
        "session_expires_at",
    }
    if not isinstance(account, dict) or not required.issubset(account):
        raise ValueError("WPS_LOCAL_ACCOUNT_INVALID")
    password_cipher = encrypt_secret(account["password"])
    token_cipher = encrypt_secret(account["session_token"])
    device_cipher = encrypt_secret(account["device_key"])
    conn = _connect()
    try:
        conn.execute(
            """INSERT INTO local_account
               (singleton_id,server_origin,username,user_id,device_id,password_cipher,session_token_cipher,device_key_cipher,session_expires_at,updated_at)
               VALUES (1,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(singleton_id) DO UPDATE SET
                 server_origin=excluded.server_origin,
                 username=excluded.username,
                 user_id=excluded.user_id,
                 device_id=excluded.device_id,
                 password_cipher=excluded.password_cipher,
                 session_token_cipher=excluded.session_token_cipher,
                 device_key_cipher=excluded.device_key_cipher,
                 session_expires_at=excluded.session_expires_at,
                 updated_at=excluded.updated_at""",
            (
                account["server_origin"],
                account["username"],
                account["user_id"],
                account["device_id"],
                password_cipher,
                token_cipher,
                device_cipher,
                int(account["session_expires_at"]),
                int(time.time()),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def clear_account() -> None:
    if not local_account_path().is_file():
        return
    conn = _connect()
    try:
        conn.execute("DELETE FROM local_account WHERE singleton_id=1")
        conn.commit()
    finally:
        conn.close()
