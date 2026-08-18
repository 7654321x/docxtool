"""Bearer session and device identity helpers for the WPS API."""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
from typing import Callable, Mapping

from .config import WPS_SESSION_TTL_SECONDS

LOGGER = logging.getLogger("docx_tool")
_SESSION_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")


class WpsAuthError(RuntimeError):
    def __init__(self, code: str, message: str, status: int) -> None:
        self.code = code
        self.message = message
        self.status = status
        super().__init__(code)


def _random_token(token_bytes=None) -> str:
    random_bytes = token_bytes or os.urandom
    return base64.urlsafe_b64encode(random_bytes(32)).decode("ascii").rstrip("=")


def session_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def device_fingerprint_hash(device_key: str) -> str:
    return hashlib.sha256(device_key.encode("utf-8")).hexdigest()


def bearer_token(headers: Mapping[str, str]) -> str:
    value = headers.get("Authorization", "")
    if not value.startswith("Bearer "):
        raise WpsAuthError("SESSION_REQUIRED", "请先登录", 401)
    token = value[7:]
    if not _SESSION_TOKEN_RE.fullmatch(token):
        raise WpsAuthError("SESSION_REQUIRED", "请先登录", 401)
    return token


def create_session_in_connection(
    conn,
    user_id: str,
    device_id: str,
    remote_ip: str,
    app_version: str,
    now: int,
    token_bytes=None,
) -> dict:
    token = _random_token(token_bytes)
    expires_at = now + WPS_SESSION_TTL_SECONDS
    conn.execute(
        """INSERT INTO wps_sessions
           (session_hash,user_id,device_id,created_at,last_seen_at,expires_at,remote_ip,app_version)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            session_hash(token),
            user_id,
            device_id,
            now,
            now,
            expires_at,
            remote_ip[:80],
            app_version,
        ),
    )
    return {"token": token, "created_at": now, "expires_at": expires_at}


def authenticated_session(
    headers,
    *,
    connect_func: Callable,
    sql_lock,
    now_func: Callable[[], int],
) -> dict:
    token = bearer_token(headers)
    now = int(now_func())
    token_digest = session_hash(token)
    with sql_lock:
        conn = connect_func()
        try:
            row = conn.execute(
                """SELECT s.*, u.username, u.status AS user_status,
                          d.device_name, d.platform, d.status AS device_status,
                          d.last_seen_at AS device_last_seen_at
                   FROM wps_sessions s
                   JOIN wps_users u ON u.id=s.user_id
                   JOIN wps_devices d ON d.id=s.device_id
                   WHERE s.session_hash=?""",
                (token_digest,),
            ).fetchone()
            if row is None:
                raise WpsAuthError("SESSION_INVALID", "登录状态无效，请重新登录", 401)
            if int(row["expires_at"]) <= now:
                conn.execute("DELETE FROM wps_sessions WHERE session_hash=?", (token_digest,))
                conn.commit()
                LOGGER.warning(
                    "wps.auth.session.expired | user_id=%s device_id=%s",
                    row["user_id"][:12],
                    row["device_id"][:12],
                )
                raise WpsAuthError("SESSION_EXPIRED", "登录已过期，请重新登录", 401)
            if row["user_status"] != "active":
                raise WpsAuthError("ACCOUNT_DISABLED", "账号已停用", 403)
            if row["device_status"] != "active":
                raise WpsAuthError("DEVICE_DISABLED", "当前设备已停用", 403)
        finally:
            conn.close()
    return {
        "session_hash": token_digest,
        "user_id": row["user_id"],
        "device_id": row["device_id"],
        "username": row["username"],
        "user_status": row["user_status"],
        "device_name": row["device_name"],
        "platform": row["platform"],
        "device_status": row["device_status"],
        "device_last_seen_at": int(row["device_last_seen_at"]),
        "app_version": row["app_version"],
        "created_at": int(row["created_at"]),
        "expires_at": int(row["expires_at"]),
    }
