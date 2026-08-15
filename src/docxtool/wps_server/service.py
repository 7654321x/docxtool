"""Transactions for WPS registration, sessions, heartbeat, and formatting authorization."""

from __future__ import annotations

from copy import deepcopy
import logging
import sqlite3
import threading
import uuid

from docxtool.auth.passwords import hash_password, verify_password

from .auth import create_session_in_connection, device_fingerprint_hash
from .config import (
    WPS_CONTROLLED_COMMANDS,
    WPS_HEARTBEAT_INTERVAL_SECONDS,
    WPS_OFFLINE_AFTER_SECONDS,
    public_feature_manifest,
)
from .validation import (
    WPS_NOTIFICATION_BATCH_MAX,
    WpsValidationError,
    require_object_fields,
    validate_app_version,
    validate_device_payload,
    validate_error_code,
    validate_notification_ids,
    validate_password,
    validate_request_id,
    validate_username,
)

LOGGER = logging.getLogger("docx_tool")
_WPS_ARGON2_LIMIT = threading.BoundedSemaphore(2)
_DUMMY_PASSWORD = "DocxToolWpsDummy01"


def _hash_wps_password(password: str) -> str:
    with _WPS_ARGON2_LIMIT:
        return hash_password(password)


def _verify_wps_password(password_hash: str, password: str) -> tuple[bool, bool]:
    with _WPS_ARGON2_LIMIT:
        return verify_password(password_hash, password)


_DUMMY_PASSWORD_HASH = _hash_wps_password(_DUMMY_PASSWORD)


class WpsServiceError(RuntimeError):
    def __init__(self, code: str, message: str, status: int) -> None:
        self.code = code
        self.message = message
        self.status = status
        super().__init__(code)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def list_pending_notifications(
    user_id: str,
    *,
    connect_func,
    sql_lock,
) -> list[dict]:
    """Return the bounded, account-scoped notifications not yet acknowledged."""
    with sql_lock:
        conn = connect_func()
        try:
            rows = conn.execute(
                """SELECT notification_id,title,body,level,created_at
                   FROM wps_notifications
                   WHERE user_id=? AND acknowledged_at=0
                   ORDER BY created_at ASC, notification_id ASC
                   LIMIT ?""",
                (user_id, WPS_NOTIFICATION_BATCH_MAX),
            ).fetchall()
        finally:
            conn.close()
    return [dict(row) for row in rows]


def _session_response(
    user: dict,
    device: dict,
    session: dict,
    config_version: str,
    *,
    notifications: list[dict],
) -> dict:
    return {
        "user": user,
        "device": device,
        "session_token": session["token"],
        "session_created_at": session["created_at"],
        "session_expires_at": session["expires_at"],
        "features": public_feature_manifest(),
        "config_version": config_version,
        "heartbeat_interval_seconds": WPS_HEARTBEAT_INTERVAL_SECONDS,
        "notifications": notifications,
    }


