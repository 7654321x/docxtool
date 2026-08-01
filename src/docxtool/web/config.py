"""Web runtime configuration helpers.

This module contains pure parsing and header helpers only.  It does not read
request bodies, mutate global app state, or touch the database.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from urllib.parse import urlparse


def parse_bool(value: object, default: bool = True) -> bool:
    """传入任意配置值，返回布尔解析结果；无法识别时返回默认值。"""
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def parse_int_env(name: str, default: int, environ: Mapping[str, str] | None = None) -> int:
    """传入环境变量名和默认整数，返回解析后的整数配置。"""
    source = os.environ if environ is None else environ
    try:
        return int(source.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def is_local_origin_host(hostname: str | None) -> bool:
    """传入 URL 主机名，返回它是否属于本机调试来源。"""
    return hostname in {"localhost", "127.0.0.1", "::1"}


def parse_frontend_origin(value: str, production_mode: bool = False) -> str:
    """传入 FRONTEND_ORIGIN 原始值，返回规范化后的 origin。"""
    raw = str(value or "").strip()
    if not raw:
        return ""

    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("FRONTEND_ORIGIN must use http or https")
    if not parsed.hostname:
        raise ValueError("FRONTEND_ORIGIN must include host")
    if parsed.username or parsed.password:
        raise ValueError("FRONTEND_ORIGIN must not include username or password")
    if parsed.query:
        raise ValueError("FRONTEND_ORIGIN must not include query")
    if parsed.fragment:
        raise ValueError("FRONTEND_ORIGIN must not include fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("FRONTEND_ORIGIN must not include path")
    if production_mode and parsed.scheme != "https" and not is_local_origin_host(parsed.hostname):
        raise ValueError("FRONTEND_ORIGIN must use https in production")

    normalized = f"{parsed.scheme}://{parsed.netloc}"
    return normalized.rstrip("/")


def resolve_cookie_secure(
    origin: str,
    explicit_value: str | None = None,
    production_mode: bool = False,
) -> bool:
    """传入前端 origin 和显式配置，返回 Cookie 是否应设置 Secure。"""
    if explicit_value is None or str(explicit_value).strip() == "":
        return str(origin or "").startswith("https://")

    secure = parse_bool(explicit_value, False)
    if production_mode and str(origin or "").startswith("https://") and not secure:
        raise ValueError("COOKIE_SECURE=false is not allowed with HTTPS FRONTEND_ORIGIN in production")
    return secure


def cors_headers_for_request(origin_header: str, frontend_origin: str = "") -> dict[str, str]:
    """传入请求 Origin 和配置 origin，返回允许的 CORS 响应头。"""
    origin = str(origin_header or "").strip()
    configured_origin = str(frontend_origin or "").strip()
    allow_origin = ""

    if configured_origin:
        if origin == configured_origin:
            allow_origin = configured_origin
    elif origin:
        parsed = urlparse(origin)
        if parsed.scheme in {"http", "https"} and is_local_origin_host(parsed.hostname):
            allow_origin = origin.rstrip("/")

    if not allow_origin:
        return {}

    return {
        "Access-Control-Allow-Origin": allow_origin,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": (
            "Content-Type, X-Filename, X-Proxy-Secret, X-Docxtool-Proxy, "
            "X-Preset-Id, X-Preset-Name, X-Template-Type, X-Processing-Mode, "
            "X-Format-Config, X-Format-Config-Encoding, X-CSRF-Token"
        ),
        "Access-Control-Max-Age": "86400",
    }
