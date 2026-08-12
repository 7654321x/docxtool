import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from apps.wps.account_runtime import AccountRuntime
from apps.wps.public_api import PublicApiError, WpsPublicApi


class _Store:
    def __init__(self):
        self.saved = None
        self.cleared = False

    def save_account(self, account):
        self.saved = dict(account)

    def clear_account(self):
        self.cleared = True


def _account(expires=200):
    return {
        "server_origin": "http://127.0.0.1:9527",
        "username": "User01",
        "user_id": "wusr_1",
        "device_id": "wdev_1",
        "password": "Pass01",
        "session_token": "old-token",
        "device_key": "device-key-001",
        "session_expires_at": expires,
    }


class _Api:
    origin = "http://127.0.0.1:9527"

    def login(self, payload):
        assert payload["username"] == "User01"
        return {
            "user": {"id": "wusr_1", "username": "User01", "status": "active"},
            "device": {"id": "wdev_1"},
            "session_token": "new-token",
            "session_expires_at": 86500,
        }

    def heartbeat(self, token, payload):
        return {"token": token, "device_id": payload["device_id"]}

    def authorize_format(self, token, payload):
        return {"allowed": True, "token": token, **payload}

    def report_format_result(self, token, payload):
        return {"reported": True, "token": token, **payload}


def test_expired_local_session_is_refreshed_and_saved():
    store = _Store()
    runtime = AccountRuntime(_account(), _Api(), store=store, now_func=lambda: 500)

    assert runtime.ensure_session() == "new-token"
    assert store.saved["session_token"] == "new-token"
    assert runtime.authorize_format("pane-request-001")["allowed"] is True


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
        lambda level, component, event, message, fields=None: events.append(event),
    )
    runtime = AccountRuntime(_account(), RecoveringApi(), store=_Store(), now_func=lambda: 100)

    with pytest.raises(PublicApiError):
        runtime.heartbeat_once()
    with pytest.raises(PublicApiError):
        runtime.heartbeat_once()
    runtime.heartbeat_once()

    assert events == ["account.heartbeat.failed", "account.heartbeat.online"]


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


def test_invalid_server_session_forces_next_silent_login():
    class ExpiredApi(_Api):
        def heartbeat(self, token, payload):
            raise PublicApiError("SESSION_EXPIRED", "expired", 401)

    store = _Store()
    runtime = AccountRuntime(_account(), ExpiredApi(), store=store, now_func=lambda: 100)
    with pytest.raises(PublicApiError, match="SESSION_EXPIRED"):
        runtime.heartbeat_once()

    assert runtime.summary()["apply_available"] is False
    assert runtime.ensure_session() == "new-token"
    assert store.saved["session_token"] == "new-token"


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
    runtime.report_format_result("request-1", "success", 120, "")

    with pytest.raises(PublicApiError, match="WPS_PUBLIC_SERVER_UNAVAILABLE"):
        runtime._flush_pending_results()
    assert runtime.summary()["pending_result_count"] == 1
    assert runtime.summary()["network_available"] is False

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
    assert runtime.summary()["error_code"] == "WPS_ACCOUNT_HEARTBEAT_THREAD_FAILED"
    assert events == ["account.heartbeat.thread.failed"]


def test_stop_discards_pending_results_from_memory(monkeypatch):
    events = []
    monkeypatch.setattr(
        "apps.wps.account_runtime.log_event",
        lambda level, component, event, message, fields=None: events.append(event),
    )
    runtime = AccountRuntime(_account(), _Api(), store=_Store(), now_func=lambda: 100)
    runtime.report_format_result("request-1", "success", 120, "")

    runtime.stop()

    assert runtime.summary()["pending_result_count"] == 0
    assert events == [
        "account.format_result.queued",
        "account.format_result.discarded",
    ]
