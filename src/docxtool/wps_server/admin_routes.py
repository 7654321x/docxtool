"""HTTP handlers for the unified administrator workspace."""

from __future__ import annotations

from urllib.parse import parse_qs

from .admin import list_users, overview, set_device_status, set_user_status, user_detail


def handle_workspace(handler, parsed, *, require_admin, web_stats, web_runtime, wps_connect, wps_lock, now_func, ready_payload, csrf_input, render_page) -> None:
    if not require_admin(parsed):
        return
    web_summary = dict(web_stats())
    web_summary["queued"] = int(web_runtime().get("queued", 0))
    handler._text(
        render_page(
            web_summary=web_summary,
            wps_summary=overview(connect_func=wps_connect, sql_lock=wps_lock, now=int(now_func())),
            readiness=ready_payload(),
            csrf_input=csrf_input(handler._admin_csrf_token(parsed)),
        ),
        "text/html; charset=utf-8",
    )


def handle_users(handler, parsed, *, require_admin, wps_connect, wps_lock, now_func, csrf_input, render_page) -> None:
    if not require_admin(parsed):
        return
    query = parse_qs(parsed.query, keep_blank_values=True)
    search = query.get("q", [""])[0][:80]
    status = query.get("status", [""])[0]
    rows = list_users(connect_func=wps_connect, sql_lock=wps_lock, now=int(now_func()), query=search, status=status)
    handler._text(render_page(rows=rows, query=search, status=status, csrf_input=csrf_input(handler._admin_csrf_token(parsed))), "text/html; charset=utf-8")


def handle_user(handler, parsed, user_id: str, *, require_admin, wps_connect, wps_lock, csrf_input, render_page) -> None:
    if not require_admin(parsed):
        return
    detail = user_detail(user_id, connect_func=wps_connect, sql_lock=wps_lock)
    if not detail:
        handler.send_error(404)
        return
    handler._text(render_page(detail=detail, csrf_input=csrf_input(handler._admin_csrf_token(parsed))), "text/html; charset=utf-8")


def handle_user_status(handler, parsed, user_id: str, *, require_admin_post, request_params, wps_connect, wps_lock, now_func) -> None:
    if not require_admin_post(parsed):
        return
    status = request_params(parsed).get("status", "")
    set_user_status(user_id, status, connect_func=wps_connect, sql_lock=wps_lock, now=int(now_func()))
    handler._redirect(f"/admin/wps/users/{user_id}")


def handle_device_status(handler, parsed, device_id: str, *, require_admin_post, request_params, wps_connect, wps_lock) -> None:
    if not require_admin_post(parsed):
        return
    params = request_params(parsed)
    set_device_status(device_id, params.get("status", ""), connect_func=wps_connect, sql_lock=wps_lock)
    handler._redirect(f"/admin/wps/users/{params.get('user_id', '')}")
