"""普通用户登录 session、Cookie、principal 和 CSRF 辅助。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import Any, Callable, Mapping

from docxtool.web.request_utils import cookie_value, csrf_header_value


def user_session_hash(token: str) -> str:
    """传入明文 session token，返回用于数据库存储和查询的 SHA-256 哈希。"""
    return hashlib.sha256(str(token).encode("ascii", "ignore")).hexdigest()


def user_cookie_header(
    token: str,
    *,
    cookie_name: str,
    max_age: int,
    secure: bool,
    clear: bool = False,
    persistent: bool = True,
) -> str:
    """传入 token、cookie 配置和清理/持久化开关，返回 Set-Cookie 头内容。"""
    parts = [f"{cookie_name}={'' if clear else token}", "HttpOnly", "Path=/", "SameSite=Lax"]
    if clear:
        parts.append("Max-Age=0")
    elif persistent:
        parts.append(f"Max-Age={max_age}")
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def _random_token(token_bytes: Callable[[int], bytes] | None = None) -> str:
    """传入可选随机字节生成器，返回 URL 安全的无填充 token 字符串。"""
    random_bytes = token_bytes or os.urandom
    return base64.urlsafe_b64encode(random_bytes(32)).decode("ascii").rstrip("=")


def create_user_session(
    user_id: str,
    user_agent: str = "",
    remote_ip: str = "",
    *,
    connect: Callable[[], Any],
    sql_lock,
    max_age: int,
    now_func: Callable[[], int],
    token_bytes: Callable[[int], bytes] | None = None,
) -> dict:
    """传入用户 ID、请求信息和数据库依赖，创建用户 session 并返回 token/CSRF/过期时间。"""
    token = _random_token(token_bytes)
    csrf_token = _random_token(token_bytes)
    now = int(now_func())
    expires = now + max_age
    with sql_lock:
        conn = connect()
        try:
            conn.execute("DELETE FROM user_sessions WHERE expires_at <= ?", (now,))
            conn.execute(
                """INSERT INTO user_sessions
                   (session_hash,user_id,csrf_token,created_at,last_seen_at,expires_at,user_agent,remote_ip)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (user_session_hash(token), user_id, csrf_token, now, now, expires, user_agent[:300], remote_ip[:80]),
            )
            conn.commit()
        finally:
            conn.close()
    return {"token": token, "csrf_token": csrf_token, "expires_at": expires}


def user_session_from_headers(
    headers: Mapping[str, str] | None,
    *,
    cookie_name: str,
    connect: Callable[[], Any],
    sql_lock,
    refresh_seconds: int,
    now_func: Callable[[], int],
) -> dict:
    """传入请求头和数据库依赖，返回已认证用户 session；无效或过期时返回空字典。"""
    token = cookie_value(headers.get("Cookie", "") if headers else "", cookie_name)
    if not token or len(token) < 32:
        return {}
    now = int(now_func())
    session_hash = user_session_hash(token)
    with sql_lock:
        conn = connect()
        try:
            row = conn.execute(
                """SELECT s.*, u.username, u.display_name, u.status
                   FROM user_sessions s
                   JOIN users u ON u.id=s.user_id
                   WHERE s.session_hash=? AND s.expires_at>?""",
                (session_hash, now),
            ).fetchone()
            if not row or row["status"] != "active":
                conn.execute("DELETE FROM user_sessions WHERE session_hash=?", (session_hash,))
                conn.commit()
            if row and row["status"] == "active" and now - int(row["last_seen_at"] or 0) >= refresh_seconds:
                conn.execute("UPDATE user_sessions SET last_seen_at=? WHERE session_hash=?", (now, session_hash))
                conn.commit()
        finally:
            conn.close()
    if not row or row["status"] != "active":
        return {}
    return {
        "user_id": row["user_id"],
        "owner_id": row["user_id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "csrf_token": row["csrf_token"],
        "token": token,
        "expires_at": row["expires_at"],
    }


def delete_user_session(
    headers: Mapping[str, str] | None,
    *,
    cookie_name: str,
    connect: Callable[[], Any],
    sql_lock,
    refresh_seconds: int,
    now_func: Callable[[], int],
) -> None:
    """传入请求头和数据库依赖，删除当前用户 session，无返回值。"""
    session = user_session_from_headers(
        headers,
        cookie_name=cookie_name,
        connect=connect,
        sql_lock=sql_lock,
        refresh_seconds=refresh_seconds,
        now_func=now_func,
    )
    if not session:
        return
    with sql_lock:
        conn = connect()
        try:
            conn.execute("DELETE FROM user_sessions WHERE session_hash=?", (user_session_hash(session["token"]),))
            conn.commit()
        finally:
            conn.close()


def principal_from_headers(
    headers: Mapping[str, str] | None,
    *,
    user_cookie_name: str,
    anonymous_cookie_name: str,
    get_user_session: Callable[[Mapping[str, str] | None], dict],
    get_anonymous_user: Callable[[Mapping[str, str] | None, str], tuple[dict, str]],
) -> dict:
    """传入请求头和身份解析函数，返回统一 principal 字典供路由鉴权和 owner 隔离使用。"""
    cookie_header = headers.get("Cookie", "") if headers else ""
    had_user_session_cookie = bool(cookie_value(cookie_header, user_cookie_name))
    session = get_user_session(headers)
    if session:
        return {"owner_id": session["user_id"], "authenticated": True, "invalid_user_session": False, **session}
    identity, cookie = get_anonymous_user(headers, cookie_header)
    return {
        "owner_id": identity["owner_id"],
        "authenticated": False,
        "user_id": None,
        "username": None,
        "display_name": None,
        "csrf_token": None,
        "cookie": cookie,
        "invalid_user_session": had_user_session_cookie,
        "has_identity_cookie": bool(
            cookie_value(cookie_header, user_cookie_name) or cookie_value(cookie_header, anonymous_cookie_name)
        ),
    }


def auth_origin_allowed(headers: Mapping[str, str] | None, origin_allowed: Callable[[Mapping[str, str] | None], bool]) -> bool:
    """传入请求头和来源校验函数，返回认证接口 Origin 是否允许。"""
    return origin_allowed(headers)


def auth_csrf_allowed(
    headers: Mapping[str, str] | None,
    principal: Mapping[str, Any],
    *,
    csrf_header_name: str,
) -> bool:
    """传入请求头、principal 和 CSRF 头名，返回已登录用户 CSRF 是否通过。"""
    if not principal.get("authenticated"):
        return False
    value = csrf_header_value(headers, csrf_header_name)
    return bool(value and hmac.compare_digest(value, str(principal.get("csrf_token", ""))))
