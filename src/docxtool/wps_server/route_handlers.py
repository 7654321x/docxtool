"""HTTP boundary for the WPS public JSON API."""

from __future__ import annotations

import json
import logging
import time
import uuid

from .auth import WpsAuthError, authenticated_session
from .config import WPS_JSON_MAX_BYTES
from .service import (
    WpsServiceError,
    authorize_format,
    current_user,
    heartbeat,
    login_user,
    logout_user,
    record_format_result,
    register_user,
)
from .validation import WpsValidationError

LOGGER = logging.getLogger("docx_tool")
API_VERSION = "wps-api-v1"


def _request_id(handler) -> str:
    value = handler.headers.get("X-DocxTool-Request-Id", "")
    return value if value else f"srv-{uuid.uuid4().hex}"


def _envelope(data, request_id: str, now: int) -> dict:
    return {"ok": True, "api_version": API_VERSION, "request_id": request_id, "server_time": now, "data": data}


def _error(code: str, message: str, request_id: str, now: int) -> dict:
    return {"ok": False, "api_version": API_VERSION, "request_id": request_id, "server_time": now, "error": {"code": code, "message": message}}


def read_wps_json_request(handler) -> dict:
    content_type = handler.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise WpsServiceError("WPS_CONTENT_TYPE_INVALID", "请求必须使用 JSON", 415)
    raw_length = handler.headers.get("Content-Length", "")
    try:
        length = int(raw_length)
    except ValueError as exc:
        raise WpsServiceError("WPS_JSON_INVALID", "请求长度无效", 400) from exc
    if length < 0 or length > WPS_JSON_MAX_BYTES:
        raise WpsServiceError("WPS_REQUEST_TOO_LARGE", "请求体超过限制", 413)
    raw = handler.rfile.read(length)
    if len(raw) != length:
        raise WpsServiceError("WPS_JSON_INVALID", "请求体不完整", 400)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WpsServiceError("WPS_JSON_INVALID", "请求体不是有效 JSON", 400) from exc
    if not isinstance(value, dict):
        raise WpsServiceError("WPS_JSON_INVALID", "请求体必须是 JSON 对象", 400)
    return value


