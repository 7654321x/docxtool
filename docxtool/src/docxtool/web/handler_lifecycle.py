"""HTTP handler 生命周期辅助。

本模块只负责 CORS/安全响应头发送、OPTIONS 响应和 HTTP 方法入口分派，不处理具体
业务路由、不访问数据库，也不触碰 DOCX 识别或渲染链路。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse


def send_security_headers(handler, *, security_headers: Callable[[], list[tuple[str, str]]]) -> None:
    """传入 handler 和安全头构造回调，逐项发送安全响应头并返回 None。"""
    for key, value in security_headers():
        handler.send_header(key, value)


def send_cors_headers(handler, *, cors_headers_for_origin: Callable[[str], dict[str, str]]) -> None:
    """传入 handler 和 CORS 构造回调，根据 Origin 发送 CORS 响应头。"""
    for key, value in cors_headers_for_origin(handler.headers.get("Origin", "")).items():
        handler.send_header(key, value)


def handle_options(handler, *, cors_headers: Callable[[], None], security_headers: Callable[[], None]) -> None:
    """传入 handler、CORS 头回调和安全头回调，发送 OPTIONS 204 响应。"""
    handler.send_response(204)
    cors_headers()
    security_headers()
    handler.end_headers()


def dispatch_http_method(
    handler,
    *,
    route_path: Callable[[str], str],
    dispatch: Callable[[Any, Any, str], None],
    authorize: Callable[[str], bool],
) -> None:
    """传入 handler、路径规范化、网关鉴权和分派回调，解析后按顺序执行。"""
    parsed = urlparse(handler.path)
    path = route_path(parsed.path)
    if not authorize(path):
        return
    dispatch(handler, parsed, path)
