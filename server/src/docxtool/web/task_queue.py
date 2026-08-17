"""Web 任务入队辅助。

本模块只负责把已通过上传校验的任务写入 queued 记录和内存队列，不执行 DOCX 识别、
排版或导出。调用方负责注入任务容器、锁、记录写入和缓存裁剪回调。
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, MutableMapping


def input_file_size(input_path: str) -> int:
    """传入上传文件路径，返回文件大小；文件缺失或不可读时返回 0。"""
    try:
        return os.path.getsize(input_path) if input_path and os.path.exists(input_path) else 0
    except OSError:
        return 0


def enqueue_task(
    task_id: str,
    input_path: str,
    orig_name: str,
    ip: str,
    ua: str,
    *,
    format_config: dict | None = None,
    request_meta: dict | None = None,
    compatibility_warnings: list | None = None,
    owner_id: str = "",
    task_queue: MutableMapping[str, tuple],
    queue_cond,
    tasks: MutableMapping[str, dict],
    tasks_lock,
    max_queue: int,
    active_count: Callable[[], int],
    record_task_queued: Callable[..., None],
    task_queue_info: Callable[[str], dict[str, object]],
    task_processing_options: Callable[[dict | None, dict | None], str],
    prune_task_cache: Callable[[], None],
    now_func: Callable[[], float] = time.time,
    file_size_func: Callable[[str], int] = input_file_size,
) -> dict[str, object]:
    """传入任务信息和队列依赖，写入 queued 记录、内存队列并返回队列位置。"""
    now = now_func()
    file_size = file_size_func(input_path)
    request_meta = request_meta or {}
    processing_options = task_processing_options(format_config, request_meta)
    preset_id = str(request_meta.get("preset_id", "") or "")

    with queue_cond:
        active = active_count()
        queued = len(task_queue)
        if active + queued >= max_queue:
            raise OverflowError("QUEUE_FULL: 服务器繁忙，请稍后再试")
        record_task_queued(
            task_id,
            ip,
            ua,
            orig_name,
            file_size,
            processing_options=processing_options,
            preset_id=preset_id,
            owner_id=owner_id,
        )
        task_queue[task_id] = (input_path, orig_name, ip, ua, format_config, request_meta or {})
        info = task_queue_info(task_id)
        queue_cond.notify()

    with tasks_lock:
        tasks[task_id] = {
            "status": "queued",
            "time": now,
            "queued_at": now,
            "uses_format_config": bool(format_config),
            "preset_name": request_meta.get("preset_name", ""),
            "preset_id": preset_id,
            "processing_mode": request_meta.get("processing_mode", ""),
            "filename": orig_name,
            "ip": ip,
            "processing_options": processing_options,
            "compatibility_warnings": list(compatibility_warnings or []),
            "owner_id": owner_id,
        }
    prune_task_cache()
    return info
