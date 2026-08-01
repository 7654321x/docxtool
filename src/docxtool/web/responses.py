"""Pure HTTP response helpers used by the compatibility handler."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
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


def security_headers() -> list[tuple[str, str]]:
    """无需传入数据，返回所有 HTTP 响应默认安全头。"""
    return [
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
        ("X-XSS-Protection", "1; mode=block"),
    ]


def text_response_headers(
    mime: str,
    content_length: int,
    extra_headers: Mapping[str, object] | Iterable[tuple[object, object]] | None = None,
) -> list[tuple[str, str]]:
    """传入 MIME、字节长度和可选附加头，返回文本响应基础头。"""
    return [
        ("Content-Type", f"{mime}; charset=utf-8"),
        ("Content-Length", str(content_length)),
        *normalize_extra_headers(extra_headers),
    ]


def json_response_headers(
    content_length: int,
    extra_headers: Mapping[str, object] | Iterable[tuple[object, object]] | None = None,
) -> list[tuple[str, str]]:
    """传入 JSON 字节长度和可选附加头，返回 JSON 响应基础头。"""
    return [
        ("Content-Type", "application/json"),
        ("Content-Length", str(content_length)),
        *normalize_extra_headers(extra_headers),
    ]


def docx_download_headers(content_disposition: str, file_size: int) -> list[tuple[str, str]]:
    """传入下载文件名响应头值和文件字节数，返回 DOCX 下载基础响应头。"""
    return [
        ("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("Content-Disposition", str(content_disposition)),
        ("Content-Length", str(int(file_size))),
    ]


def retry_after_headers(retry_after: int = 0) -> list[tuple[str, str]]:
    """传入重试等待秒数，返回 Retry-After 响应头列表。"""
    return [("Retry-After", str(retry_after))] if retry_after else []


def redirect_headers(
    target: str,
    extra_headers: Mapping[str, object] | Iterable[tuple[object, object]] | None = None,
) -> list[tuple[str, str]]:
    """传入跳转目标和可选附加头，返回 303 重定向需要发送的响应头。"""
    return [("Location", target), *normalize_extra_headers(extra_headers)]


def optional_set_cookie_headers(cookie_value: object = "") -> list[tuple[str, str]] | None:
    """传入可选 Cookie 字符串，存在时返回 Set-Cookie 头列表，否则返回 None。"""
    if not cookie_value:
        return None
    return [("Set-Cookie", str(cookie_value))]


def queued_upload_body(
    task_id: str,
    task_info: Mapping[str, object],
    compatibility_warnings: object = None,
) -> dict:
    """传入任务 ID、入队信息和可选兼容警告，返回上传成功 JSON 响应体。"""
    payload = {"task_id": task_id, "status": "queued", **dict(task_info)}
    if compatibility_warnings:
        payload["compatibility_warnings"] = compatibility_warnings
    return payload


def queue_full_error_message(exc: BaseException, *, default: str = "服务器繁忙，请稍后再试") -> str:
    """传入队列满异常和默认提示，返回可展示给用户的脱敏错误文本。"""
    message = str(exc)
    return message.split(":", 1)[1].strip() if ":" in message else default


def upload_ip_banned_error() -> tuple[str, str, int]:
    """无需传入数据，返回上传接口 IP 封禁错误码、提示和状态码。"""
    return "IP_BANNED", "该 IP 已被禁止访问", 403


def upload_limit_exceeded_error() -> tuple[str, str, int]:
    """无需传入数据，返回上传次数上限错误码、提示和状态码。"""
    return "UPLOAD_LIMIT_EXCEEDED", "当前 IP 在该时间段内排版次数已达上限，请稍后再试", 429


def upload_rate_limited_error() -> tuple[str, str, int]:
    """无需传入数据，返回上传频率限制错误码、提示和状态码。"""
    return "RATE_LIMITED", "请求过于频繁，请稍后再试", 429


def upload_file_too_large_error() -> tuple[str, str, int]:
    """无需传入数据，返回上传文件过大或为空的错误码、提示和状态码。"""
    return "FILE_TOO_LARGE", "文件过大或无内容", 413


def upload_timeout_error() -> tuple[str, str, int]:
    """无需传入数据，返回上传读取超时的错误码、提示和状态码。"""
    return "UPLOAD_TIMEOUT", "文件上传超时", 408


def upload_failed_error() -> tuple[str, str, int]:
    """无需传入数据，返回上传写入失败的错误码、提示和状态码。"""
    return "UPLOAD_FAILED", "文件上传失败，请重试", 400


def incomplete_upload_error() -> tuple[str, str, int]:
    """无需传入数据，返回上传内容读取不完整的错误码、提示和状态码。"""
    return "INCOMPLETE_UPLOAD", "读取不完整", 400


def queue_full_error(exc: BaseException) -> tuple[str, str, int]:
    """传入队列满异常，返回队列满错误码、提示和状态码。"""
    return "QUEUE_FULL", queue_full_error_message(exc), 503


def internal_server_error() -> tuple[str, str, int]:
    """无需传入数据，返回通用内部处理失败错误码、提示和状态码。"""
    return "INTERNAL_ERROR", "服务器处理失败，请稍后重试", 500


def invalid_task_id_error() -> tuple[str, str, int]:
    """无需传入数据，返回任务 ID 非法错误码、提示和状态码。"""
    return "INVALID_TASK_ID", "无效的任务 ID", 400


def task_not_found_error() -> tuple[str, str, int]:
    """无需传入数据，返回任务不存在错误码、提示和状态码。"""
    return "TASK_NOT_FOUND", "任务不存在或已过期", 404


def file_not_ready_error() -> tuple[str, str, int]:
    """无需传入数据，返回下载文件未就绪错误码、提示和状态码。"""
    return "FILE_NOT_READY", "文件未就绪", 400


def file_expired_error() -> tuple[str, str, int]:
    """无需传入数据，返回下载文件过期错误码、提示和状态码。"""
    return "FILE_EXPIRED", "文件已过期", 410


def log_not_found_error(*, expired: bool = False) -> tuple[str, str, int]:
    """传入日志是否过期，返回日志不存在或过期的错误码、提示和状态码。"""
    message = "日志不存在或已过期" if expired else "日志不存在"
    return "LOG_NOT_FOUND", message, 404


def auth_error_body(code: str, message: str, *, field: str = "", reason: str = "") -> dict:
    """传入错误码和提示，返回认证接口统一错误响应体。"""
    error = {"code": code, "message": message}
    if field:
        error["field"] = field
    if reason:
        error["reason"] = reason
    return {"ok": False, "error": error}


def json_error_body(
    *,
    auth_route: bool,
    code: str,
    message: str,
    field: str = "",
    reason: str = "",
    legacy_error_body: Callable[..., dict],
) -> dict:
    """传入路由类型和错误字段，返回认证或旧接口兼容的 JSON 错误体。"""
    if auth_route:
        return auth_error_body(code, message, field=field, reason=reason)
    return legacy_error_body(code, message, field=field, reason=reason)
