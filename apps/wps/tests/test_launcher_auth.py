import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from apps.wps.account_runtime import (
    AccountRuntime,
    account_from_response,
    merge_account_snapshot,
)
from apps.wps.public_api import PublicApiError, WpsPublicApi


class _Store:
    def __init__(self):
        self.saved = None
        self.cleared = False
        self.invalidated = False
        self.results = {}

    def save_account(self, account):
        self.saved = dict(account)

    def clear_account(self):
        self.cleared = True
        deleted_count = len(self.results)
        self.results.clear()
        return deleted_count

    def invalidate_session(self):
        self.invalidated = True
        return {}

    def enqueue_format_result(self, payload):
        existing = self.results.get(payload["request_id"])
        if existing is not None and existing != payload:
            raise RuntimeError("WPS_FORMAT_RESULT_QUEUE_CONFLICT")
        self.results[payload["request_id"]] = dict(payload)
        return existing is not None

    def list_format_results(self):
        return list(self.results.values())

    def delete_format_result(self, request_id):
        self.results.pop(request_id, None)

    def count_format_results(self):
        return len(self.results)


def _account(expires=200):
    return {
        "server_origin": "http://127.0.0.1:9527",
        "username": "User01",
        "user_id": "wusr_1",
        "device_id": "wdev_1",
        "user_status": "active",
        "device_name": "测试电脑",
        "platform": "windows",
        "device_status": "active",
        "password": "Pass01",
        "session_token": "old-token",
        "device_key": "device-key-001",
        "session_created_at": 100,
        "session_expires_at": expires,
        "features": {"controlled": [{"command": "apply", "enabled": True}]},
        "config_version": "config-1",
        "heartbeat_interval_seconds": 600,
        "remember_password": True,
        "auto_login": False,
    }


class _Api:
    origin = "http://127.0.0.1:9527"

    def login(self, _payload):
        raise AssertionError("AccountRuntime must not submit saved credentials in the background")

    def heartbeat(self, token, payload):
        return {
            "token": token,
            "device_id": payload["device_id"],
            "account_status": "active",
            "device_status": "active",
            "session_expires_at": 86500,
            "heartbeat_interval_seconds": 600,
            "features": {"controlled": [{"command": "apply", "enabled": True}]},
            "config_version": "config-2",
        }

    def current_user(self, _token):
        return {
            "user": {"id": "wusr_1", "username": "User01", "status": "active"},
            "device": {
                "id": "wdev_1",
                "device_name": "测试电脑",
                "platform": "windows",
                "status": "active",
            },
            "session_created_at": 100,
            "session_expires_at": 86500,
            "features": {"controlled": [{"command": "apply", "enabled": True}]},
            "config_version": "config-2",
            "heartbeat_interval_seconds": 600,
        }

    def authorize_format(self, token, payload):
        return {"allowed": True, "token": token, **payload}

    def report_format_result(self, token, payload):
        return {"reported": True, "token": token, **payload}

    def logout(self, token):
        return {"logged_out": True, "token": token}


def test_account_bootstrap_snapshot_creates_and_merges_without_replacing_local_credentials():
    api = _Api()
    response = {**api.current_user("old-token"), "session_token": "new-token"}

    created = account_from_response(
        response,
        origin=api.origin,
        username="User01",
        password="Pass01",
        device_key="device-key-001",
        remember_password=True,
        auto_login=False,
    )
    merged = merge_account_snapshot(
        {**created, "password": "LocalPass01", "session_token": "local-token"},
        api.current_user("local-token"),
    )

    assert created["session_token"] == "new-token"
    assert created["heartbeat_interval_seconds"] == 600
    assert merged["config_version"] == "config-2"
    assert merged["password"] == "LocalPass01"
    assert merged["session_token"] == "local-token"
    assert merged["device_key"] == "device-key-001"


def test_account_bootstrap_snapshot_rejects_missing_required_fields():
    response = {**_Api().current_user("old-token"), "session_token": "new-token"}
    response.pop("heartbeat_interval_seconds")

    with pytest.raises(PublicApiError) as exc_info:
        account_from_response(
            response,
            origin="http://127.0.0.1:9527",
            username="User01",
            password="Pass01",
            device_key="device-key-001",
        )

    assert exc_info.value.code == "WPS_PUBLIC_RESPONSE_INVALID"


