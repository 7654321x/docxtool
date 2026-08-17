"""管理员监控首页和统计接口路由处理辅助。

本模块只编排 HTTP handler、管理员鉴权回调、统计查询回调和 HTML 渲染回调，不直接
访问 SQLite、不读取任务表，也不触碰 DOCX 识别、规范化或渲染链路。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def handle_stats(
    handler,
    parsed,
    *,
    require_admin: Callable[[Any], bool],
    monitor_query_from: Callable[[Any], dict[str, int]],
    get_sql_stats: Callable[[dict[str, int]], dict[str, object]],
) -> None:
    """传入 handler、URL 和查询回调，通过管理员鉴权后发送统计 JSON。"""
    if not require_admin(parsed):
        return
    handler._json(get_sql_stats(monitor_query_from(parsed)))


def handle_monitor(
    handler,
    parsed,
    *,
    require_admin: Callable[[Any], bool],
    admin_context_or_default: Callable[[], dict[str, object]],
    create_admin_session: Callable[[str, str], dict[str, str]],
    admin_cookie_header: Callable[[str], str],
    monitor_query_from: Callable[[Any], dict[str, int]],
    get_sql_stats: Callable[[dict[str, int]], dict[str, object]],
    monitor_html: Callable[[dict[str, object], str], str],
    admin_csrf_token: Callable[[Any], str],
) -> None:
    """传入 handler、URL 和监控依赖，发送监控页 HTML 或刷新 legacy 管理员会话。"""
    if not require_admin(parsed):
        return

    context = admin_context_or_default()
    if context.get("legacy_token") and not context.get("session"):
        session = create_admin_session(
            handler.headers.get("User-Agent", ""),
            handler.client_address[0] if handler.client_address else "",
        )
        handler._redirect(
            "/monitor",
            extra_headers=[("Set-Cookie", admin_cookie_header(session["session_id"]))],
        )
        return

    query = monitor_query_from(parsed)
    handler._text(monitor_html(get_sql_stats(query), admin_csrf_token(parsed)), "text/html")
