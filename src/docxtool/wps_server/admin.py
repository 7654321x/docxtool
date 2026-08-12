"""Administrator queries and status changes for the WPS plugin database."""

from __future__ import annotations

import logging
from typing import Callable

from .config import WPS_OFFLINE_AFTER_SECONDS

LOGGER = logging.getLogger("docx_tool")


def overview(*, connect_func: Callable, sql_lock, now: int) -> dict:
    with sql_lock:
        conn = connect_func()
        try:
            row = conn.execute(
                """SELECT
                     (SELECT COUNT(*) FROM wps_users) AS users,
                     (SELECT COUNT(*) FROM wps_devices WHERE status='active' AND last_seen_at>=?) AS online_devices,
                     (SELECT COUNT(*) FROM wps_format_requests) AS requests,
                     (SELECT COUNT(*) FROM wps_format_requests WHERE status='authorized') AS pending""",
                (now - WPS_OFFLINE_AFTER_SECONDS,),
            ).fetchone()
        finally:
            conn.close()
    return dict(row)


def list_users(*, connect_func: Callable, sql_lock, now: int, query: str = "", status: str = "") -> list[dict]:
    where = []
    params = []
    if query:
        where.append("u.username_norm LIKE ?")
        pattern = f"%{query.lower()}%"
        params.append(pattern)
    if status in {"active", "disabled"}:
        where.append("u.status=?")
        params.append(status)
    clause = "WHERE " + " AND ".join(where) if where else ""
    params.append(now - WPS_OFFLINE_AFTER_SECONDS)
    with sql_lock:
        conn = connect_func()
        try:
            rows = conn.execute(
                f"""SELECT u.*,
                       COUNT(DISTINCT d.id) AS device_count,
                       MAX(CASE WHEN d.status='active' AND d.last_seen_at>=? THEN 1 ELSE 0 END) AS online,
                       MAX(d.app_version) AS app_version,
                       COUNT(DISTINCT r.request_id) AS format_total,
                       COUNT(DISTINCT CASE WHEN r.status='success' THEN r.request_id END) AS format_success,
                       COUNT(DISTINCT CASE WHEN r.status='failed' THEN r.request_id END) AS format_failed,
                       COUNT(DISTINCT CASE WHEN r.status='authorized' THEN r.request_id END) AS format_pending,
                       MAX(r.requested_at) AS last_format_at
                   FROM wps_users u
                   LEFT JOIN wps_devices d ON d.user_id=u.id
                   LEFT JOIN wps_format_requests r ON r.user_id=u.id
                   {clause}
                   GROUP BY u.id
                   ORDER BY u.created_at DESC
                   LIMIT 200""",
                (params[-1], *params[:-1]),
            ).fetchall()
        finally:
            conn.close()
    return [dict(row) for row in rows]


def user_detail(user_id: str, *, connect_func: Callable, sql_lock) -> dict:
    with sql_lock:
        conn = connect_func()
        try:
            user = conn.execute("SELECT * FROM wps_users WHERE id=?", (user_id,)).fetchone()
            if user is None:
                return {}
            devices = conn.execute(
                "SELECT * FROM wps_devices WHERE user_id=? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
            requests = conn.execute(
                """SELECT * FROM wps_format_requests WHERE user_id=?
                   ORDER BY requested_at DESC LIMIT 200""",
                (user_id,),
            ).fetchall()
        finally:
            conn.close()
    return {"user": dict(user), "devices": [dict(row) for row in devices], "requests": [dict(row) for row in requests]}


def set_user_status(user_id: str, status: str, *, connect_func: Callable, sql_lock, now: int) -> None:
    if status not in {"active", "disabled"}:
        raise ValueError("WPS_ADMIN_STATUS_INVALID")
    with sql_lock:
        conn = connect_func()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute("UPDATE wps_users SET status=?,updated_at=? WHERE id=?", (status, now, user_id))
            if cursor.rowcount != 1:
                raise ValueError("WPS_USER_NOT_FOUND")
            if status == "disabled":
                conn.execute("DELETE FROM wps_sessions WHERE user_id=?", (user_id,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    LOGGER.info(
        "wps.admin.user.status_changed | user_id=%s status=%s",
        user_id[:12],
        status,
    )


def set_device_status(device_id: str, status: str, *, connect_func: Callable, sql_lock) -> None:
    if status not in {"active", "disabled"}:
        raise ValueError("WPS_ADMIN_STATUS_INVALID")
    with sql_lock:
        conn = connect_func()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute("UPDATE wps_devices SET status=? WHERE id=?", (status, device_id))
            if cursor.rowcount != 1:
                raise ValueError("WPS_DEVICE_NOT_FOUND")
            if status == "disabled":
                conn.execute("DELETE FROM wps_sessions WHERE device_id=?", (device_id,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    LOGGER.info(
        "wps.admin.device.status_changed | device_id=%s status=%s",
        device_id[:12],
        status,
    )
    LOGGER.info(
        "wps.device.%s | device_id=%s",
        "enabled" if status == "active" else "disabled",
        device_id[:12],
    )
