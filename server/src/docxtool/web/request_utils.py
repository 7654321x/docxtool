"""Small HTTP request/response helpers shared by the Web compatibility app."""

from __future__ import annotations

import html
import json
from typing import Any
from urllib.parse import parse_qs


def error_payload(code: str, message: str, field: str = "", reason: str = "") -> dict:
    """Build an API error dict from a stable code, message and optional details."""
    payload = {"error": message, "code": code}
    if field:
        payload["field"] = field
    if reason:
        payload["reason"] = reason
    return payload


def cookie_value(cookie_header: str, name: str) -> str:
    """Read one cookie value from a Cookie header string; return an empty string if absent."""
    for part in str(cookie_header or "").split(";"):
        if "=" not in part:
            continue
        key, value = part.strip().split("=", 1)
        if key == name:
            return value
    return ""


def admin_session_cookie_settings(
    cookie_name: str,
    ttl_seconds: int,
    *,
    secure: bool = False,
    session_placeholder: str = "{session_id}",
) -> str:
    """Return the admin Set-Cookie template from cookie name, max age and secure flag."""
    parts = [
        f"{cookie_name}={session_placeholder}",
        "HttpOnly",
        "Path=/",
        "SameSite=Strict",
        f"Max-Age={int(ttl_seconds)}",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def admin_url(path: str, token: str = "") -> str:
    """Return the admin URL path; token is accepted for legacy callers but not appended."""
    return path


def html_escape(text: object) -> str:
    """Escape arbitrary display text for HTML output and return a safe string."""
    return html.escape(str(text or ""))


def hidden_input(name: str, value: str = "") -> str:
    """Return a hidden HTML input for a non-empty field name/value pair."""
    if not name or not value:
        return ""
    return f'<input type="hidden" name="{html_escape(name)}" value="{html_escape(value)}">'


def csrf_header_value(headers, header_name: str) -> str:
    """Read a CSRF token from headers by configured header name; return empty if missing."""
    return headers.get(header_name, "") if headers else ""


def route_path(path: str) -> str:
    """Normalize a requested path by stripping the public /api prefix used by the Worker."""
    path = path or ""
    return path[4:] if path.startswith("/api/") else path


def prefixed_route_tail(path: str, *prefixes: str) -> str | None:
    """传入请求路径和允许前缀，匹配时返回前缀后的资源 ID，否则返回 None。"""
    path = path or ""
    for prefix in prefixes:
        if path.startswith(prefix):
            return path.split("/", 2)[-1]
    return None


def prefixed_route_last_segment(path: str, *prefixes: str) -> str | None:
    """传入请求路径和允许前缀，匹配时返回最后一段资源 ID，否则返回 None。"""
    path = path or ""
    for prefix in prefixes:
        if path.startswith(prefix):
            return path.split("/")[-1]
    return None


def json_dumps(obj: dict) -> str:
    """Serialize a JSON object with compact separators while preserving Chinese text."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def parse_json_body(body: bytes) -> dict:
    """Decode a UTF-8 JSON request body and require it to be a JSON object."""
    if not body:
        return {}
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("JSON_INVALID: 请求体不是有效的 JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("JSON_INVALID: 请求体必须是 JSON 对象")
    return parsed


def admin_token_from_query(parsed_url: Any) -> str:
    """Read the legacy admin token from a parsed URL query string."""
    return (parse_qs(parsed_url.query).get("token") or [""])[0]
