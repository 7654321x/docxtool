"""HTTP handlers for the unified administrator workspace."""

from __future__ import annotations

import hashlib
from urllib.parse import parse_qs
import uuid

from .admin import (
    WpsAdminError,
    delete_user,
    list_admin_audit_logs,
    list_devices,
    list_format_requests,
    list_users,
    overview,
    overview_trend,
    reset_user_password,
    send_notification,
    set_device_status,
    set_user_status,
    user_detail,
)
from .validation import WpsValidationError


def _filters(parsed) -> dict[str, str]:
    """Extract bounded page filters; the query layer remains the canonical validator."""
    values = parse_qs(parsed.query, keep_blank_values=True)
    return {
        "q": values.get("q", [""])[0][:80],
        "status": values.get("status", [""])[0][:20],
        "online": values.get("online", [""])[0][:20],
        "version": values.get("version", [""])[0][:40],
        "page": values.get("page", ["1"])[0],
        "page_size": values.get("page_size", ["20"])[0],
    }


def _result_filters(filters: dict[str, str], result: dict) -> dict[str, object]:
    """Reflect canonical server pagination values back into page links and forms."""
    return {
        **filters,
        "page": result["page"],
        "page_size": result["page_size"],
    }


def _audit_actor(handler) -> dict[str, str]:
    """Build a non-reusable audit actor from the already-validated admin context."""
    context = dict(getattr(handler, "_admin_context", {}) or {})
    session = dict(context.get("session") or {})
    session_id = str(session.get("session_id") or "")
    if session_id:
        return {
            "actor_type": "session",
            "actor_session_id_short": hashlib.sha256(
                session_id.encode("utf-8")
            ).hexdigest()[:16],
        }
    if context.get("legacy_token"):
        return {"actor_type": "legacy_token", "actor_session_id_short": ""}
    raise WpsAdminError("WPS_ADMIN_AUDIT_ACTOR_INVALID", "管理员审计上下文无效", 403)


def _correlation_id() -> str:
    """Return a server-created correlation ID instead of persisting caller input."""
    return f"adm_{uuid.uuid4().hex}"


def _mutation_disabled(handler) -> None:
    """Return the stable fail-closed response before any WPS business write."""
    handler._json_error("WPS_ADMIN_MUTATIONS_DISABLED", "WPS 管理写操作尚未启用", 403)


def _mutation_error(handler, exc: WpsAdminError | WpsValidationError) -> None:
    """Return a typed administrator mutation error without losing its stable code."""
    handler._json_error(exc.code, exc.message, getattr(exc, "status", 400))


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


def handle_overview(handler, parsed, *, require_admin, wps_connect, wps_lock, now_func, csrf_input, render_page) -> None:
    """Render the Phase A read-only WPS operation overview."""
    if not require_admin(parsed):
        return
    now = int(now_func())
    handler._text(
        render_page(
            summary=overview(connect_func=wps_connect, sql_lock=wps_lock, now=now),
            trend=overview_trend(connect_func=wps_connect, sql_lock=wps_lock, now=now),
            recent=list_format_requests(
                connect_func=wps_connect,
                sql_lock=wps_lock,
                page_size=8,
            )["rows"],
            csrf_input=csrf_input(handler._admin_csrf_token(parsed)),
        ),
        "text/html; charset=utf-8",
    )


def handle_users(handler, parsed, *, require_admin, wps_connect, wps_lock, now_func, csrf_input, render_page, mutations_enabled: bool = False) -> None:
    if not require_admin(parsed):
        return
    filters = _filters(parsed)
    result = list_users(
        connect_func=wps_connect,
        sql_lock=wps_lock,
        now=int(now_func()),
        query=filters["q"],
        status=filters["status"],
        online=filters["online"],
        version=filters["version"],
        page=filters["page"],
        page_size=filters["page_size"],
    )
    handler._text(
        render_page(
            result=result,
            filters=_result_filters(filters, result),
            csrf_input=csrf_input(handler._admin_csrf_token(parsed)),
            mutations_enabled=mutations_enabled,
        ),
        "text/html; charset=utf-8",
    )


