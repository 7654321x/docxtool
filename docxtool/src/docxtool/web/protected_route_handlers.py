"""受保护路由的鉴权转发辅助。

本模块只负责在调用具体 handler 动作前执行管理员、文件 API 或模板修改鉴权，不直接
读取请求体、不访问数据库，也不处理 DOCX 识别、排版或任务执行。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def handle_admin_route(
    parsed: Any,
    *,
    require_admin: Callable[[Any], bool],
    action: Callable[[Any], None],
) -> None:
    """传入 URL、管理员鉴权回调和动作回调，鉴权通过后执行动作并返回 None。"""
    if not require_admin(parsed):
        return
    action(parsed)


def handle_admin_resource_route(
    parsed: Any,
    resource_id: str,
    *,
    require_admin: Callable[[Any], bool],
    action: Callable[[str], None],
) -> None:
    """传入 URL、资源 ID、管理员鉴权回调和动作回调，通过后处理资源。"""
    if not require_admin(parsed):
        return
    action(resource_id)


def handle_admin_post_route(
    parsed: Any,
    *,
    require_admin_post: Callable[[Any], bool],
    action: Callable[[Any], None],
) -> None:
    """传入 URL、管理员 POST 鉴权回调和动作回调，通过后执行写操作。"""
    if not require_admin_post(parsed):
        return
    action(parsed)


def handle_file_api_route(
    *,
    require_file_api: Callable[[], bool],
    action: Callable[[], None],
) -> None:
    """传入文件 API 鉴权回调和无参动作回调，通过后执行文件接口动作。"""
    if not require_file_api():
        return
    action()


def handle_file_api_resource_route(
    resource_id: str,
    *,
    require_file_api: Callable[[], bool],
    action: Callable[[str], None],
) -> None:
    """传入资源 ID、文件 API 鉴权回调和动作回调，通过后处理文件资源。"""
    if not require_file_api():
        return
    action(resource_id)


def handle_preset_mutation_route(
    parsed: Any,
    *,
    require_preset_mutation: Callable[[Any], bool],
    action: Callable[[], None],
) -> None:
    """传入 URL、模板修改鉴权回调和动作回调，通过后执行模板创建。"""
    if not require_preset_mutation(parsed):
        return
    action()


def handle_preset_resource_mutation_route(
    parsed: Any,
    preset_id: str,
    *,
    require_preset_mutation: Callable[[Any], bool],
    action: Callable[[str], None],
) -> None:
    """传入 URL、模板 ID、模板修改鉴权回调和动作回调，通过后处理模板资源。"""
    if not require_preset_mutation(parsed):
        return
    action(preset_id)
