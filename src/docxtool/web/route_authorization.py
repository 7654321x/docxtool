"""Web 路由鉴权响应辅助。

本模块只负责把管理员、文件 API 和 preset 修改鉴权结果写回 handler 兼容状态，并在失败
时发送原有错误响应；不直接访问数据库、不读取请求流，也不触碰 DOCX 识别或渲染链路。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def set_preset_mutation_context(handler, context: dict[str, object]) -> None:
    """传入 handler 和 preset 上下文，写入旧 handler 属性并返回 None。"""
    handler._preset_owner_id = context["owner_id"]
    handler._preset_cookie_header = context["cookie_header"]
    handler._preset_public_only = context["public_only"]
    handler._preset_admin = context["admin"]


def require_admin(
    handler,
    parsed: Any,
    *,
    admin_request_context: Callable[[Any, Any, str], dict[str, object]],
    unauthorized_error: Callable[[], tuple[str, str, int]],
) -> bool:
    """传入 handler 和 URL，校验管理员权限；成功返回 True，失败发送错误并返回 False。"""
    context = admin_request_context(parsed, handler.headers, handler.headers.get("Cookie", ""))
    handler._admin_context = context
    if context.get("authorized"):
        return True
    handler._json_error_fields(unauthorized_error())
    return False


def require_admin_post(
    handler,
    parsed: Any,
    *,
    admin_request_context: Callable[[Any, Any, str], dict[str, object]],
    unauthorized_error: Callable[[], tuple[str, str, int]],
    request_params: Callable[[Any], dict[str, object]],
    admin_post_csrf_allowed: Callable[[dict[str, object], dict[str, object], Any], bool],
    csrf_invalid_error: Callable[[], tuple[str, str, int]],
) -> bool:
    """传入 handler 和 URL，校验管理员 POST 权限及 CSRF；返回是否允许继续。"""
    context = admin_request_context(parsed, handler.headers, handler.headers.get("Cookie", ""))
    handler._admin_context = context
    if not context.get("authorized"):
        handler._json_error_fields(unauthorized_error())
        return False
    params = request_params(parsed)
    handler._request_params_cache = params
    if not admin_post_csrf_allowed(context, params, handler.headers):
        handler._json_error_fields(csrf_invalid_error())
        return False
    return True


def require_preset_mutation(
    handler,
    parsed: Any,
    *,
    admin_request_context: Callable[[Any, Any, str], dict[str, object]],
    require_admin_post: Callable[[Any], bool],
    anonymous_template_origin_allowed: Callable[[Any], bool],
    template_origin_error: Callable[[], tuple[str, str, int]],
    request_params: Callable[[Any], dict[str, object]],
    principal: Callable[[Any, Any], dict[str, object]],
    auth_csrf_allowed: Callable[[Any, dict[str, object]], bool],
    user_csrf_error: Callable[[], tuple[str, str, int]],
    preset_mutation_context: Callable[..., dict[str, object]],
) -> bool:
    """传入 handler 和 URL，校验管理员或私人 preset 修改权限；返回是否允许继续。"""
    admin_context = admin_request_context(parsed, handler.headers, handler.headers.get("Cookie", ""))
    if admin_context.get("authorized"):
        if not require_admin_post(parsed):
            return False
        set_preset_mutation_context(handler, preset_mutation_context(admin=True))
        return True

    if not anonymous_template_origin_allowed(handler.headers):
        handler._json_error_fields(template_origin_error())
        return False

    handler._request_params_cache = request_params(parsed)
    current_principal = principal(handler.headers, handler.client_address)
    if current_principal.get("authenticated") and not auth_csrf_allowed(handler.headers, current_principal):
        handler._json_error_fields(user_csrf_error())
        return False

    set_preset_mutation_context(
        handler,
        preset_mutation_context(current_principal["owner_id"], current_principal.get("cookie", "")),
    )
    return True


def require_file_api(
    handler,
    *,
    file_api_authorized: Callable[[Any, Any], bool],
) -> bool:
    """传入 handler 和文件 API 鉴权回调；成功返回 True，失败发送代理密钥错误。"""
    if file_api_authorized(handler.headers, handler.client_address):
        return True
    handler._json_error("PROXY_REQUIRED", "缺少或无效的代理密钥", 403)
    return False