def handle_devices(handler, parsed, *, require_admin, wps_connect, wps_lock, now_func, csrf_input, render_page, mutations_enabled: bool = False) -> None:
    """Render the server-paged read-only device page."""
    if not require_admin(parsed):
        return
    filters = _filters(parsed)
    result = list_devices(
        connect_func=wps_connect,
        sql_lock=wps_lock,
        now=int(now_func()),
        query=filters["q"],
        status=filters["status"],
        online=filters["online"],
        version=filters["version"],
        page=filters["page"],
        page_size=filters["page_size"],
    )
    handler._text(
        render_page(
            result=result,
            filters=_result_filters(filters, result),
            csrf_input=csrf_input(handler._admin_csrf_token(parsed)),
            mutations_enabled=mutations_enabled,
        ),
        "text/html; charset=utf-8",
    )


def handle_tasks(handler, parsed, *, require_admin, wps_connect, wps_lock, csrf_input, render_page) -> None:
    """Render the server-paged read-only WPS formatting task page."""
    if not require_admin(parsed):
        return
    filters = _filters(parsed)
    result = list_format_requests(
        connect_func=wps_connect,
        sql_lock=wps_lock,
        query=filters["q"],
        status=filters["status"],
        version=filters["version"],
        page=filters["page"],
        page_size=filters["page_size"],
    )
    handler._text(
        render_page(
            result=result,
            filters=_result_filters(filters, result),
            csrf_input=csrf_input(handler._admin_csrf_token(parsed)),
        ),
        "text/html; charset=utf-8",
    )


def handle_user(handler, parsed, user_id: str, *, require_admin, wps_connect, wps_lock, now_func, csrf_input, render_page, mutations_enabled: bool = False) -> None:
    if not require_admin(parsed):
        return
    detail = user_detail(user_id, connect_func=wps_connect, sql_lock=wps_lock, now=int(now_func()))
    if not detail:
        handler.send_error(404)
        return
    values = parse_qs(parsed.query, keep_blank_values=True)
    tab = values.get("tab", ["overview"])[0]
    if tab not in {"overview", "devices", "tasks", "logs", "security"}:
        tab = "overview"
    drawer = values.get("drawer", [""])[0] == "1"
    filters = _filters(parsed)
    result = None
    audit_result = None
    if tab == "devices":
        result = list_devices(
            connect_func=wps_connect,
            sql_lock=wps_lock,
            now=int(now_func()),
            user_id=user_id,
            page=filters["page"],
            page_size=filters["page_size"],
        )
    elif tab == "tasks":
        result = list_format_requests(
            connect_func=wps_connect,
            sql_lock=wps_lock,
            user_id=user_id,
            page=filters["page"],
            page_size=filters["page_size"],
        )
    elif tab == "logs":
        audit_result = list_admin_audit_logs(
            user_id,
            connect_func=wps_connect,
            sql_lock=wps_lock,
            page=filters["page"],
            page_size=filters["page_size"],
        )
        filters = _result_filters(filters, audit_result)
    if result is not None:
        filters = _result_filters(filters, result)
    handler._text(
        render_page(
            detail=detail,
            tab=tab,
            result=result,
            audit_result=audit_result,
            filters=filters,
            csrf_input=csrf_input(handler._admin_csrf_token(parsed)),
            mutations_enabled=mutations_enabled,
            drawer=drawer,
        ),
        "text/html; charset=utf-8",
    )


def handle_user_status(
    handler,
    parsed,
    user_id: str,
    *,
    require_admin_post,
    request_params,
    wps_connect,
    wps_lock,
    now_func,
    mutations_enabled: bool,
) -> None:
    """Apply one gated user-state change and preserve its same-transaction audit fact."""
    if not require_admin_post(parsed):
        return
    if not mutations_enabled:
        _mutation_disabled(handler)
        return
    status = request_params(parsed).get("status", "")
    try:
        set_user_status(
            user_id,
            status,
            connect_func=wps_connect,
            sql_lock=wps_lock,
            now=int(now_func()),
            actor=_audit_actor(handler),
            correlation_id=_correlation_id(),
        )
    except (WpsAdminError, WpsValidationError) as exc:
        _mutation_error(handler, exc)
        return
    handler._redirect(f"/admin/wps/users/{user_id}?tab=security")


