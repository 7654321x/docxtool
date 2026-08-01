import pytest

from docxtool.web import app as server
from docxtool.web.request_utils import (
    admin_session_cookie_settings,
    cookie_value,
    csrf_header_value,
    error_payload,
    hidden_input,
    html_escape,
    json_dumps,
    parse_json_body,
    prefixed_route_last_segment,
    prefixed_route_tail,
    route_path,
)


def test_request_utils_match_legacy_route_and_json_helpers():
    assert route_path("/api/auth/me") == "/auth/me"
    assert server._route_path("/api/auth/me") == route_path("/api/auth/me")
    assert prefixed_route_tail("/presets/a/b", "/presets/") == "a/b"
    assert server._prefixed_route_tail("/presets/a/b", "/presets/") == "a/b"
    assert prefixed_route_last_segment("/status/a/b", "/status/") == "b"
    assert server._prefixed_route_last_segment("/status/a/b", "/status/") == "b"
    assert json_dumps({"消息": "成功", "n": 1}) == '{"消息":"成功","n":1}'
    assert server._json_dumps({"消息": "成功", "n": 1}) == json_dumps({"消息": "成功", "n": 1})
    assert parse_json_body("{}".encode("utf-8")) == {}
    with pytest.raises(ValueError, match="JSON_INVALID"):
        parse_json_body("[]".encode("utf-8"))


def test_request_utils_cookie_and_csrf_helpers_are_config_driven():
    assert cookie_value("a=1; session=abc; b=2", "session") == "abc"
    assert cookie_value("a=1; b=2", "missing") == ""
    assert csrf_header_value({"X-CSRF-Token": "csrf"}, "X-CSRF-Token") == "csrf"

    cookie = admin_session_cookie_settings("admin_session", 60, secure=True)

    assert "admin_session={session_id}" in cookie
    assert "Max-Age=60" in cookie
    assert "Secure" in cookie


def test_request_utils_html_and_error_payload_are_safely_encoded():
    assert html_escape("<b>密钥</b>") == "&lt;b&gt;密钥&lt;/b&gt;"
    assert hidden_input("csrf_token", "<token>") == (
        '<input type="hidden" name="csrf_token" value="&lt;token&gt;">'
    )
    assert hidden_input("csrf_token", "") == ""
    assert error_payload("BAD", "失败", field="name") == {
        "error": "失败",
        "code": "BAD",
        "field": "name",
    }