def register_user(payload, *, connect_func, sql_lock, client_ip, now_func, config_version) -> dict:
    require_object_fields(payload, required=("username", "password", "device"))
    username, username_norm = validate_username(payload["username"])
    password = validate_password(payload["password"])
    device_data = validate_device_payload(payload["device"])
    password_digest = _hash_wps_password(password)
    fingerprint = device_fingerprint_hash(device_data["device_key"])
    now = int(now_func())
    user_id = _id("wusr")
    device_id = _id("wdev")
    with sql_lock:
        conn = connect_func()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM wps_users WHERE username_norm=?", (username_norm,)).fetchone():
                raise WpsServiceError("USERNAME_TAKEN", "账号已存在", 409)
            conn.execute(
                """INSERT INTO wps_users
                   (id,username,username_norm,password_hash,status,created_at,updated_at,last_login_at)
                   VALUES (?,?,?,?,'active',?,?,?)""",
                (user_id, username, username_norm, password_digest, now, now, now),
            )
            conn.execute(
                """INSERT INTO wps_devices
                   (id,user_id,fingerprint_hash,device_name,platform,app_version,status,created_at,last_seen_at,last_ip)
                   VALUES (?,?,?,?,?,?,'active',?,?,?)""",
                (device_id, user_id, fingerprint, device_data["device_name"], device_data["platform"], device_data["app_version"], now, now, client_ip[:80]),
            )
            session = create_session_in_connection(
                conn, user_id, device_id, client_ip, device_data["app_version"], now
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            if "username_norm" in str(exc):
                raise WpsServiceError("USERNAME_TAKEN", "账号已存在", 409) from exc
            raise
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    LOGGER.info("wps.auth.register.completed | user_id=%s device_id=%s", user_id[:12], device_id[:12])
    LOGGER.info("wps.device.created | user_id=%s device_id=%s", user_id[:12], device_id[:12])
    LOGGER.info("wps.device.online | user_id=%s device_id=%s", user_id[:12], device_id[:12])
    LOGGER.info("wps.auth.session.created | user_id=%s device_id=%s", user_id[:12], device_id[:12])
    return _session_response(
        {"id": user_id, "username": username, "status": "active"},
        {"id": device_id, "device_name": device_data["device_name"], "platform": device_data["platform"], "status": "active"},
        session,
        config_version,
        notifications=list_pending_notifications(
            user_id,
            connect_func=connect_func,
            sql_lock=sql_lock,
        ),
    )


def login_user(payload, *, connect_func, sql_lock, client_ip, now_func, config_version) -> dict:
    require_object_fields(payload, required=("username", "password", "device"))
    try:
        _, username_norm = validate_username(payload["username"])
        password = validate_password(payload["password"])
    except WpsValidationError as exc:
        raise WpsServiceError("INVALID_CREDENTIALS", "账号或密码错误", 401) from exc
    device_data = validate_device_payload(payload["device"])
    with sql_lock:
        conn = connect_func()
        try:
            user = conn.execute("SELECT * FROM wps_users WHERE username_norm=?", (username_norm,)).fetchone()
        finally:
            conn.close()
    if user is None:
        _verify_wps_password(_DUMMY_PASSWORD_HASH, password)
        raise WpsServiceError("INVALID_CREDENTIALS", "账号或密码错误", 401)
    valid, needs_rehash = _verify_wps_password(user["password_hash"], password)
    if not valid:
        raise WpsServiceError("INVALID_CREDENTIALS", "账号或密码错误", 401)
    if user["status"] != "active":
        raise WpsServiceError("ACCOUNT_DISABLED", "账号已停用", 403)
    updated_password_hash = _hash_wps_password(password) if needs_rehash else ""
    now = int(now_func())
    fingerprint = device_fingerprint_hash(device_data["device_key"])
    device_created = False
    with sql_lock:
        conn = connect_func()
        try:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute("SELECT * FROM wps_users WHERE id=?", (user["id"],)).fetchone()
            if current is None or current["status"] != "active":
                raise WpsServiceError("ACCOUNT_DISABLED", "账号已停用", 403)
            device = conn.execute(
                "SELECT * FROM wps_devices WHERE user_id=? AND fingerprint_hash=?",
                (user["id"], fingerprint),
            ).fetchone()
            if device is None:
                device_created = True
                device_id = _id("wdev")
                conn.execute(
                    """INSERT INTO wps_devices
                       (id,user_id,fingerprint_hash,device_name,platform,app_version,status,created_at,last_seen_at,last_ip)
                       VALUES (?,?,?,?,?,?,'active',?,?,?)""",
                    (device_id, user["id"], fingerprint, device_data["device_name"], device_data["platform"], device_data["app_version"], now, now, client_ip[:80]),
                )
                device_status = "active"
            else:
                device_id = device["id"]
                device_status = device["status"]
                if device_status != "active":
                    raise WpsServiceError("DEVICE_DISABLED", "当前设备已停用", 403)
                conn.execute(
                    """UPDATE wps_devices SET device_name=?,platform=?,app_version=?,last_seen_at=?,last_ip=?
                       WHERE id=?""",
                    (device_data["device_name"], device_data["platform"], device_data["app_version"], now, client_ip[:80], device_id),
                )
            updates = "password_hash=?,updated_at=?,last_login_at=?" if needs_rehash else "updated_at=?,last_login_at=?"
            params = (updated_password_hash, now, now, user["id"]) if needs_rehash else (now, now, user["id"])
            conn.execute(f"UPDATE wps_users SET {updates} WHERE id=?", params)
            session = create_session_in_connection(
                conn, user["id"], device_id, client_ip, device_data["app_version"], now
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    LOGGER.info("wps.auth.login.completed | user_id=%s device_id=%s", user["id"][:12], device_id[:12])
    if device_created:
        LOGGER.info("wps.device.created | user_id=%s device_id=%s", user["id"][:12], device_id[:12])
    LOGGER.info("wps.device.online | user_id=%s device_id=%s", user["id"][:12], device_id[:12])
    LOGGER.info("wps.auth.session.created | user_id=%s device_id=%s", user["id"][:12], device_id[:12])
    return _session_response(
        {"id": user["id"], "username": user["username"], "status": "active"},
        {"id": device_id, "device_name": device_data["device_name"], "platform": device_data["platform"], "status": device_status},
        session,
        config_version,
        notifications=list_pending_notifications(
            user["id"],
            connect_func=connect_func,
            sql_lock=sql_lock,
        ),
    )


def current_user(principal, *, config_version) -> dict:
    return {
        "user": {"id": principal["user_id"], "username": principal["username"], "status": principal["user_status"]},
        "device": {"id": principal["device_id"], "device_name": principal["device_name"], "platform": principal["platform"], "status": principal["device_status"], "app_version": principal["app_version"]},
        "session_created_at": principal["created_at"],
        "session_expires_at": principal["expires_at"],
        "features": public_feature_manifest(),
        "config_version": config_version,
        "heartbeat_interval_seconds": WPS_HEARTBEAT_INTERVAL_SECONDS,
    }


def logout_user(principal, *, connect_func, sql_lock) -> dict:
    with sql_lock:
        conn = connect_func()
        try:
            conn.execute("DELETE FROM wps_sessions WHERE session_hash=?", (principal["session_hash"],))
            conn.commit()
        finally:
            conn.close()
    LOGGER.info(
        "wps.auth.session.deleted | user_id=%s device_id=%s",
        principal["user_id"][:12],
        principal["device_id"][:12],
    )
    return {"logged_out": True}


def heartbeat(principal, payload, *, connect_func, sql_lock, client_ip, now_func, config_version) -> dict:
    require_object_fields(payload, required=("device_id", "app_version"))
    if payload["device_id"] != principal["device_id"]:
        raise WpsServiceError("DEVICE_MISMATCH", "请求设备与登录设备不一致", 403)
    app_version = validate_app_version(payload["app_version"])
    now = int(now_func())
    was_offline = principal["device_last_seen_at"] < now - WPS_OFFLINE_AFTER_SECONDS
    with sql_lock:
        conn = connect_func()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE wps_sessions SET last_seen_at=?,app_version=? WHERE session_hash=?", (now, app_version, principal["session_hash"]))
            conn.execute("UPDATE wps_devices SET last_seen_at=?,last_ip=?,app_version=? WHERE id=?", (now, client_ip[:80], app_version, principal["device_id"]))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    if was_offline:
        LOGGER.info(
            "wps.device.online | user_id=%s device_id=%s",
            principal["user_id"][:12],
            principal["device_id"][:12],
        )
    return {
        "account_status": "active",
        "device_status": "active",
        "session_expires_at": principal["expires_at"],
        "heartbeat_interval_seconds": WPS_HEARTBEAT_INTERVAL_SECONDS,
        "features": public_feature_manifest(),
        "config_version": config_version,
        "notifications": list_pending_notifications(
            principal["user_id"],
            connect_func=connect_func,
            sql_lock=sql_lock,
        ),
    }


def acknowledge_notifications(
    principal,
    payload,
    *,
    connect_func,
    sql_lock,
    now_func,
) -> dict:
    """Acknowledge a bounded notification batch for the authenticated account only."""
    require_object_fields(payload, required=("notification_ids",))
    notification_ids = validate_notification_ids(payload["notification_ids"])
    now = int(now_func())
    with sql_lock:
        conn = connect_func()
        try:
            placeholders = ",".join("?" for _ in notification_ids)
            rows = conn.execute(
                f"""SELECT notification_id FROM wps_notifications
                    WHERE user_id=? AND acknowledged_at=0
                    AND notification_id IN ({placeholders})""",
                (principal["user_id"], *notification_ids),
            ).fetchall()
            existing = {str(row["notification_id"]) for row in rows}
            acknowledged_ids = [item for item in notification_ids if item in existing]
            if acknowledged_ids:
                update_placeholders = ",".join("?" for _ in acknowledged_ids)
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    f"""UPDATE wps_notifications SET acknowledged_at=?
                        WHERE user_id=? AND acknowledged_at=0
                        AND notification_id IN ({update_placeholders})""",
                    (now, principal["user_id"], *acknowledged_ids),
                )
                conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()
    LOGGER.info(
        "wps.notification.acknowledge.completed | user_id=%s acknowledged_count=%s",
        principal["user_id"][:12],
        len(acknowledged_ids),
    )
    return {"acknowledged_notification_ids": acknowledged_ids}


def authorize_format(principal, payload, *, connect_func, sql_lock, format_profile, now_func) -> dict:
    require_object_fields(payload, required=("request_id", "command", "app_version"))
    request_id = validate_request_id(payload["request_id"])
    command = payload["command"]
    if command not in WPS_CONTROLLED_COMMANDS:
        raise WpsServiceError("COMMAND_NOT_ALLOWED", "当前功能未获授权", 403)
    app_version = validate_app_version(payload["app_version"])
    if not isinstance(format_profile, dict) or not isinstance(format_profile.get("format_config"), dict):
        raise WpsServiceError("FORMAT_CONFIG_UNAVAILABLE", "正式排版配置暂不可用", 503)
    now = int(now_func())
    reused = False
    response_config_version = str(format_profile["config_version"])
    with sql_lock:
        conn = connect_func()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM wps_format_requests WHERE request_id=?", (request_id,)).fetchone()
            if row is None:
                conn.execute(
                    """INSERT INTO wps_format_requests
                       (request_id,user_id,device_id,command,status,config_version,requested_at,app_version)
                       VALUES (?,?,?,?,'authorized',?,?,?)""",
                    (request_id, principal["user_id"], principal["device_id"], command, format_profile["config_version"], now, app_version),
                )
                request_status = "authorized"
            else:
                if row["user_id"] != principal["user_id"] or row["device_id"] != principal["device_id"] or row["command"] != command:
                    raise WpsServiceError("REQUEST_ID_CONFLICT", "排版请求编号已被其他请求使用", 409)
                reused = True
                request_status = row["status"]
                response_config_version = str(row["config_version"])
                if request_status == "authorized" and response_config_version != str(format_profile["config_version"]):
                    raise WpsServiceError(
                        "FORMAT_CONFIG_VERSION_CHANGED",
                        "排版配置版本已更新，请重新发起请求",
                        409,
                    )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    allowed = request_status == "authorized"
    LOGGER.info(
        "wps.format.authorize.%s | request_id=%s user_id=%s device_id=%s request_status=%s",
        "reused" if reused else "allowed",
        request_id[:16],
        principal["user_id"][:12],
        principal["device_id"][:12],
        request_status,
    )
    if allowed:
        LOGGER.info(
            "wps.format_config.returned | request_id=%s config_version=%s",
            request_id[:16],
            response_config_version[:80],
        )
    return {
        "allowed": allowed,
        "reused": reused,
        "request_id": request_id,
        "command": command,
        "request_status": request_status,
        "config_version": response_config_version,
        "format_config": deepcopy(format_profile["format_config"]) if allowed else None,
    }


def record_format_result(principal, payload, *, connect_func, sql_lock, now_func) -> dict:
    require_object_fields(payload, required=("request_id", "status", "duration_ms", "error_code", "app_version"))
    request_id = validate_request_id(payload["request_id"])
    status = payload["status"]
    if status not in {"success", "failed"}:
        raise WpsValidationError("REQUEST_STATUS_INVALID", "排版结果状态无效")
    duration_ms = payload["duration_ms"]
    if isinstance(duration_ms, bool) or not isinstance(duration_ms, int) or not 0 <= duration_ms <= 24 * 60 * 60 * 1000:
        raise WpsValidationError("DURATION_INVALID", "执行耗时无效")
    error_code = validate_error_code(payload["error_code"])
    validate_app_version(payload["app_version"])
    if status == "success" and error_code:
        raise WpsValidationError("ERROR_CODE_INVALID", "成功结果不能包含错误代码")
    if status == "failed" and not error_code:
        raise WpsValidationError("ERROR_CODE_INVALID", "失败结果必须包含错误代码")
    now = int(now_func())
    with sql_lock:
        conn = connect_func()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM wps_format_requests WHERE request_id=?", (request_id,)).fetchone()
            if row is None:
                raise WpsServiceError("FORMAT_REQUEST_NOT_FOUND", "排版请求不存在", 404)
            if row["user_id"] != principal["user_id"] or row["device_id"] != principal["device_id"]:
                raise WpsServiceError("REQUEST_ID_CONFLICT", "排版请求不属于当前账号或设备", 409)
            if row["status"] in {"success", "failed"}:
                if row["status"] != status or row["error_code"] != error_code:
                    raise WpsServiceError("REQUEST_STATUS_CONFLICT", "排版结果与已有状态冲突", 409)
                reused = True
            else:
                conn.execute(
                    """UPDATE wps_format_requests
                       SET status=?,finished_at=?,duration_ms=?,error_code=?,app_version=?
                       WHERE request_id=?""",
                    (status, now, duration_ms, error_code, payload["app_version"], request_id),
                )
                reused = False
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    LOGGER.info(
        "wps.format.result.%s | request_id=%s user_id=%s device_id=%s request_status=%s",
        "reused" if reused else "completed",
        request_id[:16],
        principal["user_id"][:12],
        principal["device_id"][:12],
        status,
    )
    return {"request_id": request_id, "status": status, "reused": reused}
