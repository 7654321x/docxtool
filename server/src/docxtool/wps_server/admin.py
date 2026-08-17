"""Administrator queries and status changes for the WPS plugin database."""

from __future__ import annotations

from collections.abc import Mapping
import logging
import uuid
from typing import Callable

from .config import WPS_OFFLINE_AFTER_SECONDS
from .service import _hash_wps_password
from .validation import validate_notification_content, validate_password

LOGGER = logging.getLogger("docx_tool")

DEFAULT_ADMIN_PAGE_SIZE = 20
MAX_ADMIN_PAGE_SIZE = 100
_USER_STATUSES = frozenset({"active", "disabled"})
_REQUEST_STATUSES = frozenset({"authorized", "success", "failed"})
_ONLINE_FILTERS = frozenset({"online", "offline"})
_ADMIN_ACTOR_TYPES = frozenset({"session", "legacy_token"})


class WpsAdminError(RuntimeError):
    """Stable WPS administrator mutation failure with an HTTP-safe error code."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        self.code = code
        self.message = message
        self.status = status
        super().__init__(code)


def _clean_text(value: object, *, limit: int = 80) -> str:
    """Return a bounded query value without changing its SQL parameter semantics."""
    return str(value or "").strip()[:limit]


def _page_values(page: object, page_size: object) -> tuple[int, int, int]:
    """Normalize server-side pagination and return page, size, and offset."""
    try:
        normalized_page = max(1, int(page))
    except (TypeError, ValueError):
        normalized_page = 1
    try:
        normalized_size = int(page_size)
    except (TypeError, ValueError):
        normalized_size = DEFAULT_ADMIN_PAGE_SIZE
    normalized_size = max(1, min(MAX_ADMIN_PAGE_SIZE, normalized_size))
    return normalized_page, normalized_size, (normalized_page - 1) * normalized_size


def _page_result(rows, total: int, page: int, page_size: int) -> dict:
    """Return the canonical server-pagination response shape."""
    total = int(total)
    last_page = max(1, (total + page_size - 1) // page_size)
    page = min(page, last_page)
    return {
        "rows": [dict(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _page_for_total(total: int, requested_page: int, page_size: int) -> tuple[int, int]:
    """Clamp a requested page after counting and return the matching offset."""
    last_page = max(1, (int(total) + page_size - 1) // page_size)
    page = min(requested_page, last_page)
    return page, (page - 1) * page_size


def overview(*, connect_func: Callable, sql_lock, now: int) -> dict:
    with sql_lock:
        conn = connect_func()
        try:
            row = conn.execute(
                """SELECT
                     (SELECT COUNT(*) FROM wps_users) AS users,
                     (SELECT COUNT(*) FROM wps_devices WHERE status='active' AND last_seen_at>=?) AS online_devices,
                     (SELECT COUNT(*) FROM wps_format_requests) AS requests,
                     (SELECT COUNT(*) FROM wps_format_requests WHERE status='authorized') AS pending,
                     (SELECT COUNT(*) FROM wps_format_requests WHERE status='success') AS success,
                     (SELECT COUNT(*) FROM wps_format_requests WHERE status='failed') AS failed,
                     (SELECT COALESCE(AVG(duration_ms), 0) FROM wps_format_requests WHERE status IN ('success','failed')) AS average_duration_ms""",
                (now - WPS_OFFLINE_AFTER_SECONDS,),
            ).fetchone()
        finally:
            conn.close()
    return dict(row)


def list_users(
    *,
    connect_func: Callable,
    sql_lock,
    now: int,
    query: str = "",
    status: str = "",
    online: str = "",
    version: str = "",
    page: int = 1,
    page_size: int = DEFAULT_ADMIN_PAGE_SIZE,
) -> dict:
    """Return a server-paged user list with only real WPS aggregate data."""
    where: list[str] = []
    params: list[object] = []
    search = _clean_text(query).lower()
    normalized_status = _clean_text(status, limit=20)
    normalized_online = _clean_text(online, limit=20)
    normalized_version = _clean_text(version, limit=40)
    threshold = int(now) - WPS_OFFLINE_AFTER_SECONDS
    if search:
        where.append("u.username_norm LIKE ?")
        params.append(f"%{search}%")
    if normalized_status in _USER_STATUSES:
        where.append("u.status=?")
        params.append(normalized_status)
    if normalized_online == "online":
        where.append(
            "EXISTS(SELECT 1 FROM wps_devices d WHERE d.user_id=u.id "
            "AND d.status='active' AND d.last_seen_at>=?)"
        )
        params.append(threshold)
    elif normalized_online == "offline":
        where.append(
            "NOT EXISTS(SELECT 1 FROM wps_devices d WHERE d.user_id=u.id "
            "AND d.status='active' AND d.last_seen_at>=?)"
        )
        params.append(threshold)
    if normalized_version:
        where.append(
            "EXISTS(SELECT 1 FROM wps_devices d WHERE d.user_id=u.id AND d.app_version LIKE ?)"
        )
        params.append(f"%{normalized_version}%")
    clause = " WHERE " + " AND ".join(where) if where else ""
    requested_page, normalized_size, _ = _page_values(page, page_size)
    with sql_lock:
        conn = connect_func()
        try:
            total = conn.execute(f"SELECT COUNT(*) FROM wps_users u{clause}", params).fetchone()[0]
            requested_page, offset = _page_for_total(total, requested_page, normalized_size)
            rows = conn.execute(
                f"""SELECT u.*,
                       (SELECT COUNT(*) FROM wps_devices d WHERE d.user_id=u.id) AS device_count,
                       CASE WHEN EXISTS(
                           SELECT 1 FROM wps_devices d
                           WHERE d.user_id=u.id AND d.status='active' AND d.last_seen_at>=?
                       ) THEN 1 ELSE 0 END AS online,
                       (SELECT d.app_version FROM wps_devices d WHERE d.user_id=u.id
                        ORDER BY d.last_seen_at DESC, d.created_at DESC LIMIT 1) AS app_version,
                       (SELECT COUNT(*) FROM wps_format_requests r WHERE r.user_id=u.id) AS format_total,
                       (SELECT COUNT(*) FROM wps_format_requests r WHERE r.user_id=u.id AND r.status='success') AS format_success,
                       (SELECT COUNT(*) FROM wps_format_requests r WHERE r.user_id=u.id AND r.status='failed') AS format_failed,
                       (SELECT COUNT(*) FROM wps_format_requests r WHERE r.user_id=u.id AND r.status='authorized') AS format_pending,
                       (SELECT MAX(r.requested_at) FROM wps_format_requests r WHERE r.user_id=u.id) AS last_format_at
                   FROM wps_users u{clause}
                   ORDER BY u.created_at DESC, u.id DESC
                   LIMIT ? OFFSET ?""",
                [threshold, *params, normalized_size, offset],
            ).fetchall()
        finally:
            conn.close()
    return _page_result(rows, total, requested_page, normalized_size)


def list_devices(
    *,
    connect_func: Callable,
    sql_lock,
    now: int,
    query: str = "",
    status: str = "",
    online: str = "",
    version: str = "",
    user_id: str = "",
    page: int = 1,
    page_size: int = DEFAULT_ADMIN_PAGE_SIZE,
) -> dict:
    """Return a server-paged WPS device list with scoped filters."""
    where: list[str] = []
    params: list[object] = []
    search = _clean_text(query).lower()
    normalized_status = _clean_text(status, limit=20)
    normalized_online = _clean_text(online, limit=20)
    normalized_version = _clean_text(version, limit=40)
    normalized_user_id = _clean_text(user_id, limit=120)
    threshold = int(now) - WPS_OFFLINE_AFTER_SECONDS
    if search:
        where.append("(u.username_norm LIKE ? OR d.device_name LIKE ? OR d.id LIKE ?)")
        pattern = f"%{search}%"
        params.extend((pattern, pattern, pattern))
    if normalized_status in _USER_STATUSES:
        where.append("d.status=?")
        params.append(normalized_status)
    if normalized_online == "online":
        where.append("d.status='active' AND d.last_seen_at>=?")
        params.append(threshold)
    elif normalized_online == "offline":
        where.append("NOT (d.status='active' AND d.last_seen_at>=?)")
        params.append(threshold)
    if normalized_version:
        where.append("d.app_version LIKE ?")
        params.append(f"%{normalized_version}%")
    if normalized_user_id:
        where.append("d.user_id=?")
        params.append(normalized_user_id)
    clause = " WHERE " + " AND ".join(where) if where else ""
    requested_page, normalized_size, _ = _page_values(page, page_size)
    with sql_lock:
        conn = connect_func()
        try:
            total = conn.execute(
                f"SELECT COUNT(*) FROM wps_devices d JOIN wps_users u ON u.id=d.user_id{clause}",
                params,
            ).fetchone()[0]
            requested_page, offset = _page_for_total(total, requested_page, normalized_size)
            rows = conn.execute(
                f"""SELECT d.*, u.username,
                       CASE WHEN d.status='active' AND d.last_seen_at>=? THEN 1 ELSE 0 END AS online,
                       (SELECT COUNT(*) FROM wps_format_requests r WHERE r.device_id=d.id) AS format_total
                   FROM wps_devices d JOIN wps_users u ON u.id=d.user_id{clause}
                   ORDER BY d.last_seen_at DESC, d.created_at DESC, d.id DESC
                   LIMIT ? OFFSET ?""",
                [threshold, *params, normalized_size, offset],
            ).fetchall()
        finally:
            conn.close()
    return _page_result(rows, total, requested_page, normalized_size)


def list_format_requests(
    *,
    connect_func: Callable,
    sql_lock,
    query: str = "",
    status: str = "",
    version: str = "",
    user_id: str = "",
    page: int = 1,
    page_size: int = DEFAULT_ADMIN_PAGE_SIZE,
) -> dict:
    """Return a server-paged WPS request list with stable request and user joins."""
    where: list[str] = []
    params: list[object] = []
    search = _clean_text(query).lower()
    normalized_status = _clean_text(status, limit=20)
    normalized_version = _clean_text(version, limit=40)
    normalized_user_id = _clean_text(user_id, limit=120)
    if search:
        where.append("(r.request_id LIKE ? OR u.username_norm LIKE ? OR COALESCE(d.device_name, '') LIKE ?)")
        pattern = f"%{search}%"
        params.extend((pattern, pattern, pattern))
    if normalized_status in _REQUEST_STATUSES:
        where.append("r.status=?")
        params.append(normalized_status)
    if normalized_version:
        where.append("r.app_version LIKE ?")
        params.append(f"%{normalized_version}%")
    if normalized_user_id:
        where.append("r.user_id=?")
        params.append(normalized_user_id)
    clause = " WHERE " + " AND ".join(where) if where else ""
    requested_page, normalized_size, _ = _page_values(page, page_size)
    source = "wps_format_requests r JOIN wps_users u ON u.id=r.user_id LEFT JOIN wps_devices d ON d.id=r.device_id"
    with sql_lock:
        conn = connect_func()
        try:
            total = conn.execute(f"SELECT COUNT(*) FROM {source}{clause}", params).fetchone()[0]
            requested_page, offset = _page_for_total(total, requested_page, normalized_size)
            rows = conn.execute(
                f"""SELECT r.*, u.username, COALESCE(d.device_name, '') AS device_name,
                           COALESCE(d.platform, '') AS platform
                   FROM {source}{clause}
                   ORDER BY r.requested_at DESC, r.request_id DESC
                   LIMIT ? OFFSET ?""",
                [*params, normalized_size, offset],
            ).fetchall()
        finally:
            conn.close()
    return _page_result(rows, total, requested_page, normalized_size)


def overview_trend(*, connect_func: Callable, sql_lock, now: int, days: int = 7) -> list[dict]:
    """Return only real WPS request trend rows from the requested recent window."""
    normalized_days = max(1, min(31, int(days)))
    cutoff = int(now) - normalized_days * 24 * 60 * 60
    with sql_lock:
        conn = connect_func()
        try:
            rows = conn.execute(
                """SELECT strftime('%Y-%m-%d', requested_at, 'unixepoch') AS date,
                           COUNT(*) AS total,
                           SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS success,
                           SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed
                    FROM wps_format_requests
                    WHERE requested_at>=?
                    GROUP BY strftime('%Y-%m-%d', requested_at, 'unixepoch')
                    ORDER BY date ASC""",
                (cutoff,),
            ).fetchall()
        finally:
            conn.close()
    return [dict(row) for row in rows]


def user_detail(user_id: str, *, connect_func: Callable, sql_lock, now: int) -> dict:
    """Return user identity and summary fields; list tabs are paged separately."""
    threshold = int(now) - WPS_OFFLINE_AFTER_SECONDS
    with sql_lock:
        conn = connect_func()
        try:
            user = conn.execute("SELECT * FROM wps_users WHERE id=?", (user_id,)).fetchone()
            if user is None:
                return {}
            summary = conn.execute(
                """SELECT
                       (SELECT COUNT(*) FROM wps_devices d WHERE d.user_id=?) AS device_count,
                       (SELECT COUNT(*) FROM wps_devices d WHERE d.user_id=? AND d.status='active' AND d.last_seen_at>=?) AS online_devices,
                       (SELECT COUNT(*) FROM wps_format_requests r WHERE r.user_id=?) AS format_total,
                       (SELECT COUNT(*) FROM wps_format_requests r WHERE r.user_id=? AND r.status='success') AS format_success,
                       (SELECT COUNT(*) FROM wps_format_requests r WHERE r.user_id=? AND r.status='failed') AS format_failed,
                       (SELECT COUNT(*) FROM wps_format_requests r WHERE r.user_id=? AND r.status='authorized') AS format_pending,
                       (SELECT COALESCE(AVG(r.duration_ms), 0) FROM wps_format_requests r
                        WHERE r.user_id=? AND r.status IN ('success','failed')) AS average_duration_ms""",
                (user_id, user_id, threshold, user_id, user_id, user_id, user_id, user_id),
            ).fetchone()
            current_device = conn.execute(
                """SELECT d.id,d.device_name,d.platform,d.app_version,d.status,d.last_seen_at,d.created_at,
                           CASE WHEN d.status='active' AND d.last_seen_at>=? THEN 1 ELSE 0 END AS online
                   FROM wps_devices d
                   WHERE d.user_id=?
                   ORDER BY CASE WHEN d.status='active' AND d.last_seen_at>=? THEN 1 ELSE 0 END DESC,
                            d.last_seen_at DESC,d.created_at DESC,d.id DESC
                   LIMIT 1""",
                (threshold, user_id, threshold),
            ).fetchone()
        finally:
            conn.close()
    return {
        "user": dict(user),
        "summary": dict(summary),
        "current_device": dict(current_device) if current_device is not None else None,
    }


def _audit_values(
    actor: Mapping[str, object], correlation_id: object
) -> tuple[str, str, str]:
    """Validate the minimal, non-reusable administrator audit context."""
    actor_type = str(actor.get("actor_type") or "").strip()
    if actor_type not in _ADMIN_ACTOR_TYPES:
        raise WpsAdminError("WPS_ADMIN_AUDIT_ACTOR_INVALID", "管理员审计上下文无效")
    session_short = str(actor.get("actor_session_id_short") or "").strip()[:32]
    if actor_type == "session" and not session_short:
        raise WpsAdminError("WPS_ADMIN_AUDIT_ACTOR_INVALID", "管理员审计上下文无效")
    if actor_type == "legacy_token":
        session_short = ""
    normalized_correlation = str(correlation_id or "").strip()[:96]
    if not normalized_correlation:
        raise WpsAdminError("WPS_ADMIN_CORRELATION_INVALID", "管理员请求关联编号无效")
    return actor_type, session_short, normalized_correlation


def _write_admin_audit(
    conn,
    *,
    actor_type: str,
    actor_session_id_short: str,
    target_user_id: str,
    event: str,
    result: str,
    error_code: str,
    correlation_id: str,
    now: int,
) -> None:
    """Write one successful or denied management fact in the caller transaction."""
    conn.execute(
        """INSERT INTO wps_admin_audit_logs
           (audit_id,actor_type,actor_session_id_short,target_user_id,event,result,error_code,correlation_id,created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            f"waud_{uuid.uuid4().hex}",
            actor_type,
            actor_session_id_short,
            target_user_id,
            event,
            result,
            error_code,
            correlation_id,
            int(now),
        ),
    )