def handle_device_status(
    handler,
    parsed,
    device_id: str,
    *,
    require_admin_post,
    request_params,
    wps_connect,
    wps_lock,
    now_func,
    mutations_enabled: bool,
) -> None:
    """Apply one gated device-state change and preserve its same-transaction audit fact."""
    if not require_admin_post(parsed):
        return
    if not mutations_enabled:
        _mutation_disabled(handler)
        return
    params = request_params(parsed)
    try:
        target_user_id = set_device_status(
            device_id,
            params.get("status", ""),
            connect_func=wps_connect,
            sql_lock=wps_lock,
            now=int(now_func()),
            actor=_audit_actor(handler),
            correlation_id=_correlation_id(),
        )
    except (WpsAdminError, WpsValidationError) as exc:
        _mutation_error(handler, exc)
        return
    handler._redirect(f"/admin/wps/users/{target_user_id}?tab=devices")


def handle_user_password_reset(
    handler,
    parsed,
    user_id: str,
    *,
    require_admin_post,
    request_params,
    wps_connect,
    wps_lock,
    now_func,
    mutations_enabled: bool,
) -> None:
    """Reset one WPS password only after the server-side mutation gate permits it."""
    if not require_admin_post(parsed):
        return
    if not mutations_enabled:
        _mutation_disabled(handler)
        return
    params = request_params(parsed)
    password = params.get("password", "")
    if password != params.get("password_confirmation", ""):
        handler._json_error(
            "WPS_ADMIN_PASSWORD_CONFIRMATION_INVALID",
            "两次输入的密码不一致",
            400,
        )
        return
    try:
        target_user_id = reset_user_password(
            user_id,
            password,
            connect_func=wps_connect,
            sql_lock=wps_lock,
            now=int(now_func()),
            actor=_audit_actor(handler),
            correlation_id=_correlation_id(),
        )
    except (WpsAdminError, WpsValidationError) as exc:
        _mutation_error(handler, exc)
        return
    handler._redirect(f"/admin/wps/users/{target_user_id}?tab=security")


def handle_user_notification(
    handler,
    parsed,
    user_id: str,
    *,
    require_admin_post,
    request_params,
    wps_connect,
    wps_lock,
    now_func,
    mutations_enabled: bool,
) -> None:
    """Send one gated, plain-text WPS account notification and return to security."""
    if not require_admin_post(parsed):
        return
    if not mutations_enabled:
        _mutation_disabled(handler)
        return
    params = request_params(parsed)
    try:
        target_user_id = user_id
        send_notification(
            target_user_id,
            params.get("title", ""),
            params.get("body", ""),
            params.get("level", "info"),
            connect_func=wps_connect,
            sql_lock=wps_lock,
            now=int(now_func()),
            actor=_audit_actor(handler),
            correlation_id=_correlation_id(),
        )
    except (WpsAdminError, WpsValidationError) as exc:
        _mutation_error(handler, exc)
        return
    handler._redirect(f"/admin/wps/users/{target_user_id}?tab=security")


def handle_user_delete(
    handler,
    parsed,
    user_id: str,
    *,
    require_admin_post,
    request_params,
    wps_connect,
    wps_lock,
    now_func,
    mutations_enabled: bool,
) -> None:
    """Hard-delete one confirmed WPS account through the canonical gate and audit path."""
    if not require_admin_post(parsed):
        return
    if not mutations_enabled:
        _mutation_disabled(handler)
        return
    params = request_params(parsed)
    try:
        delete_user(
            user_id,
            params.get("confirmation_username", ""),
            connect_func=wps_connect,
            sql_lock=wps_lock,
            now=int(now_func()),
            actor=_audit_actor(handler),
            correlation_id=_correlation_id(),
        )
    except (WpsAdminError, WpsValidationError) as exc:
        _mutation_error(handler, exc)
        return
    handler._redirect("/admin/wps/users")
