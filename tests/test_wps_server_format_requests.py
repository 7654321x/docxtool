import logging
import sqlite3
import threading

import pytest

from docxtool.wps_server import database
from docxtool.wps_server.auth import authenticated_session
from docxtool.wps_server.service import (
    WpsServiceError,
    authorize_format,
    record_format_result,
    register_user,
)


def _context(tmp_path):
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
    principal = authenticated_session(
        {"Authorization": f"Bearer {registered['session_token']}"},
        connect_func=connect,
        sql_lock=lock,
        now_func=lambda: 1001,
    )
    return path, connect, lock, principal


def test_authorization_is_recorded_once_and_result_is_terminal(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="docx_tool")
    path, connect, lock, principal = _context(tmp_path)
    payload = {"request_id": "pane-request-001", "command": "apply", "app_version": "5.1"}
    profile = {"config_version": "config-1", "format_config": {"features": {}}}

    first = authorize_format(principal, payload, connect_func=connect, sql_lock=lock, format_profile=profile, now_func=lambda: 1100)
    second = authorize_format(principal, payload, connect_func=connect, sql_lock=lock, format_profile=profile, now_func=lambda: 1101)
    assert first["allowed"] is True and first["reused"] is False
    assert first["request_id"] == "pane-request-001"
    assert second["allowed"] is True and second["reused"] is True
    with pytest.raises(WpsServiceError) as exc_info:
        authorize_format(
            principal,
            payload,
            connect_func=connect,
            sql_lock=lock,
            format_profile={"config_version": "config-2", "format_config": {"features": {"marker": 2}}},
            now_func=lambda: 1102,
        )
    assert exc_info.value.code == "FORMAT_CONFIG_VERSION_CHANGED"
    with sqlite3.connect(str(path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM wps_format_requests").fetchone()[0] == 1
        assert conn.execute("SELECT config_version FROM wps_format_requests").fetchone()[0] == "config-1"

    result = record_format_result(
        principal,
        {"request_id": "pane-request-001", "status": "success", "duration_ms": 4200, "error_code": "", "app_version": "5.1"},
        connect_func=connect,
        sql_lock=lock,
        now_func=lambda: 1200,
    )
    repeated = record_format_result(
        principal,
        {"request_id": "pane-request-001", "status": "success", "duration_ms": 4200, "error_code": "", "app_version": "5.1"},
        connect_func=connect,
        sql_lock=lock,
        now_func=lambda: 1201,
    )
    assert result["reused"] is False
    assert repeated["reused"] is True
    assert "wps.format.authorize.allowed" in caplog.text
    assert "wps.format.authorize.reused" in caplog.text
    assert "wps.format.result.completed" in caplog.text
    assert "wps.format.result.reused" in caplog.text

    after_terminal = authorize_format(
        principal,
        payload,
        connect_func=connect,
        sql_lock=lock,
        format_profile={"config_version": "config-2", "format_config": {"features": {"marker": 2}}},
        now_func=lambda: 1300,
    )
    assert after_terminal["allowed"] is False
    assert after_terminal["request_status"] == "success"
    assert after_terminal["config_version"] == "config-1"

    with pytest.raises(WpsServiceError) as exc_info:
        record_format_result(
            principal,
            {"request_id": "pane-request-001", "status": "failed", "duration_ms": 4300, "error_code": "WPS_FAILED", "app_version": "5.1"},
            connect_func=connect,
            sql_lock=lock,
            now_func=lambda: 1400,
        )
    assert exc_info.value.code == "REQUEST_STATUS_CONFLICT"