def list_admin_audit_logs(
    user_id: str,
    *,
    connect_func: Callable,
    sql_lock,
    page: int = 1,
    page_size: int = DEFAULT_ADMIN_PAGE_SIZE,
) -> dict:
    """Return server-paged, non-sensitive WPS administrator audit facts for one user."""
    requested_page, normalized_size, _ = _page_values(page, page_size)
    with sql_lock:
        conn = connect_func()
        try:
            total = int(
                conn.execute(
                    "SELECT COUNT(*) FROM wps_admin_audit_logs WHERE target_user_id=?",
                    (user_id,),
                ).fetchone()[0]
            )
            requested_page, offset = _page_for_total(total, requested_page, normalized_size)
            rows = conn.execute(
                """SELECT audit_id,actor_type,actor_session_id_short,target_user_id,event,result,error_code,correlation_id,created_at
                   FROM wps_admin_audit_logs WHERE target_user_id=?
                   ORDER BY created_at DESC, audit_id DESC LIMIT ? OFFSET ?""",
                (user_id, normalized_size, offset),
            ).fetchall()
        finally:
            conn.close()
    return _page_result(rows, total, requested_page, normalized_size)


def set_user_status(
    user_id: str,
    status: str,
    *,
    connect_func: Callable,
    sql_lock,
    now: int,
    actor: Mapping[str, object],
    correlation_id: str,
) -> str:
    """Set a user status, revoke disabled sessions, and commit its audit fact together."""
    if status not in _USER_STATUSES:
        raise WpsAdminError("WPS_ADMIN_STATUS_INVALID", "账号状态无效")
    actor_type, session_short, request_id = _audit_values(actor, correlation_id)
    normalized_user_id = _clean_text(user_id, limit=120)
    LOGGER.info(
        "wps.admin.user.status.start | user_id=%s status=%s correlation_id=%s",
        normalized_user_id[:12],
        status,
        request_id,
    )
    with sql_lock:
        conn = connect_func()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "UPDATE wps_users SET status=?,updated_at=? WHERE id=?",
                (status, int(now), normalized_user_id),
            )
            if cursor.rowcount != 1:
                raise WpsAdminError("WPS_USER_NOT_FOUND", "WPS 用户不存在", 404)
            if status == "disabled":
                conn.execute("DELETE FROM wps_sessions WHERE user_id=?", (normalized_user_id,))
            _write_admin_audit(
                conn,
                actor_type=actor_type,
                actor_session_id_short=session_short,
                target_user_id=normalized_user_id,
                event="wps.admin.user.status.updated",
                result="success",
                error_code="",
                correlation_id=request_id,
                now=now,
            )
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            LOGGER.exception(
                "wps.admin.user.status.error | user_id=%s status=%s correlation_id=%s",
                normalized_user_id[:12],
                status,
                request_id,
            )
            raise
        finally:
            conn.close()
    LOGGER.info(
        "wps.admin.user.status.success | user_id=%s status=%s correlation_id=%s",
        normalized_user_id[:12],
        status,
        request_id,
    )
    return normalized_user_id


