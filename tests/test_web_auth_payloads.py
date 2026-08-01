from __future__ import annotations

from docxtool.web.auth_payloads import (
    auth_me_data,
    auth_me_extra_headers,
    auth_success_data,
    is_json_content_type,
    public_user_data,
)


def test_is_json_content_type_accepts_charset_suffix() -> None:
    """Content-Type 检查应接受 application/json 及其 charset 后缀。"""
    assert is_json_content_type({"Content-Type": "application/json; charset=utf-8"})
    assert not is_json_content_type({"Content-Type": "text/plain"})
    assert not is_json_content_type({})


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
