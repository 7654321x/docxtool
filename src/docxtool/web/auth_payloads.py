"""Pure response payload helpers for user authentication routes."""

from __future__ import annotations

from typing import Mapping


def is_json_content_type(headers: Mapping[str, str] | None) -> bool:
    """传入请求头，返回 Content-Type 是否为 application/json。"""
    content_type = ((headers or {}).get("Content-Type", "") or "").split(";", 1)[0].strip().lower()
    return content_type == "application/json"


def public_user_data(user_id: object, username: object, display_name: object = "") -> dict:
    """传入用户 ID、用户名和显示名，返回对外 API 使用的用户字典。"""
    return {"id": str(user_id), "username": str(username), "display_name": str(display_name or "")}


def auth_success_data(user_id: object, username: object, display_name: object, csrf_token: object) -> dict:
    """传入用户字段和 CSRF token，返回登录或注册成功的 data 字典。"""
    return {"user": public_user_data(user_id, username, display_name), "csrf_token": str(csrf_token or "")}


def auth_me_data(principal: Mapping[str, object] | None) -> dict:
    """传入当前 principal 字典，返回 /auth/me 的 data 响应体。"""
    current = principal or {}
    data = {"authenticated": bool(current.get("authenticated")), "user": None, "csrf_token": None}
    if current.get("authenticated"):
        data["user"] = public_user_data(current.get("user_id", ""), current.get("username", ""), current.get("display_name", ""))
        data["csrf_token"] = current.get("csrf_token")
    return data


def auth_me_extra_headers(principal: Mapping[str, object] | None, *, clear_user_cookie_header: str = "") -> list[tuple[str, str]]:
    """传入 principal 和清除 Cookie 头，返回 /auth/me 需要附加的响应头列表。"""
    current = principal or {}
    headers: list[tuple[str, str]] = []
    if current.get("cookie"):
        headers.append(("Set-Cookie", str(current["cookie"])))
    if current.get("invalid_user_session") and clear_user_cookie_header:
        headers.append(("Set-Cookie", clear_user_cookie_header))
    return headers
