from __future__ import annotations

from docxtool.web.admin_access import (
    admin_csrf_invalid_error,
    admin_context_or_default,
    admin_login_error,
    admin_login_token_valid,
    admin_logout_cookie_header,
    admin_post_csrf_allowed,
    admin_session_payload,
    admin_unauthorized_error,
    csrf_token_from_admin_context,
)


def test_admin_context_or_default_fills_stable_fields() -> None:
    """空管理员上下文应补齐授权、session 和 legacy token 三个稳定字段。"""
    assert admin_context_or_default(None) == {"authorized": False, "session": {}, "legacy_token": False}
    assert admin_context_or_default({"authorized": True, "legacy_token": True}) == {
        "authorized": True,
        "session": {},
        "legacy_token": True,
    }


def test_csrf_token_from_admin_context_uses_session_only() -> None:
    """页面 CSRF token 只来自管理员 session；legacy token 模式返回空字符串。"""
    assert csrf_token_from_admin_context({"session": {"csrf_token": " csrf "}}) == "csrf"
    assert csrf_token_from_admin_context({"legacy_token": True}) == ""
    assert csrf_token_from_admin_context({}) == ""


def test_admin_session_payload_uses_public_session_fields() -> None:
    """管理员会话响应只返回前端需要的授权状态、CSRF token 和过期时间。"""
    assert admin_session_payload({"csrf_token": "csrf", "expires_at": 123, "session_id": "secret"}) == {
        "ok": True,
        "csrf_token": "csrf",
        "expires_at": 123,
    }


def test_admin_logout_cookie_header_clears_session_cookie() -> None:
    """管理员退出 Cookie 应清空会话并按 secure 开关追加 Secure 属性。"""
    assert admin_logout_cookie_header("admin_session") == (
        "admin_session=; HttpOnly; Path=/; SameSite=Strict; Max-Age=0"
    )
    assert admin_logout_cookie_header("admin_session", secure=True).endswith("; Secure")


def test_admin_login_token_valid_compares_expected_secret() -> None:
    """管理员登录密钥比较应只在提交值与期望值完全一致时通过。"""
    assert admin_login_token_valid("secret", "secret")
    assert not admin_login_token_valid("secret", "other")
    assert not admin_login_token_valid("", "secret")


def test_admin_login_error_returns_stable_error_or_none() -> None:
    """管理员登录错误 helper 应区分空密钥、错误密钥和正确密钥。"""
    assert admin_login_error("", "secret") == ("INVALID_LOGIN", "请输入管理员密钥", 400)
    assert admin_login_error("bad", "secret") == ("INVALID_LOGIN", "管理员密钥错误", 403)
    assert admin_login_error("secret", "secret") is None


def test_admin_access_errors_are_stable() -> None:
    """管理员授权和 CSRF 错误 helper 应返回稳定错误字段。"""
    assert admin_unauthorized_error() == ("UNAUTHORIZED", "需要管理员权限", 403)
    assert admin_csrf_invalid_error() == ("CSRF_INVALID", "CSRF 校验失败", 403)


def test_admin_post_csrf_allowed_accepts_form_or_header_token() -> None:
    """管理员 POST 校验应接受表单字段或配置的 CSRF 请求头。"""
    context = {"authorized": True, "session": {"csrf_token": "csrf-token"}, "legacy_token": False}

    assert admin_post_csrf_allowed(context, {"csrf_token": "csrf-token"}, {}, csrf_header_name="X-CSRF-Token")
    assert admin_post_csrf_allowed(
        context,
        {},
        {"X-CSRF-Token": "csrf-token"},
        csrf_header_name="X-CSRF-Token",
    )


def test_admin_post_csrf_allowed_rejects_missing_or_legacy_context() -> None:
    """缺少 session、缺少 token 或 token 不一致时，管理员 POST CSRF 校验应失败。"""
    context = {"authorized": True, "session": {"csrf_token": "csrf-token"}, "legacy_token": False}

    assert not admin_post_csrf_allowed(context, {}, {}, csrf_header_name="X-CSRF-Token")
    assert not admin_post_csrf_allowed(context, {"csrf_token": "bad"}, {}, csrf_header_name="X-CSRF-Token")
    assert not admin_post_csrf_allowed(
        {"authorized": True, "session": {}, "legacy_token": True},
        {"csrf_token": "csrf-token"},
        {},
        csrf_header_name="X-CSRF-Token",
    )
