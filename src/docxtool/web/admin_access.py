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
