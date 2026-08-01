"""Pure HTTP response helpers used by the compatibility handler."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any


def normalize_extra_headers(extra_headers: Mapping[str, object] | Iterable[tuple[object, object]] | None) -> list[tuple[str, str]]:
    """传入可选响应头映射或元组序列，返回字符串化后的响应头列表。"""
    if not extra_headers:
        return []
    items = extra_headers.items() if isinstance(extra_headers, Mapping) else extra_headers
    return [(str(key), str(value)) for key, value in items]


def text_response_bytes(body: object) -> bytes:
    """传入文本响应体对象，返回 UTF-8 编码 bytes。"""
    return str(body).encode("utf-8")


def json_response_bytes(obj: Any) -> bytes:
    """传入 JSON 可序列化对象，返回 UTF-8 编码 JSON bytes。"""
    return json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")


def retry_after_headers(retry_after: int = 0) -> list[tuple[str, str]]:
    """传入重试等待秒数，返回 Retry-After 响应头列表。"""
    return [("Retry-After", str(retry_after))] if retry_after else []


def auth_error_body(code: str, message: str, *, field: str = "", reason: str = "") -> dict:
    """传入错误码和提示，返回认证接口统一错误响应体。"""
    error = {"code": code, "message": message}
    if field:
        error["field"] = field
    if reason:
        error["reason"] = reason
    return {"ok": False, "error": error}
