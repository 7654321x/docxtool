from __future__ import annotations

from docxtool.web.admin_access import (
    admin_context_or_default,
    admin_post_csrf_allowed,
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
