"""Anonymous owner identity helpers used before a user logs in."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import uuid
from typing import Callable, Mapping
from urllib.parse import urlparse

from docxtool.web.request_utils import cookie_value


def anonymous_user_signing_key(proxy_secret: str, default_proxy_secret: str) -> bytes:
    """传入当前代理密钥和默认密钥，返回匿名用户 cookie 签名用派生密钥。"""
    secret = (proxy_secret or default_proxy_secret).encode("utf-8")
    return hmac.new(secret, b"docxtool-anonymous-user-v1", hashlib.sha256).digest()


def anonymous_user_signature(payload: str, *, proxy_secret: str, default_proxy_secret: str) -> str:
    """传入待签名 payload 和密钥配置，返回 URL 安全的 HMAC-SHA256 签名。"""
    digest = hmac.new(
        anonymous_user_signing_key(proxy_secret, default_proxy_secret),
        payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def create_anonymous_user(
    now: int,
    *,
    max_age: int,
    proxy_secret: str,
    default_proxy_secret: str,
    owner_id: str | None = None,
) -> dict:
    """传入当前时间、过期秒数和密钥配置，返回新的匿名 owner 身份字典。"""
    issued_at = int(now)
    generated_owner_id = owner_id or f"usr_{uuid.uuid4().hex}"
    payload = f"v1.{issued_at}.{generated_owner_id}"
    token = f"{payload}.{anonymous_user_signature(payload, proxy_secret=proxy_secret, default_proxy_secret=default_proxy_secret)}"
    return {
        "owner_id": generated_owner_id,
        "token": token,
        "issued_at": issued_at,
        "expires_at": issued_at + max_age,
    }


def parse_anonymous_user(
    token: str,
    now: int,
    *,
    max_age: int,
    proxy_secret: str,
    default_proxy_secret: str,
) -> dict:
    """传入匿名 cookie token、当前时间和密钥配置，校验通过时返回身份字典。"""
    parts = str(token or "").strip().split(".")
    if len(parts) != 4 or parts[0] != "v1":
        return {}
    version, issued_raw, owner_id, signature = parts
    if not re.fullmatch(r"usr_[0-9a-f]{32}", owner_id):
        return {}
    try:
        issued_at = int(issued_raw)
    except (TypeError, ValueError):
        return {}
    current = int(now)
    if issued_at > current + 300 or current - issued_at > max_age:
        return {}
    payload = f"{version}.{issued_at}.{owner_id}"
    expected = anonymous_user_signature(payload, proxy_secret=proxy_secret, default_proxy_secret=default_proxy_secret)
    if not signature or not hmac.compare_digest(signature, expected):
        return {}
    return {
        "owner_id": owner_id,
        "token": token,
        "issued_at": issued_at,
        "expires_at": issued_at + max_age,
    }


def anonymous_user_cookie_header(token: str, *, cookie_name: str, max_age: int, secure: bool) -> str:
    """传入 token、cookie 名、有效期和 Secure 开关，返回 Set-Cookie 头内容。"""
    parts = [
        f"{cookie_name}={token}",
        "HttpOnly",
        "Path=/",
        "SameSite=Lax",
        f"Max-Age={max_age}",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def anonymous_user_cookie_clear_header(*, cookie_name: str, secure: bool) -> str:
    """传入 cookie 名和 Secure 开关，返回清除匿名身份 cookie 的 Set-Cookie 头。"""
    parts = [f"{cookie_name}=", "HttpOnly", "Path=/", "SameSite=Lax", "Max-Age=0"]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def anonymous_user_from_headers(
    headers: Mapping[str, str] | None,
    cookie_header: str = "",
    *,
    cookie_name: str,
    max_age: int,
    proxy_secret: str,
    default_proxy_secret: str,
    now: Callable[[], int],
    secure: bool,
) -> tuple[dict, str]:
    """传入请求头和 cookie 配置，返回匿名身份以及必要时的新 Set-Cookie 头。"""
    token = cookie_value(cookie_header, cookie_name)
    if not token and headers:
        token = cookie_value(str(headers.get("Cookie", "")), cookie_name)
    current = int(now())
    identity = parse_anonymous_user(
        token,
        current,
        max_age=max_age,
        proxy_secret=proxy_secret,
        default_proxy_secret=default_proxy_secret,
    )
    if identity:
        return identity, ""
    identity = create_anonymous_user(
        current,
        max_age=max_age,
        proxy_secret=proxy_secret,
        default_proxy_secret=default_proxy_secret,
    )
    return identity, anonymous_user_cookie_header(identity["token"], cookie_name=cookie_name, max_age=max_age, secure=secure)


def anonymous_template_origin_allowed(
    headers: Mapping[str, str] | None,
    *,
    frontend_origin: str,
    is_local_origin_host: Callable[[str], bool],
) -> bool:
    """传入请求头、前端来源配置和本地域名判断器，返回匿名模板请求来源是否可信。"""
    origin = str(headers.get("Origin", "") if headers else "").strip().rstrip("/")
    if not origin:
        return False
    if frontend_origin:
        return hmac.compare_digest(origin, frontend_origin)
    parsed = urlparse(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    request_host = str(headers.get("Host", "") if headers else "").strip().lower()
    if request_host and parsed.netloc.lower() == request_host:
        return True
    return is_local_origin_host(parsed.hostname)
