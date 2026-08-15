import http.client
import json
import logging
import re
import threading
from urllib.parse import urlencode

from docxtool.web import app as server
from docxtool.wps_server import database
from docxtool.wps_server.admin import overview, send_notification
from docxtool.wps_server.service import register_user


def test_wps_public_http_flow_updates_admin_statistics(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="docx_tool")
    database_path = tmp_path / "wps_plugin.db"
    monkeypatch.setattr(server, "_WPS_DB_PATH", database_path)
    monkeypatch.setattr(
        server,
        "_WPS_FORMAT_PROFILE",
        {"config_version": "config-http-1", "format_config": {"features": {}}},
    )
    monkeypatch.setattr(server, "_now_unix", lambda: 1000)
    monkeypatch.setattr(server, "_auth_rate_allow", lambda *_args: (True, 0))
    database.initialize_database(server._wps_sql, server._WPS_SQL_LOCK)

    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = int(httpd.server_address[1])

    def request(path, payload=None, *, method="POST", token="", request_id=""):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        body = None
        headers = {}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers.update({"Content-Type": "application/json", "Content-Length": str(len(body))})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if request_id:
            headers["X-DocxTool-Request-Id"] = request_id
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        data = json.loads(response.read().decode("utf-8"))
        status = response.status
        conn.close()
        return status, data

    device = {
        "device_key": "device-key-http-001",
        "device_name": "HTTP 测试电脑",
        "platform": "windows",
        "app_version": "5.1",
    }
    try:
        status, registered = request(
            "/wps-api/v1/auth/register",
            {"username": "HttpUser01", "password": "Pass01", "device": device},
        )
        assert status == 201 and registered["ok"] is True
        registration_token = registered["data"]["session_token"]
        assert registered["data"]["heartbeat_interval_seconds"] == 10 * 60
        assert registered["data"]["notifications"] == []

        status, current = request(
            "/wps-api/v1/auth/me",
            method="GET",
            token=registration_token,
        )
        assert status == 200
        assert current["data"]["user"]["username"] == "HttpUser01"
        assert current["data"]["device"]["id"] == registered["data"]["device"]["id"]
        assert current["data"]["heartbeat_interval_seconds"] == 10 * 60
        assert "session_token" not in current["data"]

        status, logged_out = request(
            "/wps-api/v1/auth/logout",
            {},
            token=registration_token,
        )
        assert status == 200 and logged_out["data"] == {"logged_out": True}

        status, invalid_session = request(
            "/wps-api/v1/auth/me",
            method="GET",
            token=registration_token,
        )
        assert status == 401
        assert invalid_session["error"]["code"] == "SESSION_INVALID"

        status, logged_in = request(
            "/wps-api/v1/auth/login",
            {"username": "httpuser01", "password": "Pass01", "device": device},
        )
        assert status == 200 and logged_in["ok"] is True
        token = logged_in["data"]["session_token"]
        device_id = logged_in["data"]["device"]["id"]
        notification_id = send_notification(
            logged_in["data"]["user"]["id"],
            "服务维护",
            "通知正文只会作为纯文本交给任务窗格。",
            "info",
            connect_func=server._wps_sql,
            sql_lock=server._WPS_SQL_LOCK,
            now=1000,
            actor={"actor_type": "legacy_token", "actor_session_id_short": ""},
            correlation_id="adm_http_notification",
        )

        status, heartbeat = request(
            "/wps-api/v1/heartbeat",
            {"device_id": device_id, "app_version": "5.1"},
            token=token,
        )
        assert status == 200
        assert heartbeat["data"]["session_expires_at"] == 1000 + 7 * 24 * 60 * 60
        assert heartbeat["data"]["heartbeat_interval_seconds"] == 10 * 60
        assert heartbeat["data"]["notifications"] == [
            {
                "notification_id": notification_id,
                "title": "服务维护",
                "body": "通知正文只会作为纯文本交给任务窗格。",
                "level": "info",
                "created_at": 1000,
            }
        ]

        status, acknowledged = request(
            "/wps-api/v1/notifications/read",
            {
                "notification_ids": [
                    notification_id,
                    "wnot_00000000000000000000000000000000",
                ]
            },
            token=token,
        )
        assert status == 200
        assert acknowledged["data"] == {
            "acknowledged_notification_ids": [notification_id]
        }
        status, acknowledged_again = request(
            "/wps-api/v1/notifications/read",
            {"notification_ids": [notification_id]},
            token=token,
        )
        assert status == 200
        assert acknowledged_again["data"] == {"acknowledged_notification_ids": []}

        rejected_request_id = "http-format-rejected-001"
        status, rejected = request(
            "/wps-api/v1/format/authorize",
            {"request_id": rejected_request_id, "command": "preview", "app_version": "5.1"},
            token=token,
            request_id=rejected_request_id,
        )
        assert status == 403
        assert rejected["error"]["code"] == "COMMAND_NOT_ALLOWED"

        request_id = "http-format-request-001"
        status, authorized = request(
            "/wps-api/v1/format/authorize",
            {"request_id": request_id, "command": "apply", "app_version": "5.1"},
            token=token,
            request_id=request_id,
        )
        assert status == 200
        assert authorized["data"]["allowed"] is True
        assert authorized["data"]["request_id"] == request_id
        assert authorized["data"]["config_version"] == "config-http-1"

        status, completed = request(
            "/wps-api/v1/format/result",
            {
                "request_id": request_id,
                "status": "success",
                "duration_ms": 321,
                "error_code": "",
                "app_version": "5.1",
            },
            token=token,
            request_id=request_id,
        )
        assert status == 200 and completed["data"]["status"] == "success"

        status, conflicting = request(
            "/wps-api/v1/format/result",
            {
                "request_id": request_id,
                "status": "failed",
                "duration_ms": 322,
                "error_code": "WPS_FAILED",
                "app_version": "5.1",
            },
            token=token,
            request_id=request_id,
        )
        assert status == 409
        assert conflicting["error"]["code"] == "REQUEST_STATUS_CONFLICT"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)

    summary = overview(connect_func=server._wps_sql, sql_lock=server._WPS_SQL_LOCK, now=1000)
    assert summary == {
        "users": 1,
        "online_devices": 1,
        "requests": 1,
        "pending": 0,
        "success": 1,
        "failed": 0,
        "average_duration_ms": 321.0,
    }
    for event in (
        "wps.device.created",
        "wps.device.online",
        "wps.auth.register.start",
        "wps.auth.session.created",
        "wps.auth.session.deleted",
        "wps.auth.login.start",
        "wps.format.authorize.start",
        "wps.format.authorize.allowed",
        "wps.format.authorize.rejected",
        "wps.format.result.start",
        "wps.format.result.completed",
        "wps.format.result.conflict",
        "wps.notification.acknowledge.start",
        "wps.notification.acknowledge.completed",
        "wps.format_config.returned",
    ):
        assert event in caplog.text
    assert "wps.api.heartbeat.completed" not in caplog.text

    sensitive_values = ("Pass01", "device-key-http-001", token)
    non_auth_responses = (heartbeat, rejected, authorized, completed, conflicting)
    for value in sensitive_values:
        assert value not in caplog.text
        assert all(value not in json.dumps(item, ensure_ascii=False) for item in non_auth_responses)
        assert all(value.encode("utf-8") not in path.read_bytes() for path in tmp_path.glob("wps_plugin.db*"))