def set_device_status(
    device_id: str,
    status: str,
    *,
    connect_func: Callable,
    sql_lock,
    now: int,
    actor: Mapping[str, object],
    correlation_id: str,
) -> str:
    """Set a device status, revoke disabled sessions, and commit its audit fact together."""
    if status not in _USER_STATUSES:
        raise WpsAdminError("WPS_ADMIN_STATUS_INVALID", "设备状态无效")
    actor_type, session_short, request_id = _audit_values(actor, correlation_id)
    normalized_device_id = _clean_text(device_id, limit=120)
    LOGGER.info(
        "wps.admin.device.status.start | device_id=%s status=%s correlation_id=%s",
        normalized_device_id[:12],
        status,
        request_id,
    )
    target_user_id = ""
    with sql_lock:
        conn = connect_func()
        try:
            conn.execute("BEGIN IMMEDIATE")
            device = conn.execute(
                "SELECT user_id FROM wps_devices WHERE id=?", (normalized_device_id,)
            ).fetchone()
            if device is None:
                raise WpsAdminError("WPS_DEVICE_NOT_FOUND", "WPS 设备不存在", 404)
            target_user_id = str(device["user_id"])
            conn.execute(
                "UPDATE wps_devices SET status=? WHERE id=?",
                (status, normalized_device_id),
            )
            if status == "disabled":
                conn.execute("DELETE FROM wps_sessions WHERE device_id=?", (normalized_device_id,))
            _write_admin_audit(
                conn,
                actor_type=actor_type,
                actor_session_id_short=session_short,
                target_user_id=target_user_id,
                event="wps.admin.device.status.updated",
                result="success",
                error_code="",
                correlation_id=request_id,
                now=now,
            )
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            LOGGER.exception(
                "wps.admin.device.status.error | device_id=%s status=%s correlation_id=%s",
                normalized_device_id[:12],
                status,
                request_id,
            )
            raise
        finally:
            conn.close()
    LOGGER.info(
        "wps.admin.device.status.success | device_id=%s status=%s correlation_id=%s",
        normalized_device_id[:12],
        status,
        request_id,
    )
    LOGGER.info(
        "wps.device.%s | device_id=%s",
        "enabled" if status == "active" else "disabled",
        normalized_device_id[:12],
    )
    return target_user_id


