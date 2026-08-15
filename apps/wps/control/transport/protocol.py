"""Pure WPS Control protocol and client-disconnect helpers."""

from __future__ import annotations

import errno
from typing import Any, Dict

from ..logging_adapter import sanitize_wps_log_fields


def error_code(error: Exception, default: str = "WPS_CONTROL_ERROR") -> str:
    code = getattr(error, "code", "")
    if isinstance(code, str) and code:
        return code
    text = str(error).strip()
    if text and text.upper() == text and len(text) <= 100:
        return text
    return default


def safe_warnings(value: Any) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[Any] = []
    for item in value[:50]:
        if isinstance(item, str):
            result.append(item[:500])
        elif isinstance(item, dict):
            result.append(
                {
                    str(key)[:80]: raw
                    for key, raw in item.items()
                    if isinstance(raw, (str, int, float, bool)) or raw is None
                }
            )
    return result


def safe_log_details(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return sanitize_wps_log_fields(value)


def request_failure_event(code: str) -> str:
    return {
        "WPS_CONTROL_UNAUTHORIZED": "control.auth.rejected",
        "WPS_CONTROL_INVALID_CONTENT_LENGTH": "control.body.length_invalid",
        "WPS_CONTROL_NEGATIVE_CONTENT_LENGTH": "control.body.length_negative",
        "WPS_CONTROL_REQUEST_TOO_LARGE": "control.body.too_large",
        "WPS_CONTROL_BODY_TRUNCATED": "control.body.truncated",
        "WPS_CONTROL_JSON_INVALID": "control.body.json_invalid",
        "WPS_CONTROL_JSON_OBJECT_REQUIRED": "control.body.object_required",
        "WPS_CONTROL_ROUTE_NOT_FOUND": "control.route.not_found",
        "WPS_COMMAND_BUSY": "control.command.busy",
        "WPS_MONITOR_NOT_RUNNING": "control.monitor.unavailable",
        "WPS_HOST_NOT_REGISTERED": "bridge.host.not_registered",
        "WPS_HOST_NOT_READY": "bridge.host.not_ready",
        "WPS_HOST_CONTEXT_MISMATCH": "bridge.host.context_mismatch",
        "WPS_HOST_CONTEXT_REPLACED": "bridge.host.context_replaced",
        "WPS_HOST_CONTEXT_REQUIRED": "bridge.host.context_required",
        "WPS_HOST_GENERATION_MISMATCH": "bridge.host.generation_mismatch",
        "WPS_HOST_GENERATION_INVALID": "bridge.host.generation_invalid",
        "WPS_REQUEST_ID_MISSING": "bridge.command.request_id_missing",
        "WPS_REQUEST_COMMAND_MISSING": "bridge.command.command_missing",
        "WPS_REQUEST_COMMAND_INVALID": "bridge.command.invalid",
        "WPS_PANE_INSTANCE_ID_MISSING": "bridge.command.pane_instance_missing",
        "WPS_BRIDGE_STATE_OBJECT_REQUIRED": "bridge.state.object_required",
        "WPS_BRIDGE_STATE_REVISION_INVALID": "bridge.state.revision_invalid",
        "WPS_BRIDGE_CLOSED": "bridge.closed",
        "WPS_BRIDGE_WAIT_TIMEOUT_INVALID": "bridge.wait.timeout_invalid",
        "WPS_PUBLIC_ACCOUNT_REQUIRED": "public.account.required",
        "WPS_PUBLIC_AUTHORIZATION_REJECTED": "public.authorization.rejected",
        "WPS_APPLY_AUTHORIZATION_REQUIRED": "bridge.command.authorization_required",
        "WPS_APPLY_AUTHORIZATION_MISMATCH": "bridge.command.authorization_mismatch",
        "WPS_APPLY_CONFIG_VERSION_REQUIRED": "bridge.command.config_version_required",
        "WPS_APPLY_FORMAT_CONFIG_REQUIRED": "bridge.command.format_config_required",
        "WPS_FORMAT_CONFIG_INVALID": "bridge.command.format_config_invalid",
        "WPS_FORMAT_PROFILE_ACCOUNT_REQUIRED": "format.profile.account_required",
        "WPS_FORMAT_PROFILE_NAME_REQUIRED": "format.profile.name_required",
        "WPS_FORMAT_PROFILE_NAME_TOO_LONG": "format.profile.name_too_long",
        "WPS_FORMAT_PROFILE_NAME_CONFLICT": "format.profile.name_conflict",
        "WPS_FORMAT_PROFILE_NOT_FOUND": "format.profile.not_found",
        "WPS_FORMAT_PROFILE_SYSTEM_LOCKED": "format.profile.system_locked",
        "WPS_FORMAT_PROFILE_CONFIG_INVALID": "format.profile.config_invalid",
        "WPS_FORMAT_PROFILE_DATABASE_FAILED": "format.profile.database_failed",
        "WPS_FORMAT_PROFILE_MIGRATION_FAILED": "format.profile.migration_failed",
        "WPS_LETTERHEAD_FORM_INVALID": "letterhead.form.invalid",
        "WPS_LETTERHEAD_MARK_REQUIRED": "letterhead.mark.required",
        "WPS_LETTERHEAD_DOCUMENT_NUMBER_INVALID": "letterhead.document_number.invalid",
        "WPS_LETTERHEAD_ALREADY_EXISTS": "letterhead.already_exists",
    }.get(code, "control.request.execution_failed")


def client_disconnected(error: OSError) -> bool:
    """判断响应写入失败是否只是本机 HTTP 客户端已经离开。"""
    return isinstance(
        error, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)
    ) or getattr(error, "winerror", None) in {10053, 10054} or getattr(
        error, "errno", None
    ) in {errno.EPIPE, errno.ECONNABORTED, errno.ECONNRESET}


class ControlClientDisconnected(Exception):
    code = "WPS_CONTROL_CLIENT_DISCONNECTED"


__all__ = [
    "ControlClientDisconnected",
    "client_disconnected",
    "error_code",
    "request_failure_event",
    "safe_log_details",
    "safe_warnings",
]