def test_account_runtime_keeps_bootstrap_notifications_in_memory_and_confirms_by_id(monkeypatch):
    notification = {
        "notification_id": "wnot_1234567890abcdef1234567890abcdef",
        "title": "服务维护",
        "body": "通知正文只在运行期保存。",
        "level": "warning",
        "created_at": 1000,
    }

    class NotificationApi(_Api):
        def __init__(self):
            self.calls = []

        def acknowledge_notifications(self, token, notification_ids):
            self.calls.append((token, notification_ids))
            return {"acknowledged_notification_ids": notification_ids}

    response = {
        **_Api().current_user("old-token"),
        "session_token": "new-token",
        "notifications": [notification, {**notification}],
    }
    account = account_from_response(
        response,
        origin="http://127.0.0.1:9527",
        username="User01",
        password="Pass01",
        device_key="device-key-001",
    )
    store = _Store()
    events = []
    monkeypatch.setattr(
        "apps.wps.account_runtime.log_event",
        lambda _level, _component, event, _message, fields=None: events.append(
            (event, fields or {})
        ),
    )
    api = NotificationApi()
    runtime = AccountRuntime(account, api, store=store, now_func=lambda: 100)

    assert "_runtime_notifications" not in runtime._account
    assert runtime.summary()["notifications"] == [notification]
    assert runtime.acknowledge_notifications([notification["notification_id"]]) == {
        "acknowledged_notification_ids": [notification["notification_id"]]
    }
    assert api.calls == [("new-token", [notification["notification_id"]])]
    assert runtime.summary()["notifications"] == []
    assert [event for event, _fields in events] == [
        "account.notification.acknowledged"
    ]
    assert all("通知正文只在运行期保存。" not in str(fields) for _event, fields in events)


def test_heartbeat_merges_optional_notifications_without_persisting_them():
    notification = {
        "notification_id": "wnot_abcdef1234567890abcdef1234567890",
        "title": "版本提示",
        "body": "请保持应用运行。",
        "level": "info",
        "created_at": 1001,
    }

    class NotificationHeartbeatApi(_Api):
        def heartbeat(self, token, payload):
            return {**super().heartbeat(token, payload), "notifications": [notification]}

    store = _Store()
    runtime = AccountRuntime(
        _account(), NotificationHeartbeatApi(), store=store, now_func=lambda: 100
    )

    runtime.heartbeat_once()

    assert runtime.summary()["notifications"] == [notification]
    assert "notifications" not in store.saved


def test_expired_local_session_enters_reauthentication_without_background_login():
    store = _Store()
    runtime = AccountRuntime(_account(), _Api(), store=store, now_func=lambda: 500)
    requests = []
    runtime.set_reauth_callback(lambda: requests.append("reauth"))

    with pytest.raises(PublicApiError, match="SESSION_EXPIRED"):
        runtime.authorize_format("pane-request-001")

    assert store.invalidated is True
    assert runtime.summary()["reauth_required"] is True
    assert runtime.summary()["apply_available"] is False
    assert requests == ["reauth"]


def test_expired_session_without_remembered_password_requires_login():
    runtime = AccountRuntime(
        {
            **_account(expires=0),
            "password": "",
            "remember_password": False,
            "auto_login": False,
        },
        _Api(),
        store=_Store(),
        now_func=lambda: 500,
    )

    with pytest.raises(PublicApiError) as exc_info:
        runtime.ensure_session()
    assert exc_info.value.code == "SESSION_EXPIRED"


def test_logout_clears_session_and_auto_login_but_keeps_remembered_password():
    store = _Store()
    runtime = AccountRuntime(
        {
            **_account(),
            "remember_password": True,
            "auto_login": True,
        },
        _Api(),
        store=store,
    )

    runtime.logout()

    assert store.saved["session_token"] == ""
    assert store.saved["session_expires_at"] == 0
    assert store.saved["auto_login"] is False
    assert store.saved["password"] == "Pass01"


def test_runtime_reloads_preferences_without_reauthentication():
    store = _Store()
    store.load_account = lambda: {
        **_account(),
        "auto_login": False,
    }
    runtime = AccountRuntime(_account(), _Api(), store=store, now_func=lambda: 100)

    runtime.reload_account()

    assert runtime._account["auto_login"] is False


