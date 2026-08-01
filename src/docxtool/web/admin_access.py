"""Pure helpers for administrator request access checks."""

from __future__ import annotations

import hmac
from typing import Mapping

from docxtool.web.request_utils import csrf_header_value


def admin_context_or_default(context: Mapping[str, object] | None = None) -> dict:
    """传入可能为空的管理员上下文，返回带默认字段的上下文字典。"""
    if not context:
        return {"authorized": False, "session": {}, "legacy_token": False}
    return {
        "authorized": bool(context.get("authorized")),
        "session": dict(context.get("session") or {}),
        "legacy_token": bool(context.get("legacy_token")),
    }


def csrf_token_from_admin_context(context: Mapping[str, object] | None = None) -> str:
    """传入管理员上下文，返回可用于页面表单的 CSRF token 或空字符串。"""
    normalized = admin_context_or_default(context)
    session = normalized.get("session") or {}
    token = str(session.get("csrf_token") or "").strip()
    if token:
        return token
    if normalized.get("legacy_token"):
        return ""
    return ""


def admin_session_payload(session: Mapping[str, object]) -> dict:
    """传入管理员 session 映射，返回 /admin/session 兼容 JSON 响应体。"""
    return {
        "ok": True,
        "csrf_token": session.get("csrf_token", ""),
        "expires_at": session.get("expires_at", 0),
    }


def admin_logout_cookie_header(cookie_name: str, *, secure: bool = False) -> str:
    """传入管理员 Cookie 名和 secure 开关，返回清除登录 Cookie 的 Set-Cookie 值。"""
    cookie = f"{cookie_name}=; HttpOnly; Path=/; SameSite=Strict; Max-Age=0"
    if secure:
        cookie += "; Secure"
    return cookie


def admin_login_token_valid(submitted_token: str, expected_token: str) -> bool:
    """传入用户提交密钥和期望密钥，返回是否通过恒定时间比较。"""
    return hmac.compare_digest(str(submitted_token or ""), str(expected_token or ""))


def admin_login_error(submitted_token: str, expected_token: str) -> tuple[str, str, int] | None:
    """传入提交密钥和期望密钥，返回管理员登录错误字段或 None。"""
    if not submitted_token:
        return "INVALID_LOGIN", "请输入管理员密钥", 400
    if not admin_login_token_valid(submitted_token, expected_token):
        return "INVALID_LOGIN", "管理员密钥错误", 403
    return None


def admin_unauthorized_error() -> tuple[str, str, int]:
    """无需传入数据，返回管理员未授权的稳定错误字段。"""
    return "UNAUTHORIZED", "需要管理员权限", 403


def admin_csrf_invalid_error() -> tuple[str, str, int]:
    """无需传入数据，返回管理员 POST CSRF 校验失败的稳定错误字段。"""
    return "CSRF_INVALID", "CSRF 校验失败", 403


def admin_post_csrf_allowed(
    context: Mapping[str, object] | None,
    params: Mapping[str, object] | None,
    headers,
    *,
    csrf_header_name: str,
) -> bool:
    """传入管理员上下文、请求参数和请求头，返回 POST CSRF 校验是否通过。"""
    normalized = admin_context_or_default(context)
    session = normalized.get("session") or {}
    expected = str(session.get("csrf_token") or "")
    submitted = str((params or {}).get("csrf_token") or csrf_header_value(headers, csrf_header_name) or "").strip()
    return bool(expected and submitted and hmac.compare_digest(submitted, expected))
