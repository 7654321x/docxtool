from __future__ import annotations

from docxtool.web.routing import (
    RouteMatch,
    match_delete_route,
    match_get_route,
    match_post_route,
    match_put_route,
)


def test_match_get_route_keeps_public_pages_and_service_endpoints() -> None:
    """GET 路由匹配应保留首页、健康检查、认证和管理页动作。"""
    assert match_get_route("/") == RouteMatch("index")
    assert match_get_route("/index.html") == RouteMatch("index")
    assert match_get_route("/admin/login") == RouteMatch("admin_login")
    assert match_get_route("/admin/session") == RouteMatch("admin_session")
    assert match_get_route("/health") == RouteMatch("health")
    assert match_get_route("/ready") == RouteMatch("ready")
    assert match_get_route("/version") == RouteMatch("version")
    assert match_get_route("/auth/me") == RouteMatch("auth_me")
    assert match_get_route("/stats") == RouteMatch("stats")
    assert match_get_route("/monitor") == RouteMatch("monitor")
    assert match_get_route("/ip") == RouteMatch("ip_detail")


def test_match_get_route_extracts_resource_ids_and_method_errors() -> None:
    """GET 路由匹配应返回资源 ID，并把管理 POST-only 路径标记为 405。"""
    assert match_get_route("/ban") == RouteMatch("method_not_allowed")
    assert match_get_route("/presets") == RouteMatch("presets_list")
    assert match_get_route("/presets/user-template") == RouteMatch("preset_detail", "user-template")
    assert match_get_route("/status/task-id") == RouteMatch("status", "task-id")
    assert match_get_route("/api/status/task-id") == RouteMatch("status", "task-id")
    assert match_get_route("/download/file-id") == RouteMatch("download", "file-id")
    assert match_get_route("/api/download/file-id") == RouteMatch("download", "file-id")
    assert match_get_route("/log/task-id") == RouteMatch("log", "task-id")
    assert match_get_route("/missing") == RouteMatch("not_found")


def test_match_post_route_keeps_mutation_actions() -> None:
    """POST 路由匹配应区分上传、认证、管理动作和 preset 变更。"""
    assert match_post_route("/upload") == RouteMatch("upload")
    assert match_post_route("/auth/register") == RouteMatch("auth_register")
    assert match_post_route("/auth/login") == RouteMatch("auth_login")
    assert match_post_route("/auth/logout") == RouteMatch("auth_logout")
    assert match_post_route("/admin/login") == RouteMatch("admin_login")
    assert match_post_route("/admin/logout") == RouteMatch("admin_logout")
    assert match_post_route("/ban") == RouteMatch("ban")
    assert match_post_route("/unban") == RouteMatch("unban")
    assert match_post_route("/limit") == RouteMatch("limit")
    assert match_post_route("/cleanup") == RouteMatch("cleanup")
    assert match_post_route("/presets") == RouteMatch("preset_create")
    assert match_post_route("/presets/user-template") == RouteMatch("preset_update", "user-template")
    assert match_post_route("/missing") == RouteMatch("not_found")


def test_match_put_and_delete_route_extract_preset_ids() -> None:
    """PUT/DELETE 路由匹配应返回上传或 preset 修改删除动作。"""
    assert match_put_route("/upload") == RouteMatch("upload")
    assert match_put_route("/presets/user-template") == RouteMatch("preset_update", "user-template")
    assert match_put_route("/missing") == RouteMatch("not_found")
    assert match_delete_route("/presets/user-template") == RouteMatch("preset_delete", "user-template")
    assert match_delete_route("/upload") == RouteMatch("not_found")
