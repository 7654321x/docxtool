"""Terminal task result persistence and in-memory state synchronization."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, MutableMapping
from threading import Lock

from docxtool.document.diagnostics import log_event


def record_task_result(
    task_id: str,
    input_path: str,
    orig_name: str,
    ip: str,
    ua: str,
    result: dict,
    *,
    tasks: MutableMapping,
    tasks_lock: Lock,
    log_task_result: Callable,
    cleanup_output_path: Callable[[str], None],
    task_output_dir: Callable[[str], str],
    prune_task_cache: Callable[[], None],
    safe_file_identifier: Callable[[str], str],
    logger,
    process_timeout: int,
) -> None:
    """传入任务结果和依赖回调，同步数据库、内存任务状态和日志后返回 None。"""
    status = result.get("status", "error")
    log_filename = result.get("log_filename", "")
    log_path = result.get("log_path", "")
    output_dir = result.get("output_dir", "")
    output_filename = result.get("output_filename", "")
    output_path = result.get("output_path", "")
    file_size = os.path.getsize(input_path) if input_path and os.path.exists(input_path) else 0
    duration_ms = int(result.get("duration_ms", 0) or 0)
    error = result.get("error", "") if status != "done" else ""
    error_code = result.get("error_code", "") if status != "done" else ""
    error_message = result.get("error_message", error) if status != "done" else ""
    sql_status = _sql_status_for_result(status)
    task_payload = _load_task_payload(tasks, tasks_lock, task_id)
    _write_task_statistics(
        task_id,
        ip,
        ua,
        orig_name,
        file_size,
        result,
        duration_ms,
        sql_status,
        error,
        log_filename,
        log_path,
        output_dir,
        output_filename,
        output_path,
        task_payload,
        error_code,
        error_message,
        log_task_result,
        safe_file_identifier,
        logger,
    )
    if status != "done":
        cleanup_output_path(task_output_dir(task_id))
    _update_memory_task(
        task_id,
        orig_name,
        ip,
        result,
        status,
        duration_ms,
        log_filename,
        output_dir,
        output_filename,
        output_path,
        error,
        error_code,
        error_message,
        tasks,
        tasks_lock,
    )
    prune_task_cache()
    _log_terminal_result(task_id, orig_name, result, status, error_code, process_timeout, safe_file_identifier, logger)


def _sql_status_for_result(status: str) -> str:
    """传入任务内部状态，返回写入统计表的兼容状态。"""
    return "done" if status == "done" else ("timeout" if status == "timeout" else "error")


def _load_task_payload(tasks: MutableMapping, tasks_lock: Lock, task_id: str) -> dict:
    """传入任务映射、锁和任务 ID，返回当前内存任务快照。"""
    with tasks_lock:
        return dict(tasks.get(task_id, {}))


def _write_task_statistics(
    task_id: str,
    ip: str,
    ua: str,
    orig_name: str,
    file_size: int,
    result: dict,
    duration_ms: int,
    sql_status: str,
    error: str,
    log_filename: str,
    log_path: str,
    output_dir: str,
    output_filename: str,
    output_path: str,
    task_payload: dict,
    error_code: str,
    error_message: str,
    log_task_result: Callable,
    safe_file_identifier: Callable[[str], str],
    logger,
) -> None:
    """传入统计字段和写库回调，尝试写入 SQL 任务统计。"""
    try:
        log_task_result(
            task_id,
            ip,
            ua,
            orig_name,
            file_size,
            result.get("doc_mode", "") if sql_status == "done" else "",
            int(result.get("paragraphs", 0) or 0),
            int(result.get("headings", 0) or 0),
            int(result.get("body", 0) or 0),
            duration_ms,
            sql_status,
            error,
            log_filename=log_filename,
            log_path=log_path,
            output_dir=output_dir,
            output_filename=output_filename,
            output_path=output_path,
            processing_options=task_payload.get("processing_options", ""),
            preset_id=task_payload.get("preset_id", ""),
            error_code=error_code,
            error_message=error_message,
        )
    except Exception as exc:
        log_event(
            logger,
            40,
            "task.statistics.persist.failed",
            "任务统计写入失败",
            module="web",
            component="statistics",
            fields={
                "task_id": task_id[:8],
                "file_id": safe_file_identifier(orig_name),
                "error_code": "TASK_STATISTICS_PERSIST_FAILED",
                "error_type": type(exc).__name__,
            },
            exc_info=True,
        )


def _update_memory_task(
    task_id: str,
    orig_name: str,
    ip: str,
    result: dict,
    status: str,
    duration_ms: int,
    log_filename: str,
    output_dir: str,
    output_filename: str,
    output_path: str,
    error: str,
    error_code: str,
    error_message: str,
    tasks: MutableMapping,
    tasks_lock: Lock,
) -> None:
    """传入任务结果字段和内存任务映射，更新用户可见任务状态。"""
    with tasks_lock:
        task = tasks.get(task_id, {})
        existing_warnings = list(task.get("compatibility_warnings", []) or [])
        result_warnings = list(result.get("compatibility_warnings", []) or [])
        task["compatibility_warnings"] = list(dict.fromkeys(existing_warnings + result_warnings))
        task["status"] = status
        task["finished_at"] = time.time()
        task["duration"] = round((duration_ms or 0) / 1000, 2)
        task["paragraphs"] = int(result.get("paragraphs", 0) or 0)
        task["log_filename"] = log_filename
        task["log_url"] = f"/log/{task_id}"
        task["output_dir"] = output_dir
        task["output_filename"] = output_filename
        task["output_path"] = output_path
        task["download_name"] = output_filename
        task["safe_download_filename"] = output_filename
        task["original_filename"] = orig_name
        task["client_ip"] = ip
        task["recognition_summary"] = result.get("recognition_summary", {})
        if status == "done":
            task["output"] = output_path
            task["error"] = ""
            task["error_code"] = ""
            task["error_message"] = ""
        else:
            task["error"] = error
            task["error_code"] = error_code
            task["error_message"] = error_message
        task["time"] = time.time()
        tasks[task_id] = task


def _log_terminal_result(
    task_id: str,
    orig_name: str,
    result: dict,
    status: str,
    error_code: str,
    process_timeout: int,
    safe_file_identifier: Callable[[str], str],
    logger,
) -> None:
    """传入终态任务字段和 logger，写入脱敏任务完成日志。"""
    file_id = safe_file_identifier(orig_name)
    duration_ms = int(result.get("duration_ms", 0) or 0)
    if status == "done":
        log_event(
            logger,
            20,
            "task.complete",
            "任务处理完成",
            module="web",
            component="task",
            fields={
                "task_id": task_id[:8],
                "file_id": file_id,
                "status": status,
                "paragraph_count": int(result.get("paragraphs", 0) or 0),
                "duration_ms": duration_ms,
            },
        )
    elif status == "timeout":
        log_event(
            logger,
            30,
            "task.timeout",
            "任务处理超时，已结束当前任务",
            module="web",
            component="task",
            fields={
                "task_id": task_id[:8],
                "file_id": file_id,
                "status": status,
                "error_code": "TASK_TIMEOUT",
                "error_type": "TimeoutError",
                "duration_ms": duration_ms,
            },
        )
    else:
        log_event(
            logger,
            40,
            "task.failed",
            "任务处理失败",
            module="web",
            component="task",
            fields={
                "task_id": task_id[:8],
                "file_id": file_id,
                "status": status,
                "error_code": error_code or "TASK_FAILED",
                "error_type": result.get("error_type") or "TaskProcessingError",
                "duration_ms": duration_ms,
            },
        )
