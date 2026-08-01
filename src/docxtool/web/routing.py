"""Pure route matching helpers for the Web compatibility handler."""

from __future__ import annotations

from dataclasses import dataclass

from docxtool.web.admin_actions import is_post_only_action_path
from docxtool.web.request_utils import prefixed_route_last_segment, prefixed_route_tail


@dataclass(frozen=True)
class RouteMatch:
    """传入 HTTP 方法和路径匹配后生成，返回动作名称和可选资源 ID。"""

    action: str
    value: str = ""


def match_get_route(path: str) -> RouteMatch:
    """传入已归一化 GET 路径，返回兼容处理器应执行的路由动作。"""
    if path == "/" or path == "/index.html":
        return RouteMatch("index")
    if path == "/admin/login":
        return RouteMatch("admin_login")
    if path == "/admin/session":
        return RouteMatch("admin_session")
    if path == "/health":
        return RouteMatch("health")
    if path == "/ready":
        return RouteMatch("ready")
    if path == "/version":
        return RouteMatch("version")
    if path == "/auth/me":
        return RouteMatch("auth_me")
    if path == "/stats":
        return RouteMatch("stats")
    if path == "/monitor":
        return RouteMatch("monitor")
    if path == "/ip":
        return RouteMatch("ip_detail")
    if is_post_only_action_path(path):
        return RouteMatch("method_not_allowed")
    if path == "/presets":
        return RouteMatch("presets_list")
    if (preset_id := prefixed_route_tail(path, "/presets/")) is not None:
        return RouteMatch("preset_detail", preset_id)
    if (task_id := prefixed_route_last_segment(path, "/status/", "/api/status/")) is not None:
        return RouteMatch("status", task_id)
    if (file_id := prefixed_route_last_segment(path, "/download/", "/api/download/")) is not None:
        return RouteMatch("download", file_id)
    if (task_id := prefixed_route_last_segment(path, "/log/")) is not None:
        return RouteMatch("log", task_id)
    return RouteMatch("not_found")


def match_post_route(path: str) -> RouteMatch:
    """传入已归一化 POST 路径，返回兼容处理器应执行的路由动作。"""
    if path == "/upload":
        return RouteMatch("upload")
    if path == "/auth/register":
        return RouteMatch("auth_register")
    if path == "/auth/login":
        return RouteMatch("auth_login")
    if path == "/auth/logout":
        return RouteMatch("auth_logout")
    if path == "/admin/login":
        return RouteMatch("admin_login")
    if path == "/admin/logout":
        return RouteMatch("admin_logout")
    if path == "/ban":
        return RouteMatch("ban")
    if path == "/unban":
        return RouteMatch("unban")
    if path == "/limit":
        return RouteMatch("limit")
    if path == "/cleanup":
        return RouteMatch("cleanup")
    if path == "/presets":
        return RouteMatch("preset_create")
    if (preset_id := prefixed_route_tail(path, "/presets/")) is not None:
        return RouteMatch("preset_update", preset_id)
    return RouteMatch("not_found")


def match_put_route(path: str) -> RouteMatch:
    """传入已归一化 PUT 路径，返回兼容处理器应执行的路由动作。"""
    if path == "/upload":
        return RouteMatch("upload")
    if (preset_id := prefixed_route_tail(path, "/presets/")) is not None:
        return RouteMatch("preset_update", preset_id)
    return RouteMatch("not_found")


def match_delete_route(path: str) -> RouteMatch:
    """传入已归一化 DELETE 路径，返回兼容处理器应执行的路由动作。"""
    if (preset_id := prefixed_route_tail(path, "/presets/")) is not None:
        return RouteMatch("preset_delete", preset_id)
    return RouteMatch("not_found")
