from io import BytesIO
import json

from docxtool.web.routing import match_get_route, match_post_route
from docxtool.wps_server.route_handlers import handle_wps_action


def test_wps_public_routes_are_explicit():
    assert match_get_route("/wps-api/v1/auth/me").action == "wps_auth_me"
    expected = {
        "/wps-api/v1/auth/register": "wps_auth_register",
        "/wps-api/v1/auth/login": "wps_auth_login",
        "/wps-api/v1/auth/logout": "wps_auth_logout",
        "/wps-api/v1/heartbeat": "wps_heartbeat",
        "/wps-api/v1/notifications/read": "wps_notifications_read",
        "/wps-api/v1/format/authorize": "wps_format_authorize",
        "/wps-api/v1/format/result": "wps_format_result",
    }
    assert {path: match_post_route(path).action for path in expected} == expected


def test_wps_login_uses_independent_300_per_ip_and_10_per_account_limits():
    payload = json.dumps(
        {"username": "User01", "password": "Pass01", "device": {}},
    ).encode("utf-8")

    class Handler:
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(payload)),
        }
        client_address = ("127.0.0.1", 12345)
        rfile = BytesIO(payload)

        def __init__(self):
            self.responses = []

        def _json(self, body, status):
            self.responses.append((status, body))

    calls = []

    def rate_allow(scope, key, window, limit):
        calls.append((scope, key, window, limit))
        return False, 9

    handler = Handler()
    handle_wps_action(
        handler,
        "login",
        connect_func=lambda: None,
        sql_lock=None,
        format_profile={"config_version": "test-config"},
        now_func=lambda: 1000,
        client_ip_func=lambda _headers, _address: "203.0.113.10",
        rate_allow=rate_allow,
    )

    assert calls == [
        ("wps-login-ip", "203.0.113.10", 600, 300),
        ("wps-login-name", "user01", 600, 10),
    ]
    assert handler.responses[0][0] == 429
    assert handler.responses[0][1]["error"]["code"] == "RATE_LIMITED"
