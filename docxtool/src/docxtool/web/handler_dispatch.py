"""Route dispatch helpers for the Web compatibility handler."""

from __future__ import annotations

from typing import Any

from docxtool.web.routing import (
    match_delete_route,
    match_get_route,
    match_post_route,
    match_put_route,
)


def dispatch_get(handler: Any, parsed: Any, path: str) -> None:
    """传入 handler、已解析 URL 和路径，执行 GET 路由对应处理并返回 None。"""
    route = match_get_route(path)
    if route.action == "index":
        handler._serve_html()
    elif route.action == "admin_login":
        handler._serve_admin_login()
    elif route.action == "admin_session":
        handler._handle_admin_session()
    elif route.action == "health":
        handler._handle_health()
    elif route.action == "ready":
        handler._handle_ready()
    elif route.action == "version":
        handler._handle_version()
    elif route.action == "auth_me":
        handler._handle_auth_me()
    elif route.action == "wps_auth_me":
        handler._handle_wps_api("me")
    elif route.action == "admin_workspace":
        handler._handle_admin_workspace(parsed)
    elif route.action == "admin_web":
        handler._handle_admin_web(parsed, route.value)
    elif route.action == "admin_wps_overview":
        handler._handle_admin_wps_overview(parsed)
    elif route.action == "admin_wps_users":
        handler._handle_admin_wps_users(parsed)
    elif route.action == "admin_wps_devices":
        handler._handle_admin_wps_devices(parsed)
    elif route.action == "admin_wps_tasks":
        handler._handle_admin_wps_tasks(parsed)
    elif route.action == "admin_wps_user":
        handler._handle_admin_wps_user(parsed, route.value)
    elif route.action == "stats":
        handler._handle_stats(parsed)
    elif route.action == "monitor":
        handler._handle_monitor(parsed)
    elif route.action == "ip_detail":
        handler._handle_ip_detail_route(parsed)
    elif route.action == "method_not_allowed":
        handler.send_error(405)
    elif route.action == "presets_list":
        handler._handle_presets_list()
    elif route.action == "preset_detail":
        handler._handle_preset_detail(route.value)
    elif route.action == "status":
        handler._handle_status_route(route.value)
    elif route.action == "download":
        handler._handle_download_route(route.value)
    elif route.action == "log":
        handler._handle_log_route(parsed, route.value)
    else:
        handler.send_error(404)


def dispatch_post(handler: Any, parsed: Any, path: str) -> None:
    """传入 handler、已解析 URL 和路径，执行 POST 路由对应处理并返回 None。"""
    route = match_post_route(path)
    if route.action == "upload":
        handler._handle_upload_route()
    elif route.action == "auth_register":
        handler._handle_auth_register()
    elif route.action == "auth_login":
        handler._handle_auth_login()
    elif route.action == "auth_logout":
        handler._handle_auth_logout()
    elif route.action == "wps_auth_register":
        handler._handle_wps_api("register")
    elif route.action == "wps_auth_login":
        handler._handle_wps_api("login")
    elif route.action == "wps_auth_logout":
        handler._handle_wps_api("logout")
    elif route.action == "wps_heartbeat":
        handler._handle_wps_api("heartbeat")
    elif route.action == "wps_notifications_read":
        handler._handle_wps_api("notifications_read")
    elif route.action == "wps_format_authorize":
        handler._handle_wps_api("format_authorize")
    elif route.action == "wps_format_result":
        handler._handle_wps_api("format_result")
    elif route.action == "admin_wps_user_status":
        handler._handle_admin_wps_user_status(parsed, route.value)
    elif route.action == "admin_wps_user_password_reset":
        handler._handle_admin_wps_user_password_reset(parsed, route.value)
    elif route.action == "admin_wps_user_notification":
        handler._handle_admin_wps_user_notification(parsed, route.value)
    elif route.action == "admin_wps_user_delete":
        handler._handle_admin_wps_user_delete(parsed, route.value)
    elif route.action == "admin_wps_device_status":
        handler._handle_admin_wps_device_status(parsed, route.value)
    elif route.action == "admin_login":
        handler._handle_admin_login()
    elif route.action == "admin_logout":
        handler._handle_admin_logout()
    elif route.action == "ban":
        handler._handle_ban_route(parsed)
    elif route.action == "unban":
        handler._handle_unban_route(parsed)
    elif route.action == "limit":
        handler._handle_limit_route(parsed)
    elif route.action == "cleanup":
        handler._handle_cleanup_route(parsed)
    elif route.action == "preset_create":
        handler._handle_preset_create_route(parsed)
    elif route.action == "preset_update":
        handler._handle_preset_update_route(parsed, route.value)
    else:
        handler.send_error(404)


def dispatch_put(handler: Any, parsed: Any, path: str) -> None:
    """传入 handler、已解析 URL 和路径，执行 PUT 路由对应处理并返回 None。"""
    route = match_put_route(path)
    if route.action == "upload":
        handler._handle_upload_route()
    elif route.action == "preset_update":
        handler._handle_preset_update_route(parsed, route.value)
    else:
        handler.send_error(404)


def dispatch_delete(handler: Any, parsed: Any, path: str) -> None:
    """传入 handler、已解析 URL 和路径，执行 DELETE 路由对应处理并返回 None。"""
    route = match_delete_route(path)
    if route.action == "preset_delete":
        handler._handle_preset_delete_route(parsed, route.value)
    else:
        handler.send_error(404)