def test_public_api_sends_bearer_and_request_id():
    observed = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers["Content-Length"])
            observed.update(
                path=self.path,
                authorization=self.headers.get("Authorization"),
                request_id=self.headers.get("X-DocxTool-Request-Id"),
                body=json.loads(self.rfile.read(length)),
            )
            body = json.dumps(
                {
                    "ok": True,
                    "api_version": "wps-api-v1",
                    "request_id": observed["request_id"],
                    "server_time": 1,
                    "data": {"allowed": True, "request_id": observed["request_id"]},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        api = WpsPublicApi(f"http://127.0.0.1:{server.server_address[1]}")
        result = api.authorize_format(
            "session-token",
            {"request_id": "pane-request-001", "command": "apply", "app_version": "5.1"},
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)

    assert result == {"allowed": True, "request_id": "pane-request-001"}
    assert observed["path"] == "/wps-api/v1/format/authorize"
    assert observed["authorization"] == "Bearer session-token"
    assert observed["request_id"] == "pane-request-001"


def test_public_api_rejects_a_mismatched_response_request_id(monkeypatch):
    class Response:
        status = 200

        def read(self):
            return json.dumps(
                {
                    "ok": True,
                    "api_version": "wps-api-v1",
                    "request_id": "different-request",
                    "server_time": 1,
                    "data": {
                        "allowed": True,
                        "request_id": "different-request",
                    },
                }
            ).encode("utf-8")

    monkeypatch.setattr("apps.wps.public_api.urlopen", lambda *_args, **_kwargs: Response())
    api = WpsPublicApi("http://127.0.0.1:9527")
    with pytest.raises(PublicApiError) as exc_info:
        api.authorize_format(
            "session-token",
            {
                "request_id": "pane-request-001",
                "command": "apply",
                "app_version": "5.1",
            },
        )
    assert exc_info.value.code == "WPS_PUBLIC_REQUEST_ID_MISMATCH"


def test_public_api_posts_notification_display_acknowledgement(monkeypatch):
    observed = {}
    api = WpsPublicApi("http://127.0.0.1:9527")
    monkeypatch.setattr(
        api,
        "_request",
        lambda method, path, payload, *, token="", request_id="": observed.update(
            method=method,
            path=path,
            payload=payload,
            token=token,
            request_id=request_id,
        )
        or {"acknowledged_notification_ids": payload["notification_ids"]},
    )

    result = api.acknowledge_notifications(
        "session-token",
        ["wnot_1234567890abcdef1234567890abcdef"],
    )

    assert result == {
        "acknowledged_notification_ids": ["wnot_1234567890abcdef1234567890abcdef"]
    }
    assert observed == {
        "method": "POST",
        "path": "/notifications/read",
        "payload": {
            "notification_ids": ["wnot_1234567890abcdef1234567890abcdef"]
        },
        "token": "session-token",
        "request_id": "",
    }


def test_public_api_network_failure_is_distinct():
    api = WpsPublicApi("http://127.0.0.1:1", timeout=1)
    with pytest.raises(PublicApiError) as exc_info:
        api.current_user("session-token")
    assert exc_info.value.code == "WPS_PUBLIC_SERVER_UNAVAILABLE"
    assert exc_info.value.network is True


def test_public_api_rejects_insecure_public_origin():
    for origin in (
        "http://example.com",
        "https://",
        "https://user:password@example.com",
        "https://example.com:99999",
    ):
        with pytest.raises(RuntimeError, match="WPS_SERVER_ORIGIN_INVALID"):
            WpsPublicApi(origin)


def test_public_authorization_failure_disables_only_controlled_feature():
    class FailingApi(_Api):
        def authorize_format(self, token, payload):
            raise PublicApiError("WPS_PUBLIC_SERVER_UNAVAILABLE", "offline", network=True)

    runtime = AccountRuntime(_account(), FailingApi(), store=_Store(), now_func=lambda: 100)
    with pytest.raises(PublicApiError, match="WPS_PUBLIC_SERVER_UNAVAILABLE"):
        runtime.authorize_format("pane-request-001")

    summary = runtime.summary()
    assert summary["network_available"] is False
    assert summary["apply_available"] is False
    assert summary["error_code"] == "WPS_PUBLIC_SERVER_UNAVAILABLE"


def test_public_business_error_keeps_server_reachable():
    class ConflictApi(_Api):
        def authorize_format(self, token, payload):
            raise PublicApiError("REQUEST_STATUS_CONFLICT", "conflict", 409)

    runtime = AccountRuntime(_account(), ConflictApi(), store=_Store(), now_func=lambda: 100)
    with pytest.raises(PublicApiError, match="REQUEST_STATUS_CONFLICT"):
        runtime.authorize_format("pane-request-001")

    summary = runtime.summary()
    assert summary["network_available"] is True
    assert summary["apply_available"] is True
    assert summary["error_code"] == "REQUEST_STATUS_CONFLICT"


def test_heartbeat_logs_only_state_changes(monkeypatch):
    events = []
    failures = [
        PublicApiError("WPS_PUBLIC_SERVER_UNAVAILABLE", "offline", network=True),
        PublicApiError("WPS_PUBLIC_SERVER_UNAVAILABLE", "offline", network=True),
    ]

    class RecoveringApi(_Api):
        def heartbeat(self, token, payload):
            if failures:
                raise failures.pop(0)
            return super().heartbeat(token, payload)

    monkeypatch.setattr(
        "apps.wps.account_runtime.log_event",
        lambda level, component, event, message, fields=None: events.append(
            (event, message)
        ),
    )
    runtime = AccountRuntime(_account(), RecoveringApi(), store=_Store(), now_func=lambda: 100)

    with pytest.raises(PublicApiError):
        runtime.heartbeat_once()
    with pytest.raises(PublicApiError):
        runtime.heartbeat_once()
    runtime.heartbeat_once()

    assert events == [
        ("account.heartbeat.failed", "服务器无法连接"),
        ("account.heartbeat.recovered", "WPS 账号心跳已恢复"),
    ]


def test_heartbeat_logs_recovery_after_previously_online(monkeypatch):
    events = []

    class IntermittentApi(_Api):
        def __init__(self):
            self.calls = 0

        def heartbeat(self, token, payload):
            self.calls += 1
            if self.calls == 2:
                raise PublicApiError("WPS_PUBLIC_SERVER_UNAVAILABLE", "offline", network=True)
            return super().heartbeat(token, payload)

    monkeypatch.setattr(
        "apps.wps.account_runtime.log_event",
        lambda level, component, event, message, fields=None: events.append(event),
    )
    runtime = AccountRuntime(_account(), IntermittentApi(), store=_Store(), now_func=lambda: 100)

    runtime.heartbeat_once()
    with pytest.raises(PublicApiError):
        runtime.heartbeat_once()
    runtime.heartbeat_once()

    assert events == [
        "account.heartbeat.online",
        "account.heartbeat.failed",
        "account.heartbeat.recovered",
    ]


def test_invalid_server_session_requires_one_ui_reauthentication_and_preserves_outbox():
    class ExpiredApi(_Api):
        def heartbeat(self, token, payload):
            raise PublicApiError("SESSION_EXPIRED", "expired", 401)

    store = _Store()
    runtime = AccountRuntime(_account(), ExpiredApi(), store=store, now_func=lambda: 100)
    requests = []
    runtime.set_reauth_callback(lambda: requests.append("reauth"))
    with pytest.raises(PublicApiError, match="SESSION_EXPIRED"):
        runtime.heartbeat_once()

    assert runtime.summary()["apply_available"] is False
    assert runtime.summary()["reauth_required"] is True
    assert store.invalidated is True
    assert requests == ["reauth"]
    with pytest.raises(PublicApiError, match="SESSION_EXPIRED"):
        runtime.ensure_session()


def test_pending_result_survives_network_failure_and_flushes_after_recovery():
    class RecoveringApi(_Api):
        def __init__(self):
            self.report_calls = 0

        def report_format_result(self, token, payload):
            self.report_calls += 1
            if self.report_calls == 1:
                raise PublicApiError(
                    "WPS_PUBLIC_SERVER_UNAVAILABLE", "offline", network=True
                )
            return super().report_format_result(token, payload)

    runtime = AccountRuntime(
        _account(), RecoveringApi(), store=_Store(), now_func=lambda: 100
    )
    runtime.report_format_result("request-1", "success", 120, "", "会议纪要.docx")

    with pytest.raises(PublicApiError, match="WPS_PUBLIC_SERVER_UNAVAILABLE"):
        runtime._flush_pending_results()
    assert runtime.summary()["pending_result_count"] == 1
    assert runtime.summary()["network_available"] is False

    assert runtime._store.results["request-1"]["document_name"] == "会议纪要.docx"

    runtime._flush_pending_results()
    assert runtime.summary()["pending_result_count"] == 0
    assert runtime.summary()["network_available"] is True


def test_pending_result_conflict_is_removed_and_identical_enqueue_is_reused():
    class ConflictApi(_Api):
        def report_format_result(self, token, payload):
            raise PublicApiError("REQUEST_STATUS_CONFLICT", "conflict", 409)

    runtime = AccountRuntime(
        _account(), ConflictApi(), store=_Store(), now_func=lambda: 100
    )
    first = runtime.report_format_result("request-1", "success", 120, "")
    second = runtime.report_format_result("request-1", "success", 120, "")

    assert first["reused"] is False
    assert second["reused"] is True
    assert runtime.summary()["pending_result_count"] == 1

    runtime._flush_pending_results()

    assert runtime.summary()["pending_result_count"] == 0
    assert runtime.summary()["network_available"] is True
    assert runtime.summary()["error_code"] == "REQUEST_STATUS_CONFLICT"


def test_account_rejection_preserves_pending_results_and_requires_reauthentication(monkeypatch):
    events = []

    class RejectedApi(_Api):
        def report_format_result(self, token, payload):
            raise PublicApiError("ACCOUNT_DISABLED", "disabled", 403)

    monkeypatch.setattr(
        "apps.wps.account_runtime.log_event",
        lambda level, component, event, message, fields=None: events.append((event, fields or {})),
    )
    store = _Store()
    runtime = AccountRuntime(_account(), RejectedApi(), store=store, now_func=lambda: 100)
    runtime.report_format_result("request-rejected", "success", 120, "")

    with pytest.raises(PublicApiError, match="ACCOUNT_DISABLED"):
        runtime._flush_pending_results()

    assert store.cleared is False
    assert store.invalidated is True
    assert runtime.summary()["pending_result_count"] == 1
    assert runtime.summary()["reauth_required"] is True
    assert any(item[0] == "account.reauth.required" for item in events)
    assert any(item[0] == "account.format_result.deferred" for item in events)


def test_session_expiry_preserves_pending_result(monkeypatch):
    events = []

    class ExpiredResultApi(_Api):
        def report_format_result(self, token, payload):
            raise PublicApiError("SESSION_EXPIRED", "expired", 401)

    monkeypatch.setattr(
        "apps.wps.account_runtime.log_event",
        lambda level, component, event, message, fields=None: events.append(event),
    )
    store = _Store()
    runtime = AccountRuntime(_account(), ExpiredResultApi(), store=store, now_func=lambda: 100)
    runtime.report_format_result("request-expired", "success", 120, "")

    with pytest.raises(PublicApiError, match="SESSION_EXPIRED"):
        runtime._flush_pending_results()

    assert store.cleared is False
    assert runtime.summary()["pending_result_count"] == 1
    assert "account.format_result.deferred" in events


def test_heartbeat_thread_logs_unexpected_failure_and_stops(monkeypatch):
    events = []
    monkeypatch.setattr(
        "apps.wps.account_runtime.log_event",
        lambda level, component, event, message, fields=None: events.append(event),
    )
    runtime = AccountRuntime(_account(), _Api(), store=_Store(), now_func=lambda: 100)
    monkeypatch.setattr(
        runtime,
        "heartbeat_once",
        lambda: (_ for _ in ()).throw(RuntimeError("unexpected")),
    )

    runtime.start()
    runtime._thread.join(timeout=1)

    assert runtime._thread.is_alive() is False
    assert runtime.summary()["network_available"] is True
    assert runtime.summary()["error_code"] == "WPS_ACCOUNT_HEARTBEAT_THREAD_FAILED"
    assert events == ["account.heartbeat.thread.failed"]


def test_stop_preserves_pending_results_in_store(monkeypatch):
    events = []
    monkeypatch.setattr(
        "apps.wps.account_runtime.log_event",
        lambda level, component, event, message, fields=None: events.append(event),
    )
    store = _Store()
    runtime = AccountRuntime(_account(), _Api(), store=store, now_func=lambda: 100)
    runtime.report_format_result("request-1", "success", 120, "")

    runtime.stop()

    assert runtime.summary()["pending_result_count"] == 1
    assert events == ["account.format_result.queued"]


def test_new_runtime_flushes_result_left_by_previous_runtime():
    store = _Store()
    first = AccountRuntime(_account(), _Api(), store=store, now_func=lambda: 100)
    first.report_format_result("request-1", "success", 120, "")
    first.stop()

    second = AccountRuntime(_account(), _Api(), store=store, now_func=lambda: 100)
    assert second.summary()["pending_result_count"] == 1
    second._flush_pending_results()
    assert second.summary()["pending_result_count"] == 0
