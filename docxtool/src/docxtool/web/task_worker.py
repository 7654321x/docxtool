"""Web 任务 worker 编排辅助。

本模块只处理任务执行边界选择和后台线程启动，不执行 DOCX 导入、识别或导出。
"""

from __future__ import annotations

import threading
import time
from queue import Empty
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


def ensure_worker_threads_started(
    worker_threads: list,
    workers_lock,
    worker_state: dict,
    *,
    max_workers: int,
    worker_target: Callable[[], None],
    start_threads: Callable[[int, Callable[[], None]], list[threading.Thread]] = start_worker_threads,
) -> bool:
    """传入线程列表、锁和启动状态，必要时启动 worker 线程并返回本次是否新启动。"""
    with workers_lock:
        if worker_state.get("started", False):
            return False
        worker_threads.extend(start_threads(max_workers, worker_target))
        worker_state["started"] = True
        return True


def wait_for_next_task(task_queue, queue_condition) -> tuple[str, tuple]:
    """传入有序任务队列和条件变量，阻塞等待并返回最早入队的任务 ID 与 payload。"""
    with queue_condition:
        while not task_queue:
            queue_condition.wait()
        return task_queue.popitem(last=False)


def mark_memory_task_processing(
    task_id: str,
    tasks: dict,
    tasks_lock,
    *,
    started_at: float | None = None,
) -> dict:
    """传入任务 ID、内存任务表和锁，写入 processing 状态并返回更新后的任务快照。"""
    if started_at is None:
        started_at = time.time()
    with tasks_lock:
        task = tasks.get(task_id, {})
        task["status"] = "processing"
        task["started_at"] = started_at
        task["queue_ahead"] = 0
        task["queue_position"] = 0
        tasks[task_id] = task
        return dict(task)


def process_next_queued_task(
    task_queue,
    queue_condition,
    tasks: dict,
    tasks_lock,
    *,
    mark_task_processing: Callable[[str], None],
    process_task: Callable[[str, str, str, str, str, dict | None, dict | None], object],
    now: Callable[[], float] = time.time,
) -> str:
    """传入队列、状态容器和处理回调，消费一个任务并返回已处理的任务 ID。"""
    task_id, payload = wait_for_next_task(task_queue, queue_condition)
    input_path, orig_name, ip, ua, format_config, request_meta = payload
    mark_task_processing(task_id)
    mark_memory_task_processing(task_id, tasks, tasks_lock, started_at=now())
    process_task(task_id, input_path, orig_name, ip, ua, format_config, request_meta)
    return task_id


def run_worker_loop(
    task_queue,
    queue_condition,
    tasks: dict,
    tasks_lock,
    *,
    mark_task_processing: Callable[[str], None],
    process_task: Callable[[str, str, str, str, str, dict | None, dict | None], object],
    now: Callable[[], float] = time.time,
) -> None:
    """传入队列、状态容器和处理回调，持续消费后台任务；本函数不返回。"""
    while True:
        process_next_queued_task(
            task_queue,
            queue_condition,
            tasks,
            tasks_lock,
            mark_task_processing=mark_task_processing,
            process_task=process_task,
            now=now,
        )


def run_task_in_subprocess(
    task_id: str,
    input_path: str,
    orig_name: str,
    ip: str,
    ua: str,
    format_config: dict | None,
    request_meta: dict | None,
    *,
    process_timeout: int,
    context_factory: Callable[[str], object],
    process_target: Callable[..., None],
    cleanup_output_path: Callable[[str], None],
    task_output_dir: Callable[[str], str],
    result_queue_timeout: int = 2,
) -> dict:
    """传入任务参数和子进程依赖，隔离执行任务并返回成功、超时或错误结果字典。"""
    ctx = context_factory("spawn")
    result_queue = ctx.Queue()
    process = ctx.Process(
        target=process_target,
        args=(result_queue, task_id, input_path, orig_name, ip, ua, format_config, request_meta),
        daemon=True,
    )
    process.start()
    process.join(process_timeout)
    if process.is_alive():
        process.terminate()
        process.join(5)
        if process.is_alive():
            try:
                process.kill()
            except Exception:
                pass
            process.join(5)
        result = {
            "status": "timeout",
            "log_filename": "",
            "log_path": "",
            "output_dir": "",
            "output_filename": "",
            "output_path": "",
            "duration_s": process_timeout,
            "duration_ms": process_timeout * 1000,
            "doc_mode": "",
            "paragraphs": 0,
            "headings": 0,
            "body": 0,
            "error": f"排版超时：超过 {process_timeout} 秒",
            "error_code": "TASK_TIMEOUT",
            "error_message": f"排版超时：超过 {process_timeout} 秒",
        }
        cleanup_output_path(task_output_dir(task_id))
        return result
    try:
        result = result_queue.get(timeout=result_queue_timeout)
    except Empty:
        result = {
            "status": "error",
            "log_filename": "",
            "log_path": "",
            "output_dir": "",
            "output_filename": "",
            "output_path": "",
            "duration_s": 0,
            "duration_ms": 0,
            "doc_mode": "",
            "paragraphs": 0,
            "headings": 0,
            "body": 0,
            "error": f"子进程未返回结果，退出码={process.exitcode}",
            "error_code": "TASK_PROCESSING_ERROR",
            "error_message": f"子进程未返回结果，退出码={process.exitcode}",
        }
    if result.get("status") != "done":
        cleanup_output_path(task_output_dir(task_id))
    return result


def run_task_process_entry(
    result_queue,
    task_id: str,
    input_path: str,
    orig_name: str,
    ip: str,
    ua: str,
    format_config: dict | None,
    request_meta: dict | None,
    *,
    process_task_body: Callable[[str, str, str, str, str, dict | None, dict | None], dict],
    sanitize_error: Callable[[object], str],
) -> dict:
    """传入结果队列、任务参数和处理回调，执行子进程任务并返回已写队列的结果字典。"""
    try:
        result = process_task_body(task_id, input_path, orig_name, ip, ua, format_config, request_meta)
    except Exception as exc:
        result = {
            "status": "error",
            "log_filename": "",
            "log_path": "",
            "output_dir": "",
            "output_filename": "",
            "output_path": "",
            "duration_s": 0,
            "duration_ms": 0,
            "doc_mode": "",
            "paragraphs": 0,
            "headings": 0,
            "body": 0,
            "error": "",
            "error_code": "TASK_PROCESSING_ERROR",
            "error_message": sanitize_error(f"{type(exc).__name__}: {exc}"),
            "recognition_summary": {},
        }
    try:
        result_queue.put(result)
    except Exception:
        pass
    return result
