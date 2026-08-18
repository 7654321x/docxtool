"""HTTP handler response writers for the Web compatibility app."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from docxtool.web.responses import (
    json_error_body,
    json_response_bytes,
    json_response_headers,
    redirect_headers,
    retry_after_headers,
    text_response_bytes,
    text_response_headers,
)


def send_redirect_response(
    handler: Any,
    *,
    target: str,
    security_headers: Callable[[], None],
    extra_headers=None,
) -> None:
    """传入 handler、目标地址和响应头回调，发送 303 跳转响应并返回 None。"""
    handler.send_response(303)
    for key, value in redirect_headers(target, extra_headers):
        handler.send_header(key, value)
    security_headers()
    handler.end_headers()


def send_text_response(
    handler: Any,
    *,
    body: str,
    mime: str,
    status: int,
    cors_headers: Callable[[], None],
    security_headers: Callable[[], None],
    extra_headers=None,
) -> None:
    """传入 handler、文本内容和 MIME，发送 UTF-8 文本响应并返回 None。"""
    data = text_response_bytes(body)
    handler.send_response(status)
    for key, value in text_response_headers(mime, len(data), extra_headers):
        handler.send_header(key, value)
    cors_headers()
    security_headers()
    handler.end_headers()
    handler.wfile.write(data)


def send_json_response(
    handler: Any,
    *,
    obj: dict,
    status: int,
    cors_headers: Callable[[], None],
    security_headers: Callable[[], None],
    extra_headers=None,
) -> None:
    """传入 handler、JSON 对象和状态码，发送 JSON 响应并返回 None。"""
    data = json_response_bytes(obj)
    handler.send_response(status)
    for key, value in json_response_headers(len(data), extra_headers):
        handler.send_header(key, value)
    cors_headers()
    security_headers()
    handler.end_headers()
    handler.wfile.write(data)


def send_json_error_response(
    handler: Any,
    *,
    auth_route: bool,
    code: str,
    message: str,
    status: int,
    cors_headers: Callable[[], None],
    security_headers: Callable[[], None],
    legacy_error_body: Callable[..., dict],
    field: str = "",
    reason: str = "",
    retry_after: int = 0,
) -> None:
    """传入错误字段和响应头回调，按认证或旧接口合同发送 JSON 错误响应。"""
    headers = retry_after_headers(retry_after)
    body = json_error_body(
        auth_route=auth_route,
        code=code,
        message=message,
        field=field,
        reason=reason,
        legacy_error_body=legacy_error_body,
    )
    send_json_response(
        handler,
        obj=body,
        status=status,
        cors_headers=cors_headers,
        security_headers=security_headers,
        extra_headers=headers,
    )
