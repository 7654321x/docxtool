"""DOCX 上传路由处理辅助。

本模块只负责 HTTP 上传请求的限流、落盘、DOCX 安全校验和任务入队编排；实际识别、
排版和导出仍由后台任务处理，不在这里执行。
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from typing import Any
from urllib.parse import unquote


def file_md5(path: str, *, chunk_size: int = 1024 * 1024) -> str:
    """传入文件路径和分块大小，返回该文件内容的 MD5 十六进制字符串。"""
    digest = hashlib.md5()
    with open(path, "rb") as file_obj:
        while True:
            chunk = file_obj.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _send_format_config_error(handler, error: Any) -> None:
    """传入 handler 和格式配置异常对象，按旧 JSON 错误合同发送响应。"""
    handler._json_error(
        error.code,
        error.message,
        error.status,
        field=error.field,
        reason=error.reason,
    )


def _restore_connection_timeout(connection, old_timeout: object) -> None:
    """传入连接对象和旧超时值，尽力恢复连接超时并返回 None。"""
    if old_timeout is None:
        return
    try:
        connection.settimeout(old_timeout)
    except Exception:
        pass


def handle_upload_raw(
    handler,
    *,
    principal: Callable[[Any, Any], dict[str, object]],
    client_ip: Callable[[Any, Any], str],
    is_ip_banned: Callable[[str], bool],
    upload_limit_exceeded: Callable[[str], bool],
    allow_upload: Callable[[str], bool],
    logger,
    upload_ip_banned_error: Callable[[], tuple[str, str, int] | tuple[str, str, int, int]],
    upload_limit_exceeded_error: Callable[[], tuple[str, str, int] | tuple[str, str, int, int]],
    upload_rate_limited_error: Callable[[], tuple[str, str, int] | tuple[str, str, int, int]],
    decode_format_config: Callable[[Any], dict | None],
    format_config_error_type: type[Exception],
    upload_request_meta: Callable[[Any], dict[str, object]],
    validate_requested_processing_mode: Callable[[dict | None, dict[str, object]], None],
    max_size: int,
    new_task_id: Callable[[], str],
    task_upload_dir: Callable[[str], str],
    task_upload_input_path: Callable[[str, str], str],
    upload_read_timeout_seconds: int,
    read_exact_to_file: Callable[..., int],
    timeout_errors: tuple[type[BaseException], ...],
    cleanup_incomplete_upload: Callable[[str, str], None],
    upload_timeout_error: Callable[[], tuple[str, str, int] | tuple[str, str, int, int]],
    upload_failed_error: Callable[[], tuple[str, str, int] | tuple[str, str, int, int]],
    incomplete_upload_error: Callable[[], tuple[str, str, int] | tuple[str, str, int, int]],
    validate_docx_upload: Callable[..., None],
    docx_validation_error_type: type[Exception],
    docx_validation_limits: dict[str, int],
    detect_docx_complexity: Callable[[str], list[dict[str, object]]],
    ensure_workers_started: Callable[[], None],
    enqueue_task: Callable[..., dict[str, object]],
    queue_full_error: Callable[[OverflowError], tuple[str, str, int] | tuple[str, str, int, int]],
    queued_upload_body: Callable[[str, dict[str, object], list[dict[str, object]]], dict[str, object]],
    optional_set_cookie_headers: Callable[[str], list[tuple[str, str]]],
    file_too_large_error: Callable[[], tuple[str, str, int] | tuple[str, str, int, int]],
    internal_server_error: Callable[[], tuple[str, str, int] | tuple[str, str, int, int]],
) -> None:
    """传入 handler 和上传依赖，完成上传校验、落盘、入队和 JSON 响应。"""
    current_principal = principal(handler.headers, handler.client_address)
    ip = client_ip(handler.headers, handler.client_address)
    if is_ip_banned(ip):
        logger.warning(f"[Security] banned ip blocked: {ip}")
        handler._json_error_fields(upload_ip_banned_error())
        return
    if upload_limit_exceeded(ip):
        logger.warning(f"[Security] upload limit exceeded: {ip}")
        handler._json_error_fields(upload_limit_exceeded_error())
        return
    if not allow_upload(ip):
        handler._json_error_fields(upload_rate_limited_error())
        return

    task_id = ""
    input_path = ""
    try:
        try:
            format_config = decode_format_config(handler.headers)
        except format_config_error_type as error:
            _send_format_config_error(handler, error)
            return

        request_meta = upload_request_meta(handler.headers)
        try:
            validate_requested_processing_mode(format_config, request_meta)
        except format_config_error_type as error:
            _send_format_config_error(handler, error)
            return

        try:
            length = int(handler.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        if length <= 0 or length > max_size:
            handler._json_error_fields(file_too_large_error())
            return

        task_id = new_task_id()
        raw_name = unquote(handler.headers.get("X-Filename", "upload.docx"))
        os.makedirs(task_upload_dir(task_id), exist_ok=True)
        input_path = task_upload_input_path(task_id, raw_name)

        try:
            old_timeout = handler.connection.gettimeout()
        except Exception:
            old_timeout = None
        try:
            handler.connection.settimeout(upload_read_timeout_seconds)
            written = read_exact_to_file(
                handler.rfile,
                input_path,
                length,
                timeout=upload_read_timeout_seconds,
            )
        except timeout_errors:
            cleanup_incomplete_upload(task_id, input_path)
            handler._json_error_fields(upload_timeout_error())
            return
        except Exception:
            cleanup_incomplete_upload(task_id, input_path)
            handler._json_error_fields(upload_failed_error())
            return
        finally:
            _restore_connection_timeout(handler.connection, old_timeout)

        if written != length:
            cleanup_incomplete_upload(task_id, input_path)
            handler._json_error_fields(incomplete_upload_error())
            return

        try:
            validate_docx_upload(input_path, max_upload_bytes=max_size, **docx_validation_limits)
        except docx_validation_error_type as error:
            cleanup_incomplete_upload(task_id, input_path)
            handler._json_error(error.code, error.message, error.status)
            return

        compatibility_warnings = detect_docx_complexity(input_path)
        md5_hash = file_md5(input_path)
        logger.info(
            f"[Upload] size={written} expect={length} md5={md5_hash} task={task_id[:8]} "
            f"preset={request_meta.get('preset_name','')} mode={request_meta.get('processing_mode','smart')} "
            f"frontend_config={bool(format_config)}"
        )

        ensure_workers_started()
        try:
            info = enqueue_task(
                task_id,
                input_path,
                raw_name,
                ip,
                handler.headers.get("User-Agent", ""),
                format_config=format_config,
                request_meta=request_meta,
                compatibility_warnings=compatibility_warnings,
                owner_id=current_principal["owner_id"],
            )
        except OverflowError as error:
            cleanup_incomplete_upload(task_id, input_path)
            handler._json_error_fields(queue_full_error(error))
            return

        payload = queued_upload_body(task_id, info, compatibility_warnings)
        handler._json(payload, extra_headers=optional_set_cookie_headers(current_principal.get("cookie", "")))
    except Exception:
        try:
            if task_id:
                cleanup_incomplete_upload(task_id, input_path)
        except Exception:
            pass
        handler._json_error_fields(internal_server_error())