def reset_user_password(
    user_id: str,
    password: str,
    *,
    connect_func: Callable,
    sql_lock,
    now: int,
    actor: Mapping[str, object],
    correlation_id: str,
) -> str:
    """Replace a user password, revoke sessions, and audit the committed mutation."""
    normalized_password = validate_password(password)
    password_hash = _hash_wps_password(normalized_password)
    actor_type, session_short, request_id = _audit_values(actor, correlation_id)
    normalized_user_id = _clean_text(user_id, limit=120)
    LOGGER.info(
        "wps.admin.user.password_reset.start | user_id=%s correlation_id=%s",
        normalized_user_id[:12],
        request_id,
    )
    with sql_lock:
        conn = connect_func()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "UPDATE wps_users SET password_hash=?,updated_at=? WHERE id=?",
                (password_hash, int(now), normalized_user_id),
            )
            if cursor.rowcount != 1:
                raise WpsAdminError("WPS_USER_NOT_FOUND", "WPS 用户不存在", 404)
            conn.execute("DELETE FROM wps_sessions WHERE user_id=?", (normalized_user_id,))
            _write_admin_audit(
                conn,
                actor_type=actor_type,
                actor_session_id_short=session_short,
                target_user_id=normalized_user_id,
                event="wps.admin.user.password_reset",
                result="success",
                error_code="",
                correlation_id=request_id,
                now=now,
            )
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            LOGGER.exception(
                "wps.admin.user.password_reset.error | user_id=%s correlation_id=%s",
                normalized_user_id[:12],
                request_id,
            )
            raise
        finally:
            conn.close()
    LOGGER.info(
        "wps.admin.user.password_reset.success | user_id=%s correlation_id=%s",
        normalized_user_id[:12],
        request_id,
    )
    return normalized_user_id


