"""Preset API route handlers for the Web compatibility app."""

from __future__ import annotations

from typing import Any


def handle_presets_list(handler: Any, *, principal, list_presets, optional_set_cookie_headers) -> None:
    """传入 handler、principal 和列表回调，发送当前 owner 可见 preset 列表。"""
    principal_data = principal(handler.headers, handler.client_address)
    handler._json(
        {"presets": list_presets(principal_data["owner_id"])},
        extra_headers=optional_set_cookie_headers(principal_data.get("cookie", "")),
    )


def handle_preset_detail(handler: Any, preset_id: str, *, principal, get_preset, optional_set_cookie_headers) -> None:
    """传入 handler、模板 ID 和查询回调，发送单个 preset 或稳定错误响应。"""
    normalized_id = str(preset_id or "").strip()
    if not normalized_id:
        handler._json_error("TEMPLATE_ID_INVALID", "无效的模板 ID", 400)
        return
    principal_data = principal(handler.headers, handler.client_address)
    preset = get_preset(normalized_id, owner_id=principal_data["owner_id"])
    if not preset:
        handler._json_error("TEMPLATE_NOT_FOUND", "模板不存在", 404)
        return
    handler._json(preset, extra_headers=optional_set_cookie_headers(principal_data.get("cookie", "")))


def handle_preset_create(
    handler: Any,
    *,
    insert_preset,
    preset_error_from_exception,
    optional_set_cookie_headers,
) -> None:
    """传入 handler 和插入回调，根据缓存请求参数创建 preset 并发送 JSON 响应。"""
    payload = getattr(handler, "_request_params_cache", {})
    try:
        preset = insert_preset(
            payload.get("name", ""),
            payload.get("description", ""),
            payload.get("config_json", {}),
            preset_id=payload.get("id", ""),
            owner_id=getattr(handler, "_preset_owner_id", ""),
            visibility="public" if getattr(handler, "_preset_admin", False) else "private",
        )
    except ValueError as exc:
        handler._json_error_fields(preset_error_from_exception(exc, not_found_status=400))
        return
    handler._json(
        preset,
        201,
        extra_headers=optional_set_cookie_headers(getattr(handler, "_preset_cookie_header", "")),
    )


def handle_preset_update(
    handler: Any,
    preset_id: str,
    *,
    update_preset,
    preset_error_from_exception,
    optional_set_cookie_headers,
) -> None:
    """传入 handler、模板 ID 和更新回调，根据缓存请求参数更新 preset 并发送 JSON。"""
    payload = getattr(handler, "_request_params_cache", {})
    try:
        preset = update_preset(
            preset_id,
            payload.get("name", ""),
            payload.get("description", ""),
            payload.get("config_json", {}),
            owner_id=getattr(handler, "_preset_owner_id", ""),
            public_only=getattr(handler, "_preset_public_only", True),
        )
    except ValueError as exc:
        handler._json_error_fields(preset_error_from_exception(exc))
        return
    handler._json(preset, extra_headers=optional_set_cookie_headers(getattr(handler, "_preset_cookie_header", "")))


def handle_preset_delete(
    handler: Any,
    preset_id: str,
    *,
    delete_preset,
    preset_error_from_exception,
    optional_set_cookie_headers,
) -> None:
    """传入 handler、模板 ID 和删除回调，删除 preset 并发送 JSON 结果。"""
    try:
        result = delete_preset(
            preset_id,
            owner_id=getattr(handler, "_preset_owner_id", ""),
            public_only=getattr(handler, "_preset_public_only", True),
        )
    except ValueError as exc:
        handler._json_error_fields(preset_error_from_exception(exc))
        return
    handler._json(
        result,
        200,
        extra_headers=optional_set_cookie_headers(getattr(handler, "_preset_cookie_header", "")),
    )
