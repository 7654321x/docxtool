"""Pure response payload helpers for user authentication routes."""

from __future__ import annotations

from typing import Mapping


def is_json_content_type(headers: Mapping[str, str] | None) -> bool:
    """传入请求头，返回 Content-Type 是否为 application/json。"""
    content_type = ((headers or {}).get("Content-Type", "") or "").split(";", 1)[0].strip().lower()
    return content_type == "application/json"


def auth_json_request_error(origin_allowed: bool, headers: Mapping[str, str] | None) -> tuple[str, str, int] | None:
    """传入来源校验结果和请求头，返回认证 JSON 请求错误三元组或 None。"""
    if not origin_allowed:
        return "ORIGIN_INVALID", "请求来源不被允许", 403
    if not is_json_content_type(headers):
        return "CONTENT_TYPE_INVALID", "请求必须使用 application/json", 415
    return None


def auth_validation_error_from_exception(exc: ValueError, *, status: int = 400) -> tuple[str, str, int]:
    """传入认证字段校验异常，返回稳定错误码、提示文本和 HTTP 状态码。"""
    raw = str(exc)
    code, message = raw.split(":", 1) if ":" in raw else ("VALIDATION_ERROR", raw)
    return code.strip() or "VALIDATION_ERROR", message.strip(), status


def auth_register_error_from_exception(exc: BaseException) -> tuple[str, str, int]:
    """传入注册持久化异常，返回对外稳定的错误码、提示文本和 HTTP 状态码。"""
    if "UNIQUE constraint" in str(exc):
        return "USERNAME_TAKEN", "用户名已存在", 409
    return "REGISTER_FAILED", "注册失败", 500


def auth_register_rate_limit_error(allowed: bool, retry_after: int) -> tuple[str, str, int, int] | None:
    """传入注册限流结果，返回注册限流错误字段或 None。"""
    if allowed:
        return None
    return "RATE_LIMITED", "注册请求过于频繁，请稍后再试", 429, retry_after


def auth_login_rate_limit_error(
    ip_allowed: bool,
    ip_retry_after: int,
    name_allowed: bool,
    name_retry_after: int,
) -> tuple[str, str, int, int] | None:
    """传入 IP 和用户名限流结果，返回登录限流错误字段或 None。"""
    if ip_allowed and name_allowed:
        return None
    return "RATE_LIMITED", "登录请求过于频繁，请稍后再试", 429, max(ip_retry_after, name_retry_after)


def auth_invalid_credentials_error() -> tuple[str, str, int]:
    """无需传入数据，返回用户名或密码错误的稳定错误字段。"""
    return "INVALID_CREDENTIALS", "用户名或密码错误", 401


def auth_account_disabled_error() -> tuple[str, str, int]:
    """无需传入数据，返回账号停用的稳定错误字段。"""
    return "ACCOUNT_DISABLED", "账号已停用", 403


def public_user_data(user_id: object, username: object, display_name: object = "") -> dict:
    """传入用户 ID、用户名和显示名，返回对外 API 使用的用户字典。"""
    return {"id": str(user_id), "username": str(username), "display_name": str(display_name or "")}


def auth_success_data(user_id: object, username: object, display_name: object, csrf_token: object) -> dict:
    """传入用户字段和 CSRF token，返回登录或注册成功的 data 字典。"""
    return {"user": public_user_data(user_id, username, display_name), "csrf_token": str(csrf_token or "")}


def ok_data_response(data: object) -> dict:
    """传入 API data 对象，返回认证接口统一 ok=true 响应体。"""
    return {"ok": True, "data": data}


def auth_success_response(user_id: object, username: object, display_name: object, csrf_token: object) -> dict:
    """传入用户字段和 CSRF token，返回登录或注册成功的完整响应体。"""
    return ok_data_response(auth_success_data(user_id, username, display_name, csrf_token))


def auth_session_extra_headers(user_cookie_header: str, anonymous_clear_cookie_header: str = "") -> list[tuple[str, str]]:
    """传入用户 Cookie 和可选匿名清理 Cookie，返回登录或注册成功附加响应头。"""
    headers = [("Set-Cookie", user_cookie_header)]
    if anonymous_clear_cookie_header:
        headers.append(("Set-Cookie", anonymous_clear_cookie_header))
    return headers


def auth_logout_response() -> dict:
    """无需传入数据，返回退出登录成功的完整响应体。"""
    return ok_data_response({"logged_out": True})


def auth_logout_request_error(origin_allowed: bool, authenticated: bool, csrf_allowed: bool) -> tuple[str, str, int] | None:
    """传入来源、登录态和 CSRF 校验结果，返回退出登录错误字段或 None。"""
    if not origin_allowed:
        return "ORIGIN_INVALID", "请求来源不被允许", 403
    if authenticated and not csrf_allowed:
        return "CSRF_INVALID", "CSRF 校验失败", 403
    return None


def auth_logout_extra_headers(clear_user_cookie_header: str) -> list[tuple[str, str]]:
    """传入清除用户 Cookie 的 Set-Cookie 值，返回退出登录附加响应头。"""
    return [("Set-Cookie", clear_user_cookie_header)]


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
