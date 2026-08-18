"""Web runtime configuration helpers.

This module contains pure parsing and header helpers only.  It does not read
request bodies, mutate global app state, or touch the database.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from urllib.parse import urlparse


DEFAULT_PUBLIC_FRONTEND_ORIGIN = "https://docx.toolpp.cn"
DEFAULT_ADMIN_CONSOLE_ORIGIN = DEFAULT_PUBLIC_FRONTEND_ORIGIN


def parse_bool(value: object, default: bool = True) -> bool:
    """传入任意配置值，返回布尔解析结果；无法识别时返回默认值。"""
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def parse_strict_bool(value: object, name: str) -> bool:
    """解析安全边界布尔配置；无法识别时明确拒绝启动。"""
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError(
        f"{name} must be one of 1, true, yes, on, 0, false, no, or off"
    )


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


def display_frontend_origin(value: str) -> str:
    """传入已校验的前端 Origin，返回启动日志可展示的公网前端地址。"""
    return str(value or "").strip().rstrip("/") or DEFAULT_PUBLIC_FRONTEND_ORIGIN


def parse_admin_console_origin(value: str, production_mode: bool = False) -> str:
    """传入管理入口 Origin，返回规范化后的根地址或默认 Pages 地址。"""
    raw = str(value or "").strip()
    if not raw:
        return DEFAULT_ADMIN_CONSOLE_ORIGIN

    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("ADMIN_CONSOLE_ORIGIN must use http or https")
    if not parsed.hostname:
        raise ValueError("ADMIN_CONSOLE_ORIGIN must include host")
    if parsed.username or parsed.password:
        raise ValueError("ADMIN_CONSOLE_ORIGIN must not include username or password")
    if parsed.query:
        raise ValueError("ADMIN_CONSOLE_ORIGIN must not include query")
    if parsed.fragment:
        raise ValueError("ADMIN_CONSOLE_ORIGIN must not include fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("ADMIN_CONSOLE_ORIGIN must not include path")
    if production_mode and parsed.scheme != "https":
        raise ValueError("ADMIN_CONSOLE_ORIGIN must use https in production")

    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def resolve_admin_cookie_secure(
    admin_console_origin: str,
    explicit_value: str | None,
    default: bool,
    production_mode: bool = False,
) -> bool:
    """根据独立管理入口和显式配置，返回管理员 Cookie 的 Secure 标记。"""
    origin = parse_admin_console_origin(admin_console_origin, production_mode)
    secure = (
        default
        if explicit_value is None or str(explicit_value).strip() == ""
        else parse_strict_bool(explicit_value, "ADMIN_COOKIE_SECURE")
    )
    scheme = urlparse(origin).scheme
    if scheme == "http" and secure:
        raise ValueError("ADMIN_COOKIE_SECURE must be false when ADMIN_CONSOLE_ORIGIN uses http")
    if production_mode and scheme == "https" and not secure:
        raise ValueError("ADMIN_COOKIE_SECURE=false is not allowed with HTTPS ADMIN_CONSOLE_ORIGIN in production")
    return secure


def resolve_cookie_secure(
    origin: str,
    explicit_value: str | None = None,
    production_mode: bool = False,
) -> bool:
    """传入前端 origin 和显式配置，返回 Cookie 是否应设置 Secure。"""
    if explicit_value is None or str(explicit_value).strip() == "":
        return str(origin or "").startswith("https://")

    secure = parse_strict_bool(explicit_value, "COOKIE_SECURE")
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
