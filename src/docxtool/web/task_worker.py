"""Web 任务 worker 编排辅助。

本模块只处理任务执行边界选择和后台线程启动，不执行 DOCX 导入、识别或导出。
"""

from __future__ import annotations

import threading
from typing import Callable


def run_task_with_execution_boundary(
    task_id: str,
    input_path: str,
    orig_name: str,
    ip: str,
    ua: str,
    format_config: dict | None,
    request_meta: dict | None,
    *,
    is_main_thread: bool,
    direct_runner: Callable[[str, str, str, str, str, dict | None, dict | None], dict],
    subprocess_runner: Callable[[str, str, str, str, str, dict | None, dict | None], dict],
    record_result: Callable[[str, str, str, str, str, dict], None],
) -> dict:
    """传入任务参数、执行器和记录回调，选择 direct/subprocess 路径并返回任务结果。"""
    if is_main_thread:
        result = direct_runner(task_id, input_path, orig_name, ip, ua, format_config, request_meta)
    else:
        result = subprocess_runner(task_id, input_path, orig_name, ip, ua, format_config, request_meta)
    record_result(task_id, input_path, orig_name, ip, ua, result)
    return result


def start_worker_threads(
    max_workers: int,
    worker_target: Callable[[], None],
    *,
    thread_factory: Callable[..., threading.Thread] = threading.Thread,
) -> list[threading.Thread]:
    """传入 worker 数量和目标函数，启动 daemon 线程并返回线程对象列表。"""
    threads = []
    for index in range(max_workers):
        thread = thread_factory(target=worker_target, name=f"docx-worker-{index + 1}", daemon=True)
        thread.start()
        threads.append(thread)
    return threads
