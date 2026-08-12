import http.client
import json
import logging
import threading

from docxtool.web import app as server
from docxtool.wps_server import database
from docxtool.wps_server.admin import overview


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

        status, current = request(
            "/wps-api/v1/auth/me",
            method="GET",
            token=registration_token,
        )
        assert status == 200
        assert current["data"]["user"]["username"] == "HttpUser01"

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

        status, heartbeat = request(
            "/wps-api/v1/heartbeat",
            {"device_id": device_id, "app_version": "5.1"},
            token=token,
        )
        assert status == 200
        assert heartbeat["data"]["session_expires_at"] == 1000 + 7 * 24 * 60 * 60

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
    assert summary == {"users": 1, "online_devices": 1, "requests": 1, "pending": 0}
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
