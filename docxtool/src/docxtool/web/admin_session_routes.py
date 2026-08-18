"""Administrator session route handlers for the Web compatibility app."""

from __future__ import annotations

from typing import Any


def handle_admin_session(handler: Any, *, session_from_headers, session_payload) -> None:
    """传入 handler、session 查询和响应构造回调，发送管理员会话 JSON 或未授权错误。"""
    session = session_from_headers(handler.headers, handler.headers.get("Cookie", ""))
    if not session:
        handler._json_error("UNAUTHORIZED", "需要管理员权限", 403)
        return
    handler._json(session_payload(session))


def handle_admin_login(
    handler: Any,
    *,
    admin_token: str,
    read_exact,
    parse_login_token,
    login_error,
    create_admin_session,
    admin_cookie_header,
) -> None:
    """传入 handler、密钥和 session 回调，读取表单并执行管理员登录跳转。"""
    length = int(handler.headers.get("Content-Length", 0) or 0)
    body = read_exact(handler.rfile, length) if length > 0 else b""
    token = parse_login_token(body)
    error = login_error(token, admin_token)
    if error is not None:
        handler._json_error_fields(error)
        return
    session = create_admin_session(
        handler.headers.get("User-Agent", ""),
        handler.client_address[0] if handler.client_address else "",
    )
    cookie = admin_cookie_header(session["session_id"])
    handler._redirect("/admin", extra_headers=[("Set-Cookie", cookie)])


def handle_admin_logout(
    handler: Any,
    *,
    session_from_headers,
    delete_admin_session,
    logout_cookie_header,
    cookie_name: str,
    secure: bool,
) -> None:
    """传入 handler、session 删除和 Cookie 回调，清理管理员 session 并跳转登录页。"""
    session = session_from_headers(handler.headers, handler.headers.get("Cookie", ""))
    if session:
        delete_admin_session(session.get("session_id", ""))
    cookie = logout_cookie_header(cookie_name, secure=secure)
    handler._redirect("/admin/login", extra_headers=[("Set-Cookie", cookie)])
