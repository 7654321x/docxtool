"""Task status, download, and log route handlers for the Web app."""

from __future__ import annotations

import os
from typing import Any


def handle_status(
    handler: Any,
    task_id: str,
    *,
    is_safe_uuid,
    invalid_task_id_error,
    task_not_found_error,
    principal,
    public_task_state,
) -> None:
    """传入 handler、任务 ID 和状态查询回调，发送公开任务状态或稳定错误。"""
    if not is_safe_uuid(task_id):
        handler._json_error_fields(invalid_task_id_error())
        return
    principal_data = principal(handler.headers, handler.client_address)
    task = public_task_state(task_id, principal_data["owner_id"])
    if not task:
        handler._json_error_fields(task_not_found_error())
        return
    handler._json(task)


def handle_download(
    handler: Any,
    task_id: str,
    *,
    is_safe_uuid,
    invalid_task_id_error,
    file_not_ready_error,
    file_expired_error,
    principal,
    tasks,
    tasks_lock,
    sql_lock,
    connect,
    safe_download_filename,
    content_disposition_filename,
    docx_download_headers,
    stream_file,
    path_exists=os.path.exists,
    path_getsize=os.path.getsize,
) -> None:
    """传入 handler、任务 ID、任务存储和文件回调，发送 DOCX 下载或稳定错误。"""
    if not is_safe_uuid(task_id):
        handler._json_error_fields(invalid_task_id_error())
        return
    principal_data = principal(handler.headers, handler.client_address)
    owner_id = principal_data["owner_id"]
    with tasks_lock:
        task = tasks.get(task_id)
        if task and owner_id and task.get("owner_id", "") != owner_id:
            task = None
    if not task or task.get("status") != "done":
        with sql_lock:
            conn = connect()
            row = conn.execute(
                "SELECT status, output_path, output_filename, filename FROM tasks WHERE id=? AND owner_id=?",
                (task_id, owner_id),
            ).fetchone()
            conn.close()
        if not row or row["status"] != "done":
            handler._json_error_fields(file_not_ready_error())
            return
        path = row["output_path"] or ""
        download_name = row["output_filename"] or safe_download_filename(row["filename"] or "download.docx")
    else:
        path = task.get("output_path") or task.get("output") or ""
        download_name = task.get("download_name") or safe_download_filename(task.get("filename", "download.docx"))
    if not path or not path_exists(path):
        handler._json_error_fields(file_expired_error())
        return
    try:
        file_size = path_getsize(path)
    except OSError:
        handler._json_error_fields(file_expired_error())
        return
    handler.send_response(200)
    for key, value in docx_download_headers(content_disposition_filename(download_name), file_size):
        handler.send_header(key, value)
    handler._set_cors_headers()
    handler._set_security_headers()
    handler.end_headers()
    stream_file(path, handler.wfile)


def handle_log(
    handler: Any,
    task_id: str,
    *,
    is_safe_uuid,
    invalid_task_id_error,
    log_not_found_error,
    tasks,
    tasks_lock,
    sql_lock,
    connect,
    log_dir: str,
    redact_sensitive_log,
    render_task_log_html,
    path_abspath=os.path.abspath,
    path_exists=os.path.exists,
    open_text=open,
) -> None:
    """传入 handler、任务 ID、任务存储和日志回调，发送日志 HTML 或稳定错误。"""
    if not is_safe_uuid(task_id):
        handler._json_error_fields(invalid_task_id_error())
        return
    path = ""
    with tasks_lock:
        task = tasks.get(task_id)
        if task:
            filename = task.get("log_filename", "")
            if filename:
                path = os.path.join(log_dir, filename)
    with sql_lock:
        conn = connect()
        row = conn.execute(
            """SELECT filename, status, duration_ms, error_code, error_message,
                      created_at, log_path
               FROM tasks WHERE id=?""",
            (task_id,),
        ).fetchone()
        conn.close()
    if not path:
        path = row["log_path"] if row else ""
    if not path:
        handler._json_error_fields(log_not_found_error())
        return
    root = path_abspath(log_dir)
    path = path_abspath(path)
    if not path.startswith(root + os.sep) or not path_exists(path):
        handler._json_error_fields(log_not_found_error(expired=True))
        return
    with open_text(path, "r", encoding="utf-8", errors="replace") as f:
        log_text = redact_sensitive_log(f.read())
    body = render_task_log_html(task_id, row, log_text)
    handler._text(body, "text/html")