def send_notification(
    user_id: str,
    title: str,
    body: str,
    level: str,
    *,
    connect_func: Callable,
    sql_lock,
    now: int,
    actor: Mapping[str, object],
    correlation_id: str,
) -> str:
    """Persist one plain-text account notification and its audit fact atomically."""
    normalized_title, normalized_body, normalized_level = validate_notification_content(
        title,
        body,
        level,
    )
    actor_type, session_short, request_id = _audit_values(actor, correlation_id)
    normalized_user_id = _clean_text(user_id, limit=120)
    notification_id = f"wnot_{uuid.uuid4().hex}"
    LOGGER.info(
        "wps.admin.notification.send.start | user_id=%s level=%s correlation_id=%s",
        normalized_user_id[:12],
        normalized_level,
        request_id,
    )
    with sql_lock:
        conn = connect_func()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute(
                "SELECT 1 FROM wps_users WHERE id=?", (normalized_user_id,)
            ).fetchone() is None:
                raise WpsAdminError("WPS_USER_NOT_FOUND", "WPS 用户不存在", 404)
            conn.execute(
                """INSERT INTO wps_notifications
                   (notification_id,user_id,title,body,level,created_at,acknowledged_at)
                   VALUES (?,?,?,?,?,?,0)""",
                (
                    notification_id,
                    normalized_user_id,
                    normalized_title,
                    normalized_body,
                    normalized_level,
                    int(now),
                ),
            )
            _write_admin_audit(
                conn,
                actor_type=actor_type,
                actor_session_id_short=session_short,
                target_user_id=normalized_user_id,
                event="wps.admin.notification.sent",
                result="success",
                error_code="",
                correlation_id=request_id,
                now=now,
            )
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            LOGGER.exception(
                "wps.admin.notification.send.error | user_id=%s level=%s correlation_id=%s",
                normalized_user_id[:12],
                normalized_level,
                request_id,
            )
            raise
        finally:
            conn.close()
    LOGGER.info(
        "wps.admin.notification.send.success | user_id=%s level=%s correlation_id=%s",
        normalized_user_id[:12],
        normalized_level,
        request_id,
    )
    return notification_id


