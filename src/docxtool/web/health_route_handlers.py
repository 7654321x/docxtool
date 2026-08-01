"""健康检查路由处理辅助。

本模块只负责调用 payload 构造回调并写入 JSON 响应，不读取数据库、不检查目录，也不
触碰 DOCX 识别和渲染链路；实际检查逻辑由调用方注入。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def handle_health(handler, *, health_payload: Callable[[], dict[str, object]]) -> None:
    """传入 HTTP handler 和健康 payload 回调，发送 `/health` JSON 响应。"""
    handler._json(health_payload())


def handle_ready(handler, *, ready_payload: Callable[[], dict[str, object]]) -> None:
    """传入 HTTP handler 和 readiness payload 回调，发送 `/ready` JSON 响应。"""
    payload = ready_payload()
    handler._json(payload, 200 if payload.get("ok") else 503)


def handle_version(handler, *, version_payload: Callable[[], dict[str, Any]]) -> None:
    """传入 HTTP handler 和版本 payload 回调，发送 `/version` JSON 响应。"""
    handler._json(version_payload())
