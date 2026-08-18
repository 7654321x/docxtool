"""Administrator session and legacy admin-token helpers."""

from __future__ import annotations

import hmac
import time
import uuid
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs

from docxtool.web.request_utils import cookie_value, csrf_header_value


def now_unix(time_func: Callable[[], float] = time.time) -> int:
    """传入可选时间函数，返回当前 Unix 秒级时间戳。"""
    return int(time_func())


def prune_expired_admin_sessions(conn, *, now: int) -> None:
    """传入数据库连接和当前时间，删除过期管理员会话，无返回值。"""
    conn.execute("DELETE FROM admin_sessions WHERE expires_at <= ?", (now,))


def create_admin_session(
    user_agent: str = "",
    remote_ip: str = "",
    *,
    connect: Callable[[], Any],
    sql_lock,
    ttl_seconds: int,
    now_func: Callable[[], int] = now_unix,
    token_hex: Callable[[], str] | None = None,
) -> dict:
    """传入 UA、远端 IP、数据库连接器和 TTL，创建管理员会话并返回 session 字典。"""
    token_factory = token_hex or (lambda: uuid.uuid4().hex)
    session_id = token_factory()
    csrf_token = token_factory() + token_factory()
    now = int(now_func())
    expires_at = now + ttl_seconds
    with sql_lock:
        conn = connect()
        prune_expired_admin_sessions(conn, now=now)
        conn.execute(
            """INSERT INTO admin_sessions
               (session_id, csrf_token, user_agent, remote_ip, created_at, last_seen_at, expires_at)
               VALUES (?,?,?,?,?,?,?)""",
            (session_id, csrf_token, user_agent or "", remote_ip or "", now, now, expires_at),
        )
        conn.commit()
        conn.close()
    return {"session_id": session_id, "csrf_token": csrf_token, "expires_at": expires_at}


def get_admin_session(
    session_id: str,
    *,
    connect: Callable[[], Any],
    sql_lock,
    ttl_seconds: int,
    now_func: Callable[[], int] = now_unix,
) -> dict:
    """传入 session ID、数据库连接器和 TTL，返回已刷新过期时间的管理员会话。"""
    cleaned = str(session_id or "").strip()
    if not cleaned:
        return {}
    with sql_lock:
        conn = connect()
        now = int(now_func())
        prune_expired_admin_sessions(conn, now=now)
        row = conn.execute("SELECT * FROM admin_sessions WHERE session_id=?", (cleaned,)).fetchone()
        if row:
            conn.execute(
                "UPDATE admin_sessions SET last_seen_at=?, expires_at=? WHERE session_id=?",
                (now, now + ttl_seconds, cleaned),
            )
            conn.commit()
        conn.close()
    return dict(row) if row else {}


def delete_admin_session(session_id: str, *, connect: Callable[[], Any], sql_lock) -> None:
    """传入 session ID 和数据库连接器，删除管理员会话，无返回值。"""
    cleaned = str(session_id or "").strip()
    if not cleaned:
        return
    with sql_lock:
        conn = connect()
        conn.execute("DELETE FROM admin_sessions WHERE session_id=?", (cleaned,))
        conn.commit()
        conn.close()


def legacy_admin_token_from(parsed, headers: Mapping[str, str] | None, cookie_header: str = "") -> str:
    """传入 URL 解析结果、请求头和 Cookie 头，返回 legacy 管理员 token。"""
    qs = parse_qs(parsed.query)
    token = (qs.get("token") or [""])[0]
    if token:
        return token
    header_token = headers.get("X-Admin-Token", "") if headers else ""
    if header_token:
        return header_token
    return cookie_value(cookie_header, "admin_token")


def admin_authorized(parsed, headers: Mapping[str, str] | None, cookie_header: str = "", *, admin_token: str) -> bool:
    """传入请求上下文和管理员密钥，返回 legacy token 是否通过。"""
    token = legacy_admin_token_from(parsed, headers, cookie_header)
    return bool(token and hmac.compare_digest(token, admin_token))


def admin_session_from_headers(
    headers: Mapping[str, str] | None,
    cookie_header: str = "",
    *,
    cookie_name: str,
    get_session: Callable[[str], dict],
) -> dict:
    """传入请求头、Cookie 头和查询函数，返回当前管理员会话或空字典。"""
    value = cookie_value(cookie_header, cookie_name)
    if not value and headers:
        value = cookie_value(str(headers.get("Cookie", "")), cookie_name)
    return get_session(value)


def admin_request_context(
    parsed,
    headers: Mapping[str, str] | None,
    cookie_header: str = "",
    *,
    cookie_name: str,
    admin_token: str,
    get_session: Callable[[str], dict],
) -> dict:
    """传入请求上下文、cookie 名和管理员密钥，返回管理员授权上下文字典。"""
    session = admin_session_from_headers(headers, cookie_header, cookie_name=cookie_name, get_session=get_session)
    if session:
        return {"authorized": True, "session": session, "legacy_token": False}
    token = legacy_admin_token_from(parsed, headers, cookie_header)
    if token and hmac.compare_digest(token, admin_token):
        return {"authorized": True, "session": {}, "legacy_token": True}
    return {"authorized": False, "session": {}, "legacy_token": False}


def validate_admin_csrf(
    headers: Mapping[str, str] | None,
    cookie_header: str = "",
    *,
    cookie_name: str,
    csrf_header_name: str,
    get_session: Callable[[str], dict],
) -> bool:
    """传入请求头、Cookie、cookie 名和 CSRF 头名，返回管理员 CSRF 是否通过。"""
    session = admin_session_from_headers(headers, cookie_header, cookie_name=cookie_name, get_session=get_session)
    if not session:
        return False
    value = csrf_header_value(headers, csrf_header_name)
    return bool(value and hmac.compare_digest(value, session.get("csrf_token", "")))
