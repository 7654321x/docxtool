import logging
import sqlite3
import threading

import pytest

from docxtool.wps_server import database
from docxtool.wps_server.admin import list_users, overview, set_device_status, set_user_status
from docxtool.wps_server.auth import WpsAuthError, authenticated_session
from docxtool.wps_server.service import login_user, register_user


def _seed(tmp_path):
    path = tmp_path / "wps_plugin.db"

    def connect():
        return database.connect(path)

    lock = threading.Lock()
    database.initialize_database(connect, lock)
    registered = register_user(
        {
            "username": "User01",
            "password": "Pass01",
            "device": {
                "device_key": "device-key-001",
                "device_name": "测试电脑",
                "platform": "windows",
                "app_version": "5.1",
            },
        },
        connect_func=connect,
        sql_lock=lock,
        client_ip="127.0.0.1",
        now_func=lambda: 1000,
        config_version="config-1",
    )
    return path, connect, lock, registered


def test_admin_summary_search_and_status_changes(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="docx_tool")
    path, connect, lock, registered = _seed(tmp_path)
    summary = overview(connect_func=connect, sql_lock=lock, now=1100)
    rows = list_users(connect_func=connect, sql_lock=lock, now=1100, query="user01")

    assert summary == {"users": 1, "online_devices": 1, "requests": 0, "pending": 0}
    assert len(rows) == 1
    assert rows[0]["device_count"] == 1

    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            "ALTER TABLE wps_users ADD COLUMN display_name TEXT NOT NULL DEFAULT ''"
        )
        conn.execute("UPDATE wps_users SET display_name='Legacy Alias'")
        conn.commit()
    assert list_users(
        connect_func=connect,
        sql_lock=lock,
        now=1100,
        query="legacy alias",
    ) == []

    set_user_status(registered["user"]["id"], "disabled", connect_func=connect, sql_lock=lock, now=1200)
    with sqlite3.connect(str(path)) as conn:
        assert conn.execute("SELECT status FROM wps_users").fetchone()[0] == "disabled"
        assert conn.execute("SELECT COUNT(*) FROM wps_sessions").fetchone()[0] == 0
    with pytest.raises(WpsAuthError, match="SESSION_INVALID"):
        authenticated_session(
            {"Authorization": f"Bearer {registered['session_token']}"},
            connect_func=connect,
            sql_lock=lock,
            now_func=lambda: 1201,
        )

    set_user_status(registered["user"]["id"], "active", connect_func=connect, sql_lock=lock, now=1300)
    logged_in = login_user(
        {
            "username": "User01",
            "password": "Pass01",
            "device": {
                "device_key": "device-key-001",
                "device_name": "测试电脑",
                "platform": "windows",
                "app_version": "5.1",
            },
        },
        connect_func=connect,
        sql_lock=lock,
        client_ip="127.0.0.1",
        now_func=lambda: 1301,
        config_version="config-1",
    )
    set_device_status(registered["device"]["id"], "disabled", connect_func=connect, sql_lock=lock)
    with sqlite3.connect(str(path)) as conn:
        assert conn.execute("SELECT status FROM wps_devices").fetchone()[0] == "disabled"
    with pytest.raises(WpsAuthError, match="SESSION_INVALID"):
        authenticated_session(
            {"Authorization": f"Bearer {logged_in['session_token']}"},
            connect_func=connect,
            sql_lock=lock,
            now_func=lambda: 1302,
        )
    assert "wps.admin.user.status_changed" in caplog.text
    assert "wps.admin.device.status_changed" in caplog.text