def test_wps_admin_http_status_mutation_requires_session_csrf_and_writes_audit(tmp_path, monkeypatch):
    """Exercise the real Handler route from admin login through one gated WPS mutation."""
    web_database_path = tmp_path / "stats.db"
    wps_database_path = tmp_path / "wps_plugin.db"
    monkeypatch.setattr(server, "_DB_PATH", web_database_path)
    monkeypatch.setattr(server, "_WPS_DB_PATH", wps_database_path)
    monkeypatch.setattr(server, "ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setattr(server, "_WPS_ADMIN_MUTATIONS_ENABLED", True)
    server._sql_init()
    registered = register_user(
        {
            "username": "AdminHttp01",
            "password": "Pass01",
            "device": {
                "device_key": "admin-http-device-key",
                "device_name": "HTTP 测试电脑",
                "platform": "windows",
                "app_version": "5.1",
            },
        },
        connect_func=server._wps_sql,
        sql_lock=server._WPS_SQL_LOCK,
        client_ip="127.0.0.1",
        now_func=lambda: 1000,
        config_version="config-http-1",
    )
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = int(httpd.server_address[1])

    def request(path, *, method="GET", form=None, headers=None):
        body = None
        request_headers = dict(headers or {})
        if form is not None:
            body = urlencode(form).encode("utf-8")
            request_headers["Content-Type"] = "application/x-www-form-urlencoded"
            request_headers["Content-Length"] = str(len(body))
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(method, path, body=body, headers=request_headers)
        response = conn.getresponse()
        payload = response.read()
        result = (response.status, dict(response.getheaders()), payload)
        conn.close()
        return result

    user_id = registered["user"]["id"]
    try:
        status, headers, _body = request("/admin?token=test-admin-token")
        assert status == 303
        assert headers["Location"] == "/admin"
        cookie = headers["Set-Cookie"].split(";", 1)[0]

        status, _headers, page = request(
            f"/admin/wps/users/{user_id}?tab=security",
            headers={"Cookie": cookie},
        )
        assert status == 200
        match = re.search(rb'name="csrf_token" value="([^"]+)"', page)
        assert match is not None
        csrf_token = match.group(1).decode("ascii")

        status, _headers, denied = request(
            f"/admin/wps/users/{user_id}/status",
            method="POST",
            form={"status": "disabled"},
            headers={"Cookie": cookie},
        )
        assert status == 403
        assert json.loads(denied.decode("utf-8"))["code"] == "CSRF_INVALID"

        status, headers, _body = request(
            f"/admin/wps/users/{user_id}/status",
            method="POST",
            form={"csrf_token": csrf_token, "status": "disabled"},
            headers={"Cookie": cookie},
        )
        assert status == 303
        assert headers["Location"] == f"/admin/wps/users/{user_id}?tab=security"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)

    with database.connect(wps_database_path) as conn:
        assert conn.execute("SELECT status FROM wps_users WHERE id=?", (user_id,)).fetchone()[0] == "disabled"
        assert conn.execute("SELECT COUNT(*) FROM wps_sessions WHERE user_id=?", (user_id,)).fetchone()[0] == 0
        audit_row = conn.execute(
            "SELECT event,result FROM wps_admin_audit_logs WHERE target_user_id=?",
            (user_id,),
        ).fetchone()
        assert tuple(audit_row) == ("wps.admin.user.status.updated", "success")
