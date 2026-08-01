from __future__ import annotations

from docxtool.web.auth_payloads import (
    auth_account_disabled_error,
    auth_invalid_credentials_error,
    auth_json_request_error,
    auth_login_rate_limit_error,
    auth_logout_extra_headers,
    auth_logout_request_error,
    auth_logout_response,
    auth_me_data,
    auth_me_extra_headers,
    auth_register_error_from_exception,
    auth_register_rate_limit_error,
    auth_session_extra_headers,
    auth_success_data,
    auth_success_response,
    auth_validation_error_from_exception,
    is_json_content_type,
    ok_data_response,
    public_user_data,
)


def test_is_json_content_type_accepts_charset_suffix() -> None:
    """Content-Type 检查应接受 application/json 及其 charset 后缀。"""
    assert is_json_content_type({"Content-Type": "application/json; charset=utf-8"})
    assert not is_json_content_type({"Content-Type": "text/plain"})
    assert not is_json_content_type({})


def test_auth_json_request_error_reports_origin_or_content_type() -> None:
    """认证 JSON 请求校验应返回稳定错误三元组或 None。"""
    assert auth_json_request_error(False, {"Content-Type": "application/json"}) == (
        "ORIGIN_INVALID",
        "请求来源不被允许",
        403,
    )
    assert auth_json_request_error(True, {"Content-Type": "text/plain"}) == (
        "CONTENT_TYPE_INVALID",
        "请求必须使用 application/json",
        415,
    )
    assert auth_json_request_error(True, {"Content-Type": "application/json"}) is None


def test_auth_validation_error_from_exception_returns_stable_tuple() -> None:
    """认证字段校验异常应解析为错误码、提示文本和 HTTP 状态码。"""
    assert auth_validation_error_from_exception(ValueError("USERNAME_REQUIRED: 用户名不能为空")) == (
        "USERNAME_REQUIRED",
        "用户名不能为空",
        400,
    )
    assert auth_validation_error_from_exception(ValueError("plain")) == ("VALIDATION_ERROR", "plain", 400)


def test_auth_register_error_from_exception_hides_database_details() -> None:
    """注册持久化异常应转为脱敏的稳定错误码和提示。"""
    assert auth_register_error_from_exception(RuntimeError("UNIQUE constraint failed: users.username_norm")) == (
        "USERNAME_TAKEN",
        "用户名已存在",
        409,
    )
    assert auth_register_error_from_exception(RuntimeError("database disk image is malformed")) == (
        "REGISTER_FAILED",
        "注册失败",
        500,
    )


def test_auth_register_rate_limit_error_returns_retry_after() -> None:
    """注册限流错误应在被限流时返回稳定错误和 retry-after。"""
    assert auth_register_rate_limit_error(True, 0) is None
    assert auth_register_rate_limit_error(False, 7) == (
        "RATE_LIMITED",
        "注册请求过于频繁，请稍后再试",
        429,
        7,
    )


def test_auth_login_rate_limit_error_merges_ip_and_name_limits() -> None:
    """登录限流错误应在 IP 或用户名被限流时返回最大 retry-after。"""
    assert auth_login_rate_limit_error(True, 1, True, 2) is None
    assert auth_login_rate_limit_error(False, 3, True, 2) == (
        "RATE_LIMITED",
        "登录请求过于频繁，请稍后再试",
        429,
        3,
    )
    assert auth_login_rate_limit_error(True, 3, False, 5) == (
        "RATE_LIMITED",
        "登录请求过于频繁，请稍后再试",
        429,
        5,
    )


def test_auth_login_fixed_errors_are_stable() -> None:
    """登录凭据错误和账号停用错误应返回稳定错误字段。"""
    assert auth_invalid_credentials_error() == ("INVALID_CREDENTIALS", "用户名或密码错误", 401)
    assert auth_account_disabled_error() == ("ACCOUNT_DISABLED", "账号已停用", 403)


def test_public_user_and_auth_success_data_are_stable() -> None:
    """用户响应辅助应返回稳定 user 字段和 CSRF token。"""
    assert public_user_data("usr_1", "Alice", "Alice A") == {
        "id": "usr_1",
        "username": "Alice",
        "display_name": "Alice A",
    }
    assert auth_success_data("usr_1", "Alice", "Alice A", "csrf") == {
        "user": {"id": "usr_1", "username": "Alice", "display_name": "Alice A"},
        "csrf_token": "csrf",
    }
    assert auth_success_response("usr_1", "Alice", "Alice A", "csrf") == {
        "ok": True,
        "data": {
            "user": {"id": "usr_1", "username": "Alice", "display_name": "Alice A"},
            "csrf_token": "csrf",
        },
    }


def test_ok_and_logout_responses_use_stable_envelope() -> None:
    """认证接口成功响应应统一使用 ok=true 和 data 包装。"""
    assert ok_data_response({"value": 1}) == {"ok": True, "data": {"value": 1}}
    assert auth_logout_response() == {"ok": True, "data": {"logged_out": True}}


def test_auth_logout_request_error_checks_origin_and_csrf() -> None:
    """退出登录前置校验应返回来源或 CSRF 错误，匿名退出可直接通过。"""
    assert auth_logout_request_error(False, False, False) == ("ORIGIN_INVALID", "请求来源不被允许", 403)
    assert auth_logout_request_error(True, True, False) == ("CSRF_INVALID", "CSRF 校验失败", 403)
    assert auth_logout_request_error(True, False, False) is None
    assert auth_logout_request_error(True, True, True) is None


def test_auth_session_and_logout_extra_headers_are_ordered() -> None:
    """登录、注册和退出的 Set-Cookie 响应头应保持旧顺序。"""
    assert auth_session_extra_headers("user=cookie", "anon=clear") == [
        ("Set-Cookie", "user=cookie"),
        ("Set-Cookie", "anon=clear"),
    ]
    assert auth_logout_extra_headers("user=clear") == [("Set-Cookie", "user=clear")]


def test_auth_me_data_handles_anonymous_and_authenticated_principal() -> None:
    """传入 principal 后，/auth/me data 应区分匿名和已登录用户。"""
    assert auth_me_data({}) == {"authenticated": False, "user": None, "csrf_token": None}
    assert auth_me_data(
        {
            "authenticated": True,
            "user_id": "usr_1",
            "username": "Alice",
            "display_name": "Alice A",
            "csrf_token": "csrf",
        }
    ) == {
        "authenticated": True,
        "user": {"id": "usr_1", "username": "Alice", "display_name": "Alice A"},
        "csrf_token": "csrf",
    }


def test_auth_me_extra_headers_preserves_owner_and_invalid_session_cookies() -> None:
    """传入 principal 后，/auth/me 附加头应保留匿名 cookie 并清理无效用户 cookie。"""
    assert auth_me_extra_headers({"cookie": "owner=abc"}, clear_user_cookie_header="clear=user") == [
        ("Set-Cookie", "owner=abc")
    ]
    assert auth_me_extra_headers({"invalid_user_session": True}, clear_user_cookie_header="clear=user") == [
        ("Set-Cookie", "clear=user")
    ]
