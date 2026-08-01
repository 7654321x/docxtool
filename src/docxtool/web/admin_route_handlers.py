"""Administrator monitor action handlers for the Web compatibility app."""

from __future__ import annotations

from typing import Any

from docxtool.web.admin_actions import (
    ban_reason_from_params,
    ip_from_action_params,
    upload_limit_values_from_params,
)


def handle_ip_detail(handler: Any, parsed: Any, *, is_ip, render_ip_detail_html) -> None:
    """传入 handler、已解析 URL、IP 校验和渲染回调，发送 IP 详情页或错误响应。"""
    ip = handler._query_ip(parsed)
    if not is_ip(ip):
        handler._json_error("INVALID_IP", "无效的 IP", 400)
        return
    handler._text(render_ip_detail_html(ip, handler._admin_csrf_token(parsed)), "text/html")


def handle_ban(handler: Any, parsed: Any, *, is_ip, ban_ip, logger) -> None:
    """传入 handler、已解析 URL、IP 校验和封禁回调，执行封禁并跳转监控页。"""
    params = handler._request_params(parsed)
    ip = ip_from_action_params(params)
    if not is_ip(ip):
        handler._json_error("INVALID_IP", "无效的 IP", 400)
        return
    reason = ban_reason_from_params(params)
    ban_ip(ip, reason)
    logger.warning(f"[Security] ip banned: {ip} reason={reason}")
    handler._redirect("/monitor")


def handle_unban(handler: Any, parsed: Any, *, is_ip, unban_ip, logger) -> None:
    """传入 handler、已解析 URL、IP 校验和解封回调，执行解封并跳转监控页。"""
    params = handler._request_params(parsed)
    ip = ip_from_action_params(params)
    if not is_ip(ip):
        handler._json_error("INVALID_IP", "无效的 IP", 400)
        return
    unban_ip(ip)
    logger.warning(f"[Security] ip unbanned: {ip}")
    handler._redirect("/monitor")


def handle_limit(
    handler: Any,
    parsed: Any,
    *,
    default_window_seconds: int,
    default_count: int,
    save_limit_settings,
    logger,
) -> None:
    """传入 handler、已解析 URL、默认限额和保存回调，更新上传限额并跳转监控页。"""
    params = handler._request_params(parsed)
    enabled, window_seconds, count = upload_limit_values_from_params(
        params,
        default_window_seconds=default_window_seconds,
        default_count=default_count,
    )
    save_limit_settings(enabled, window_seconds, count)
    logger.warning(
        f"[Security] upload limit settings updated: enabled={enabled} "
        f"window_seconds={max(1, window_seconds)} count={max(1, count)}"
    )
    handler._redirect("/monitor")


def handle_cleanup(handler: Any, *, logger) -> None:
    """传入 handler 和日志对象，执行永久保留策略下的兼容清理入口并跳转监控页。"""
    logger.info("[Cleaner] manual cleanup skipped: permanent file retention is enabled")
    handler._redirect("/monitor")