def handle_wps_action(
    handler,
    action: str,
    *,
    connect_func,
    sql_lock,
    format_profile,
    now_func,
    client_ip_func,
    rate_allow,
) -> None:
    request_id = _request_id(handler)
    started = time.monotonic()
    start_events = {
        "register": "wps.auth.register.start",
        "login": "wps.auth.login.start",
        "format_authorize": "wps.format.authorize.start",
        "format_result": "wps.format.result.start",
    }
    if action in start_events:
        LOGGER.info("%s | request_id=%s", start_events[action], request_id[:16])
    try:
        ip = client_ip_func(handler.headers, handler.client_address)
        if action == "register":
            allowed, retry_after = rate_allow("wps-register-ip", ip, 3600, 5)
            if not allowed:
                raise WpsServiceError("RATE_LIMITED", f"请求过于频繁，请在 {retry_after} 秒后重试", 429)
            data = register_user(read_wps_json_request(handler), connect_func=connect_func, sql_lock=sql_lock, client_ip=ip, now_func=now_func, config_version=format_profile["config_version"])
            status = 201
        elif action == "login":
            payload = read_wps_json_request(handler)
            username_key = str(payload.get("username", "")).lower()
            ip_allowed, ip_retry = rate_allow("wps-login-ip", ip, 600, 300)
            name_allowed, name_retry = rate_allow("wps-login-name", username_key, 600, 10)
            if not ip_allowed or not name_allowed:
                raise WpsServiceError("RATE_LIMITED", f"请求过于频繁，请在 {max(ip_retry, name_retry)} 秒后重试", 429)
            data = login_user(payload, connect_func=connect_func, sql_lock=sql_lock, client_ip=ip, now_func=now_func, config_version=format_profile["config_version"])
            status = 200
        else:
            principal = authenticated_session(handler.headers, connect_func=connect_func, sql_lock=sql_lock, now_func=now_func)
            if action == "me":
                data = current_user(principal, config_version=format_profile["config_version"])
            elif action == "logout":
                read_wps_json_request(handler)
                data = logout_user(principal, connect_func=connect_func, sql_lock=sql_lock)
            elif action == "heartbeat":
                data = heartbeat(principal, read_wps_json_request(handler), connect_func=connect_func, sql_lock=sql_lock, client_ip=ip, now_func=now_func, config_version=format_profile["config_version"])
            elif action == "format_authorize":
                payload = read_wps_json_request(handler)
                header_id = handler.headers.get("X-DocxTool-Request-Id", "")
                if header_id and header_id != payload.get("request_id"):
                    raise WpsServiceError("REQUEST_ID_MISMATCH", "请求头与请求体编号不一致", 400)
                data = authorize_format(principal, payload, connect_func=connect_func, sql_lock=sql_lock, format_profile=format_profile, now_func=now_func)
            elif action == "format_result":
                payload = read_wps_json_request(handler)
                header_id = handler.headers.get("X-DocxTool-Request-Id", "")
                if header_id and header_id != payload.get("request_id"):
                    raise WpsServiceError("REQUEST_ID_MISMATCH", "请求头与请求体编号不一致", 400)
                data = record_format_result(principal, payload, connect_func=connect_func, sql_lock=sql_lock, now_func=now_func)
            else:
                raise WpsServiceError("WPS_ROUTE_NOT_FOUND", "接口不存在", 404)
            status = 200
        handler._json(_envelope(data, request_id, int(now_func())), status)
        if action != "heartbeat":
            LOGGER.info("wps.api.%s.completed | request_id=%s duration_ms=%s", action, request_id[:16], int((time.monotonic() - started) * 1000))
    except (WpsServiceError, WpsValidationError, WpsAuthError) as exc:
        code = exc.code
        message = exc.message
        status = getattr(exc, "status", 400)
        LOGGER.warning("wps.api.%s.failed | request_id=%s error_code=%s duration_ms=%s", action, request_id[:16], code, int((time.monotonic() - started) * 1000))
        if action == "register":
            if code == "USERNAME_TAKEN":
                event = "wps.auth.register.username_conflict"
            elif isinstance(exc, WpsValidationError):
                event = "wps.auth.register.validation_failed"
            else:
                event = "wps.auth.register.failed"
            LOGGER.warning("%s | request_id=%s error_code=%s", event, request_id[:16], code)
        elif action == "login":
            if code == "RATE_LIMITED":
                event = "wps.auth.login.rate_limited"
            elif code == "INVALID_CREDENTIALS":
                event = "wps.auth.login.credentials_rejected"
            elif isinstance(exc, WpsValidationError):
                event = "wps.auth.login.validation_failed"
            else:
                event = "wps.auth.login.failed"
            LOGGER.warning("%s | request_id=%s error_code=%s", event, request_id[:16], code)
        elif action == "format_authorize":
            LOGGER.warning(
                "wps.format.authorize.rejected | request_id=%s error_code=%s",
                request_id[:16],
                code,
            )
        elif action == "format_result":
            event = (
                "wps.format.result.conflict"
                if code == "REQUEST_STATUS_CONFLICT"
                else "wps.format.result.failed"
            )
            LOGGER.warning("%s | request_id=%s error_code=%s", event, request_id[:16], code)
        handler._json(_error(code, message, request_id, int(now_func())), status)
    except Exception:
        LOGGER.exception("wps.api.%s.failed | request_id=%s error_code=WPS_DATABASE_FAILED", action, request_id[:16])
        handler._json(_error("WPS_DATABASE_FAILED", "WPS 服务处理失败", request_id, int(now_func())), 500)