def delete_user(
    user_id: str,
    confirmation_username: str,
    *,
    connect_func: Callable,
    sql_lock,
    now: int,
    actor: Mapping[str, object],
    correlation_id: str,
) -> str:
    """Hard-delete one WPS user and dependent data while retaining the audit fact."""
    actor_type, session_short, request_id = _audit_values(actor, correlation_id)
    normalized_user_id = _clean_text(user_id, limit=120)
    confirmation = _clean_text(confirmation_username, limit=80)
    LOGGER.info(
        "wps.admin.user.delete.start | user_id=%s correlation_id=%s",
        normalized_user_id[:12],
        request_id,
    )
    denied_error = None
    with sql_lock:
        conn = connect_func()
        try:
            conn.execute("BEGIN IMMEDIATE")
            user = conn.execute(
                "SELECT username FROM wps_users WHERE id=?", (normalized_user_id,)
            ).fetchone()
            if user is None:
                raise WpsAdminError("WPS_USER_NOT_FOUND", "WPS 用户不存在", 404)
            if confirmation != str(user["username"]):
                _write_admin_audit(
                    conn,
                    actor_type=actor_type,
                    actor_session_id_short=session_short,
                    target_user_id=normalized_user_id,
                    event="wps.admin.user.delete.denied",
                    result="denied",
                    error_code="WPS_ADMIN_DELETE_CONFIRMATION_INVALID",
                    correlation_id=request_id,
                    now=now,
                )
                conn.commit()
                denied_error = WpsAdminError(
                    "WPS_ADMIN_DELETE_CONFIRMATION_INVALID",
                    "删除确认账号不匹配",
                )
            else:
                conn.execute("DELETE FROM wps_sessions WHERE user_id=?", (normalized_user_id,))
                conn.execute("DELETE FROM wps_format_requests WHERE user_id=?", (normalized_user_id,))
                conn.execute("DELETE FROM wps_notifications WHERE user_id=?", (normalized_user_id,))
                conn.execute("DELETE FROM wps_devices WHERE user_id=?", (normalized_user_id,))
                conn.execute("DELETE FROM wps_users WHERE id=?", (normalized_user_id,))
                _write_admin_audit(
                    conn,
                    actor_type=actor_type,
                    actor_session_id_short=session_short,
                    target_user_id=normalized_user_id,
                    event="wps.admin.user.deleted",
                    result="success",
                    error_code="",
                    correlation_id=request_id,
                    now=now,
                )
                conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            LOGGER.exception(
                "wps.admin.user.delete.error | user_id=%s correlation_id=%s",
                normalized_user_id[:12],
                request_id,
            )
            raise
        finally:
            conn.close()
    if denied_error is not None:
        LOGGER.warning(
            "wps.admin.user.delete.denied | user_id=%s correlation_id=%s error_code=%s",
            normalized_user_id[:12],
            request_id,
            denied_error.code,
        )
        raise denied_error
    LOGGER.info(
        "wps.admin.user.delete.success | user_id=%s correlation_id=%s",
        normalized_user_id[:12],
        request_id,
    )
    return normalized_user_id
